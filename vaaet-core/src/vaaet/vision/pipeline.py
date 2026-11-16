# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Pipe-and-Filter ordenado para analizar videos finitos.

Todos los filtros permanecen en una sesión y un proceso. Tracking, cinemática,
telemetría y render dependen del frame anterior y no admiten workers concurrentes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from time import perf_counter
from types import MappingProxyType
from typing import Protocol, TypeVar

import numpy as np
import pandas as pd

from vaaet.contracts import TrafficStatePrediction
from vaaet.exceptions import VideoValidationError
from vaaet.vision.detector import Detection
from vaaet.vision.hud import HudConfig, HudSnapshot, draw_track_annotation, render_hud
from vaaet.vision.optical_flow import OpticalFlowEstimator
from vaaet.vision.speed import (
    SmoothedSpeedTracker,
    TrackMotionStateTracker,
    estimate_speed,
    is_near_zero_motion,
    is_speed_measurement_reliable,
    robust_speed_summary,
)
from vaaet.vision.telemetry import MinuteTelemetryAccumulator
from vaaet.vision.tracking import SORTTracker, Track, TrackObservation
from vaaet.vision.view_plan import (
    CameraCalibration,
    VideoViewPlan,
    VideoViewSegment,
    ViewSegmentReport,
)

__all__ = [
    "PipelineMetrics",
    "PredictionProvider",
    "TrafficStatePrediction",
    "VisionPipelineSession",
]

_PIPELINE_STAGES: tuple[str, ...] = (
    "read",
    "perception",
    "tracking",
    "motion_telemetry",
    "render_encode",
    "minute_policy",
)

_Result = TypeVar("_Result")


class FrameCapture(Protocol):
    """Define la fuente mínima y ordenada de frames."""

    def read(self) -> tuple[bool, np.ndarray]: ...


class FrameWriter(Protocol):
    """Define el destino mínimo de frames anotados."""

    def write(self, frame: np.ndarray) -> None: ...


class Detector(Protocol):
    """Define la frontera mínima del detector vehicular."""

    def detect(self, frame: np.ndarray) -> list[Detection]: ...


PredictionProvider = Callable[[pd.DataFrame], TrafficStatePrediction | None]


@dataclass(frozen=True)
class PipelineMetrics:
    """Representa tiempos portables de una ejecución síncrona completa."""

    frames_processed: int
    processing_seconds: float
    frames_per_second: float
    stage_seconds: Mapping[str, float]

    def __post_init__(self) -> None:
        if self.frames_processed < 0:
            raise ValueError("Pipeline frames_processed cannot be negative")
        if self.processing_seconds < 0.0:
            raise ValueError("Pipeline processing_seconds cannot be negative")
        if self.frames_per_second < 0.0:
            raise ValueError("Pipeline frames_per_second cannot be negative")

        normalized = {
            stage: float(self.stage_seconds.get(stage, 0.0)) for stage in _PIPELINE_STAGES
        }
        if any(value < 0.0 for value in normalized.values()):
            raise ValueError("Pipeline stage timings cannot be negative")
        object.__setattr__(self, "stage_seconds", MappingProxyType(normalized))

    @classmethod
    def empty(cls) -> PipelineMetrics:
        """Crea el valor compatible anterior a completar una ejecución."""
        return cls(0, 0.0, 0.0, {})


class PipelineMetricsCollector:
    """Acumula tiempos con un reloj monotónico inyectable."""

    def __init__(self, *, clock: Callable[[], float] = perf_counter) -> None:
        self._clock = clock
        self._started_at = clock()
        self._stage_seconds: dict[str, float] = {stage: 0.0 for stage in _PIPELINE_STAGES}

    def measure(self, stage: str, operation: Callable[[], _Result]) -> _Result:
        """Ejecuta un filtro y acumula su tiempo transcurrido."""
        if stage not in self._stage_seconds:
            raise ValueError(f"Unsupported vision pipeline stage: {stage}")
        started_at = self._clock()
        try:
            return operation()
        finally:
            self._stage_seconds[stage] += max(self._clock() - started_at, 0.0)

    def finish(self, *, frames_processed: int) -> PipelineMetrics:
        """Materializa las métricas sin exponer el acumulador mutable."""
        elapsed = max(self._clock() - self._started_at, 0.0)
        return PipelineMetrics(
            frames_processed=frames_processed,
            processing_seconds=elapsed,
            frames_per_second=(frames_processed / elapsed) if elapsed > 0.0 else 0.0,
            stage_seconds=self._stage_seconds,
        )


