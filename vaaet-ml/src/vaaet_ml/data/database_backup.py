# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Lectura segura de backups PostgreSQL sin ejecutar SQL del dump."""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from vaaet.exceptions import ArtifactNotFoundError, ArtifactValidationError
from vaaet.timestamps import normalize_timestamp_series

from vaaet_ml.data.database_queries import RAW_TABLE

FEATURE_TABLE = "vaaet_ml.telemetry_features"
PREDICTION_TABLE = "vaaet_ml.traffic_predictions"
VALIDATION_TABLE = "vaaet_feedback.human_validations"

_RECOGNIZED_BACKUP_TABLES = {
    RAW_TABLE,
    FEATURE_TABLE,
    PREDICTION_TABLE,
    VALIDATION_TABLE,
    # Corridas y comprobantes son la evidencia que exige ADR-0034 para admitir
    # decisiones humanas desde un backup.
    "vaaet_ops.pipeline_runs",
    "vaaet_ops.persistence_receipts",
    "public.traffic_data",
    "public.telemetry_raw",
    "public.traffic_classifications",
}
_TOC_TABLE_DATA_PATTERN = re.compile(
    r"^\s*(?P<dump_id>\d+);\s+\d+\s+\d+\s+TABLE DATA\s+"
    r"(?P<schema>\S+)\s+(?P<table>\S+)\s+.+$",
    re.IGNORECASE,
)
_COPY_PATTERN = re.compile(
    r"COPY\s+(?:(?P<schema>[\w\"]+)\.)?(?P<table>[\w\"]+)\s*"
    r"\((?P<columns>[^)]+)\)\s+FROM\s+stdin;",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _BackupCatalogEntry:
    """Entrada exacta TABLE DATA preservada desde la tabla de contenidos."""

    qualified_name: str
    toc_line: str


def _resolve_pg_restore(pg_restore_path: str | Path | None) -> Path:
    if pg_restore_path is None:
        discovered = shutil.which("pg_restore")
        if not discovered:
            raise ArtifactNotFoundError("pg_restore not found; install PostgreSQL client 17.")
        return Path(discovered).resolve()
    resolved = Path(pg_restore_path).expanduser().resolve()
    if not resolved.is_file():
        raise ArtifactNotFoundError("Explicit pg_restore binary was not found.")
    if not os.access(resolved, os.X_OK):
        raise ArtifactValidationError("Explicit pg_restore binary is not executable.")
    return resolved


def _pg_restore_version(binary: Path) -> str:
    result = subprocess.run(
        [str(binary), "--version"], capture_output=True, text=True, check=False
    )
    version = result.stdout.strip()
    if result.returncode != 0 or not version:
        raise ArtifactValidationError("Cannot execute PostgreSQL backup reader.")
    return version


def get_pg_restore_version(pg_restore_path: str | Path | None = None) -> str:
    """Devuelve una versión de pg_restore validada y apta para diagnóstico."""

    return _pg_restore_version(_resolve_pg_restore(pg_restore_path))


def _read_backup_catalog(backup: Path, binary: Path) -> tuple[_BackupCatalogEntry, ...]:
    result = subprocess.run(
        [str(binary), "-l", str(backup)], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise ArtifactValidationError("Cannot inspect PostgreSQL backup with the configured reader.")
    entries: list[_BackupCatalogEntry] = []
    for line in result.stdout.splitlines():
        match = _TOC_TABLE_DATA_PATTERN.match(line)
        if not match:
            continue
        schema = match.group("schema").strip(chr(34))
        table = match.group("table").strip(chr(34))
        entries.append(_BackupCatalogEntry(f"{schema}.{table}", line.strip()))
    return tuple(entries)


def inspect_backup_catalog(
    backup_path: str | Path,
    *,
    pg_restore_path: str | Path | None = None,
) -> tuple[str, ...]:
    """Lista sólo las tablas reconocidas y disponibles en un backup existente."""

    backup = Path(backup_path)
    if not backup.is_file():
        raise ArtifactNotFoundError("Backup file was not found.")
    binary = _resolve_pg_restore(pg_restore_path)
    entries = _read_backup_catalog(backup, binary)
    recognized = {
        entry.qualified_name
        for entry in entries
        if entry.qualified_name in _RECOGNIZED_BACKUP_TABLES
    }
    return tuple(sorted(recognized))


def restore_backup_to_sql(
    backup_path: str | Path,
    output_path: str | Path | None = None,
    pg_restore_path: str | Path | None = None,
    tables: Sequence[str] | None = None,
) -> Path:
    """Extrae datos de un backup a SQL temporal y verifica tablas solicitadas."""

    backup = Path(backup_path)
    if not backup.is_file():
        raise ArtifactNotFoundError("Backup file was not found.")
    binary = _resolve_pg_restore(pg_restore_path)
    version = _pg_restore_version(binary)
    destination = Path(output_path) if output_path else backup.with_suffix(".sql")
    destination.unlink(missing_ok=True)
    requested_tables, entries = _resolve_requested_tables(backup, binary, tables)
    toc_path = _write_table_of_contents(entries, requested_tables)
    command = _restore_command(binary, backup, destination, toc_path)
    try:
        result = _run_restore(command, destination)
    finally:
        if toc_path is not None:
            toc_path.unlink(missing_ok=True)
    _validate_restored_sql(result, destination, requested_tables, version)
    return destination


def _resolve_requested_tables(
    backup: Path, binary: Path, tables: Sequence[str] | None
) -> tuple[tuple[str, ...], dict[str, _BackupCatalogEntry]]:
    """Resuelve las tablas solicitadas antes de crear cualquier salida temporal."""

    requested = tuple(dict.fromkeys(tables or ()))
    if not requested:
        return requested, {}
    entries = _read_backup_catalog(backup, binary)
    by_name = {entry.qualified_name: entry for entry in entries}
    missing = [table_name for table_name in requested if table_name not in by_name]
    if missing:
        recognized = sorted(set(by_name) & _RECOGNIZED_BACKUP_TABLES)
        raise ArtifactValidationError(
            "PostgreSQL backup selection did not match requested TABLE DATA entries: "
            f"missing={missing}, recognized={recognized}"
        )
    return requested, by_name


def _write_table_of_contents(
    entries: dict[str, _BackupCatalogEntry], requested: Sequence[str]
) -> Path | None:
    """Crea la lista efímera que limita pg_restore a las tablas validadas."""

    if not requested:
        return None
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".toc", delete=False) as handle:
        handle.write("\n".join(entries[name].toc_line for name in requested))
        handle.write("\n")
        return Path(handle.name)


def _restore_command(binary: Path, backup: Path, destination: Path, toc_path: Path | None) -> list[str]:
    command = [str(binary), "--data-only", "--no-owner", "--no-acl", "--no-comments"]
    if toc_path is not None:
        command.extend(["--use-list", str(toc_path)])
    return [*command, "-f", str(destination), str(backup)]


def _run_restore(command: Sequence[str], destination: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        destination.unlink(missing_ok=True)
        raise


def _validate_restored_sql(
    result: subprocess.CompletedProcess[str],
    destination: Path,
    requested_tables: Sequence[str],
    reader_version: str,
) -> None:
    stderr = result.stderr.strip().lower()
    if any(value in stderr for value in ("unsupported version", "unsupported archive")):
        _discard_invalid_sql(destination, "PostgreSQL backup reader version is incompatible.")
    if result.returncode != 0:
        _discard_invalid_sql(destination, "PostgreSQL backup extraction failed.")
    if not destination.is_file() or destination.stat().st_size == 0:
        _discard_invalid_sql(destination, "PostgreSQL backup extraction produced no data.")
    _validate_requested_copy_blocks(destination, requested_tables, reader_version)


def _validate_requested_copy_blocks(
    destination: Path, requested_tables: Sequence[str], reader_version: str
) -> None:
    missing = [name for name in requested_tables if name not in _copy_tables(destination)]
    if missing:
        _discard_invalid_sql(
            destination,
            "PostgreSQL backup extraction produced no COPY block for requested tables: "
            f"{missing} (reader={reader_version})",
        )


def _discard_invalid_sql(destination: Path, message: str) -> None:
    destination.unlink(missing_ok=True)
    raise ArtifactValidationError(message)


def _copy_tables(path: Path) -> set[str]:
    tables: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            match = _COPY_PATTERN.match(line.strip())
            if match:
                schema = (match.group("schema") or "public").strip(chr(34))
                table = match.group("table").strip(chr(34))
                tables.add(f"{schema}.{table}")
    return tables


def parse_sql_dump_tables(sql_path: str | Path) -> dict[str, pd.DataFrame]:
    """Lee bloques COPY reconocidos sin ejecutar contenido del dump SQL."""

    path = Path(sql_path)
    if not path.is_file():
        raise ArtifactNotFoundError("SQL dump file was not found.")
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    frames: dict[str, pd.DataFrame] = {}
    index = 0
    while index < len(lines):
        match = _COPY_PATTERN.match(lines[index].strip())
        if not match:
            index += 1
            continue
        schema = (match.group("schema") or "public").strip('"')
        table_name = match.group("table").strip('"')
        columns = [column.strip().strip('"') for column in match.group("columns").split(",")]
        rows: list[str] = []
        index += 1
        while index < len(lines) and lines[index].strip() != "\\.":
            if lines[index]:
                rows.append(lines[index])
            index += 1
        qualified_name = f"{schema}.{table_name}"
        frames[qualified_name] = _copy_frame(rows, columns)
        index += 1
    return frames


def _copy_frame(rows: list[str], columns: list[str]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.read_csv(
        io.StringIO("\n".join(rows)),
        sep="\t",
        header=None,
        names=columns,
        na_values=["\\N"],
        float_precision="round_trip",
    )


def parse_sql_dump(sql_path: str | Path) -> pd.DataFrame:
    """Devuelve telemetría reconocida y convierte sólo columnas numéricas seguras."""

    frames = parse_sql_dump_tables(sql_path)
    raw = frames.get(RAW_TABLE)
    if raw is None:
        raw = frames.get("public.traffic_data")
    if raw is None:
        raise ValueError("No COPY block for a recognized traffic_data table was found.")
    for column in raw.columns:
        if column == "record_time":
            raw[column] = normalize_timestamp_series(raw[column])
        elif column not in {"clip_id", "telemetry_schema_version", "pipeline_run_id"}:
            converted = pd.to_numeric(raw[column], errors="coerce")
            if raw[column].isna().equals(converted.isna()):
                raw[column] = converted
    return raw


def load_from_backup(
    backup_path: str | Path,
    cache_csv: str | Path | None = None,
    pg_restore_path: str | Path | None = None,
) -> pd.DataFrame:
    """Restaura, parsea y elimina el SQL temporal; el CSV de cache es opt-in."""

    sql_path = restore_backup_to_sql(backup_path, pg_restore_path=pg_restore_path)
    try:
        frame = parse_sql_dump(sql_path)
    finally:
        sql_path.unlink(missing_ok=True)
    if cache_csv is not None:
        destination = Path(cache_csv)
        destination.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(destination, index=False)
    return frame


__all__ = [
    "FEATURE_TABLE",
    "PREDICTION_TABLE",
    "VALIDATION_TABLE",
    "get_pg_restore_version",
    "inspect_backup_catalog",
    "load_from_backup",
    "parse_sql_dump",
    "parse_sql_dump_tables",
    "restore_backup_to_sql",
]