@dataclass(frozen=True)
class FramePacket:
    """Representa un frame BGR con identidad estable y ordenada."""

    clip_id: str
    frame_index: int
    fps: float
    elapsed_seconds: float
    capture_time: datetime
    frame: np.ndarray

    def __post_init__(self) -> None:
        if not self.clip_id:
            raise VideoValidationError("vision.frame_read: clip_id is required")
        if self.frame_index < 1:
            raise VideoValidationError("vision.frame_read: frame_index must be positive")
        if not np.isfinite(self.fps) or self.fps <= 0.0:
            raise VideoValidationError("vision.frame_read: fps must be positive")
        if not np.isfinite(self.elapsed_seconds) or self.elapsed_seconds < 0.0:
            raise VideoValidationError("vision.frame_read: elapsed_seconds must be non-negative")
        if not isinstance(self.frame, np.ndarray) or self.frame.ndim != 3:
            raise VideoValidationError("vision.frame_read: expected a three-dimensional BGR frame")
        if self.frame.shape[0] < 1 or self.frame.shape[1] < 1 or self.frame.shape[2] != 3:
            raise VideoValidationError("vision.frame_read: invalid BGR frame shape")


@dataclass(frozen=True)
class PerceptionPacket:
    """Agrupa un frame con sus resultados de flujo óptico y detección."""

    frame: FramePacket
    global_motion: np.ndarray
    flow_tracking_ratio: float
    detections: tuple[Detection, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.global_motion, np.ndarray) or self.global_motion.shape != (2,):
            raise VideoValidationError("vision.perception: global motion must contain two values")
        if not 0.0 <= self.flow_tracking_ratio <= 1.0:
            raise VideoValidationError("vision.perception: invalid optical-flow tracking ratio")


@dataclass(frozen=True)
class TrackingPacket:
    """Agrupa la percepción luego de aplicar el estado serial de SORT."""

    perception: PerceptionPacket
    tracks: tuple[Track, ...]
    pruned_track_ids: tuple[int, ...]

    def __post_init__(self) -> None:
        track_ids = [track.track_id for track in self.tracks]
        if len(track_ids) != len(set(track_ids)):
            raise VideoValidationError("vision.tracking: duplicate active track identifiers")


@dataclass(frozen=True)
class TrackAnnotation:
    """Representa una anotación resuelta tras evaluar velocidad e inmovilidad."""

    bbox: tuple[int, int, int, int]
    vehicle_type: str
    track_id: int
    speed: float | None
    stationary: bool


@dataclass(frozen=True)
class MotionPacket:
    """Agrupa un frame luego de actualizar movimiento, velocidad y telemetría."""

    tracking: TrackingPacket
    annotations: tuple[TrackAnnotation, ...]

    def __post_init__(self) -> None:
        track_ids = {track.track_id for track in self.tracking.tracks}
        annotation_ids = [annotation.track_id for annotation in self.annotations]
        if len(annotation_ids) != len(set(annotation_ids)):
            raise VideoValidationError("vision.motion_telemetry: duplicate track annotations")
        if set(annotation_ids) != track_ids:
            raise VideoValidationError(
                "vision.motion_telemetry: annotations do not match active tracks"
            )


@dataclass(frozen=True)
class RenderedFramePacket:
    """Representa un frame anotado listo para su destino ordenado."""

    motion: MotionPacket

    @property
    def frame(self) -> np.ndarray:
        return self.motion.tracking.perception.frame.frame


@dataclass(frozen=True)
class PipelineRunOutput:
    """Agrupa la salida interna que consume la frontera pública."""

    telemetry_records: tuple[dict[str, object], ...]
    classification_records: tuple[dict[str, object], ...]
    frames_processed: int
    metrics: PipelineMetrics
    view_segments: tuple[ViewSegmentReport, ...] = ()


@dataclass
class _ViewSegmentProgress:
    """Estado interno mínimo para materializar un segmento de vista procesado."""

    segment: VideoViewSegment
    calibration: CameraCalibration
    end_frame: int
    valid_minutes: int = 0
    discarded_minutes: int = 0
    discard_reason: str | None = None

    def report(self) -> ViewSegmentReport:
        """Convierte el estado mutable de sesión en un reporte portable e inmutable."""
        return ViewSegmentReport(
            profile_id=self.calibration.profile_id,
            profile_revision=self.calibration.revision,
            start_frame=self.segment.start_frame,
            end_frame=self.end_frame,
            valid_minutes=self.valid_minutes,
            discarded_minutes=self.discarded_minutes,
            discard_reason=self.discard_reason,
        )


@dataclass
class VisionPipelineSession:
    """Coordina filtros ordenados con estado para un video finito.

    No es un worker ni una cola. El estado mutable pertenece a un único clip
    para conservar determinista la cadena de percepción.
    """

    clip_id: str
    recording_start: datetime
    fps: float
    frame_height: int
    frames_per_minute: int
    detector: Detector
    tracker: SORTTracker
    flow_estimator: OpticalFlowEstimator
    speed_tracker: SmoothedSpeedTracker
    motion_tracker: TrackMotionStateTracker
    accumulator: MinuteTelemetryAccumulator
    prediction_provider: PredictionProvider | None
    hud_config: HudConfig
    view_plan: VideoViewPlan | None = None
    clock: Callable[[], float] = perf_counter
    _latest_prediction: TrafficStatePrediction | None = field(default=None, init=False)
    _records: list[dict[str, object]] = field(default_factory=list, init=False)
    _classification_records: list[dict[str, object]] = field(default_factory=list, init=False)
    _prediction_context_records: list[dict[str, object]] = field(
        default_factory=list,
        init=False,
    )
    _view_progress: list[_ViewSegmentProgress] = field(default_factory=list, init=False)
    _active_view_index: int | None = field(default=None, init=False)
    _continuity_sequence: int = field(default=1, init=False)
    _active_calibration: CameraCalibration | None = field(default=None, init=False)
    _skip_current_minute: bool = field(default=False, init=False)
    _discarding_progress: _ViewSegmentProgress | None = field(default=None, init=False)
    _next_frame_index: int = field(default=1, init=False)
    _metrics: PipelineMetricsCollector = field(init=False)

    def __post_init__(self) -> None:
        if self.frames_per_minute < 1:
            raise ValueError("frames_per_minute must be positive")
        self._metrics = PipelineMetricsCollector(clock=self.clock)

    def run(
        self,
        capture: FrameCapture,
        writer: FrameWriter,
        *,
        max_frames: int | None,
    ) -> PipelineRunOutput:
        """Lee, filtra y escribe frames en el orden exacto de la fuente."""
        frames_processed = 0
        while max_frames is None or frames_processed < max_frames:
            ok, frame = self._metrics.measure("read", capture.read)
            if not ok:
                break

            frame_index = frames_processed + 1
            packet = FramePacket(
                clip_id=self.clip_id,
                frame_index=frame_index,
                fps=self.fps,
                elapsed_seconds=frame_index / self.fps,
                capture_time=self.recording_start
                + timedelta(seconds=frame_index / self.fps),
                frame=frame,
            )
            rendered = self.process_frame(packet)
            self._metrics.measure(
                "render_encode",
                lambda rendered_packet=rendered: writer.write(rendered_packet.frame),
            )
            frames_processed = frame_index

            if frame_index % self.frames_per_minute == 0:
                self._metrics.measure(
                    "minute_policy",
                    lambda rendered_packet=rendered: self._complete_minute(rendered_packet),
                )

        return PipelineRunOutput(
            telemetry_records=tuple(self._records),
            classification_records=tuple(self._classification_records),
            frames_processed=frames_processed,
            metrics=self._metrics.finish(frames_processed=frames_processed),
            view_segments=tuple(progress.report() for progress in self._view_progress),
        )

    def process_frame(self, packet: FramePacket) -> RenderedFramePacket:
        """Aplica los filtros sin I/O a un paquete en orden monotónico."""
        if packet.frame_index != self._next_frame_index:
            raise VideoValidationError(
                "vision.frame_order: frame_index is not the next ordered frame"
            )
        self._apply_view_plan(packet)
        perception = self._metrics.measure("perception", lambda: self._perceive(packet))
        tracking = self._metrics.measure("tracking", lambda: self._track(perception))
        motion = self._metrics.measure("motion_telemetry", lambda: self._measure_motion(tracking))
        rendered = self._metrics.measure("render_encode", lambda: self._render(motion))
        self._next_frame_index += 1
        return rendered

    def _perceive(self, packet: FramePacket) -> PerceptionPacket:
        global_motion = self.flow_estimator.update(packet.frame)
        detections = tuple(self.detector.detect(packet.frame))
        flow_tracking_ratio = (
            self.flow_estimator.last_tracking_ratio
            if self.flow_estimator.last_total_points > 0
            else 1.0
        )
        return PerceptionPacket(
            frame=packet,
            global_motion=global_motion,
            flow_tracking_ratio=flow_tracking_ratio,
            detections=detections,
        )

    def _track(self, packet: PerceptionPacket) -> TrackingPacket:
        tracks = self.tracker.update(
            [
                TrackObservation(
                    centroid=detection.centroid,
                    vehicle_type=detection.vehicle_type,
                    road_contact=detection.road_contact,
                )
                for detection in packet.detections
            ]
        )
        return TrackingPacket(
            perception=packet,
            tracks=tuple(tracks),
            pruned_track_ids=tuple(self.tracker.last_pruned_track_ids),
        )

    def _measure_motion(self, packet: TrackingPacket) -> MotionPacket:
        """Evalúa cinemática y calidad sin mezclar calibración y modo legado."""

        for track_id in packet.pruned_track_ids:
            self.speed_tracker.remove_track(track_id)
            self.motion_tracker.remove_track(track_id)
            self.accumulator.counted_tracks.discard(track_id)

        annotations: list[TrackAnnotation] = []
        for track in packet.tracks:
            recovered_gap = track.recovered_after_gap
            speed_history = (
                track.road_contact_history if self._active_calibration is not None else track.history
            )
            reliable = is_speed_measurement_reliable(
                speed_history,
                flow_tracking_ratio=packet.perception.flow_tracking_ratio,
                recovered_after_gap=recovered_gap,
            )
            speed = (
                estimate_speed(
                    speed_history,
                    fps=self.fps,
                    frame_height=self.frame_height,
                    global_motion=packet.perception.global_motion,
                    vehicle_type=track.vehicle_type,
                    calibration=self._active_calibration,
                )
                if reliable
                else None
            )
            stationary = self.motion_tracker.update(
                track.track_id,
                track.history,
                candidate_speed=speed,
            )
            if stationary or not reliable:
                self.speed_tracker.remove_track(track.track_id)
                smoothed_speed = None
            else:
                smoothed_speed = self.speed_tracker.update(track.track_id, speed)

            if not self._skip_current_minute:
                self.accumulator.observe_track(
                    track,
                    smoothed_speed=smoothed_speed,
                    reliable=reliable,
                    near_zero_motion=is_near_zero_motion(track.history),
                    stationary_confirmed=stationary,
                    recovered_gap=recovered_gap,
                    flow_tracking_ratio=packet.perception.flow_tracking_ratio,
                )
            annotations.append(
                TrackAnnotation(
                    bbox=_nearest_detection_bbox(track, packet.perception.detections),
                    vehicle_type=track.vehicle_type,
                    track_id=track.track_id,
                    speed=smoothed_speed,
                    stationary=stationary,
                )
            )

        return MotionPacket(tracking=packet, annotations=tuple(annotations))

    def _render(self, packet: MotionPacket) -> RenderedFramePacket:
        frame = packet.tracking.perception.frame.frame
        for annotation in packet.annotations:
            draw_track_annotation(
                frame,
                bbox=annotation.bbox,
                vehicle_type=annotation.vehicle_type,
                track_id=annotation.track_id,
                speed=annotation.speed,
                stationary=annotation.stationary,
                config=self.hud_config,
            )
        render_hud(
            frame,
            _build_hud_snapshot(
                self.accumulator,
                self._latest_prediction,
                packet.tracking.perception.frame.elapsed_seconds,
                inference_enabled=self.prediction_provider is not None,
            ),
            self.hud_config,
        )
        return RenderedFramePacket(motion=packet)

    def _complete_minute(self, packet: RenderedFramePacket) -> None:
        if self._skip_current_minute:
            self.accumulator.discard_minute()
            self._skip_current_minute = False
            if self._discarding_progress is not None:
                self._discarding_progress.discarded_minutes += 1
                self._discarding_progress.discard_reason = "transition_crossed_minute"
                self._discarding_progress = None
            return
        record = self.accumulator.build_record(
            packet.motion.tracking.perception.frame.capture_time,
            continuity_id=self._current_continuity_id(),
        )
        self._records.append(record)
        if self._view_progress:
            self._view_progress[-1].valid_minutes += 1
        prediction = self._request_minute_prediction(record)
        self._latest_prediction = prediction
        if prediction is not None:
            self._classification_records.append(_prediction_record(prediction, record))
        self.accumulator.rollover_minute()

    def _apply_view_plan(self, packet: FramePacket) -> None:
        """Activa el perfil de la vista actual y aísla cualquier transición declarada."""
        if self.view_plan is None:
            return
        height, width = packet.frame.shape[:2]
        view_index = self.view_plan.segment_index(packet.frame_index)
        calibration = self.view_plan.resolve(packet.frame_index, width=width, height=height)
        if self._active_view_index == view_index:
            if self._view_progress:
                self._view_progress[-1].end_frame = packet.frame_index
            return

        segment = self.view_plan.segments[view_index]
        if self._active_view_index is not None:
            self._reset_for_view_transition()
            self._continuity_sequence += 1
            if not self._starts_minute(packet.frame_index):
                self.accumulator.discard_minute()
                self._skip_current_minute = True
        self._active_view_index = view_index
        self._active_calibration = calibration
        progress = _ViewSegmentProgress(
            segment=segment,
            calibration=calibration,
            end_frame=packet.frame_index,
        )
        self._view_progress.append(progress)
        if self._skip_current_minute:
            self._discarding_progress = progress

    def _reset_for_view_transition(self) -> None:
        """Evita transportar identidad, cinemática o contexto temporal entre cámaras."""
        self.flow_estimator.reset()
        self.tracker.reset()
        self.speed_tracker.reset()
        self.motion_tracker.reset()
        self._latest_prediction = None
        self._prediction_context_records.clear()

    def _request_minute_prediction(
        self,
        record: dict[str, object],
    ) -> TrafficStatePrediction | None:
        """Aísla el historial de inferencia entre vistas sin alterar el modo legado."""
        if self.view_plan is None:
            return _request_prediction(self.prediction_provider, self._records[:-1], record)
        self._prediction_context_records.append(record)
        if len(self._prediction_context_records) < 2:
            return None
        return _request_prediction(
            self.prediction_provider,
            self._prediction_context_records[:-1],
            record,
        )

    def _starts_minute(self, frame_index: int) -> bool:
        """Indica si el frame abre un bucket temporal nuevo de la fuente."""
        return (frame_index - 1) % self.frames_per_minute == 0

    def _current_continuity_id(self) -> str:
        """Identifica el tramo visual continuo sin exponerlo como feature."""
        return f"{self.clip_id}:continuity-{self._continuity_sequence:04d}"


def _nearest_detection_bbox(
    track: Track,
    detections: tuple[Detection, ...],
) -> tuple[int, int, int, int]:
    same_type = [item for item in detections if item.vehicle_type == track.vehicle_type]
    if not same_type:
        center_x, center_y = track.centroid
        return (center_x - 30, center_y - 20, center_x + 30, center_y + 20)
    detection = min(
        same_type,
        key=lambda item: (item.centroid[0] - track.centroid[0]) ** 2
        + (item.centroid[1] - track.centroid[1]) ** 2,
    )
    return detection.bbox


def _build_hud_snapshot(
    accumulator: MinuteTelemetryAccumulator,
    prediction: TrafficStatePrediction | None,
    elapsed_seconds: float,
    *,
    inference_enabled: bool,
) -> HudSnapshot:
    cumulative_counts = {
        kind: accumulator.cumulative_counts.get(kind, 0) + accumulator.minute_counts.get(kind, 0)
        for kind in ("car", "truck", "bus", "motorcycle", "bicycle")
    }
    reliable_count = len(accumulator.reliable_speed_track_ids)
    rejected_count = len(accumulator.rejected_speed_track_ids - accumulator.reliable_speed_track_ids)
    quality_attempts = reliable_count + rejected_count
    return HudSnapshot(
        elapsed_seconds=elapsed_seconds,
        cumulative_counts=cumulative_counts,
        average_speed=(
            robust_speed_summary(accumulator.minute_speeds) if accumulator.minute_speeds else None
        ),
        inference_enabled=inference_enabled,
        state=prediction.state if prediction is not None else None,
        confidence=prediction.confidence if prediction is not None else None,
        evidence=prediction.evidence if prediction is not None else None,
        incident_candidate=prediction.incident_candidate if prediction is not None else False,
        measurement_quality=(reliable_count / quality_attempts if quality_attempts else None),
    )


def _request_prediction(
    provider: PredictionProvider | None,
    records: list[dict[str, object]],
    current_record: dict[str, object],
) -> TrafficStatePrediction | None:
    if provider is None:
        return None
    return provider(pd.DataFrame([*records, current_record]))


def _prediction_record(
    prediction: TrafficStatePrediction,
    telemetry_record: dict[str, object],
) -> dict[str, object]:
    return {
        "clip_id": telemetry_record["clip_id"],
        "continuity_id": telemetry_record["continuity_id"],
        "record_time": telemetry_record["record_time"],
        "traffic_state": prediction.state,
        "state_label": prediction.label,
        "confidence": prediction.confidence,
        "evidence": prediction.evidence,
        "incident_candidate": prediction.incident_candidate,
    }
