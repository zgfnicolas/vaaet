# SPDX-FileCopyrightText: 2026 VAAET Contributors
# SPDX-License-Identifier: AGPL-3.0-only
"""Tests for vaaet_ml.data.database utilities.

Only pure functions are tested. Actual DB connections require credentials
and are marked with ``@pytest.mark.db`` (skipped by default).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pandas as pd
import pytest

from vaaet_ml.data.database import (
    HUMAN_GROUND_TRUTH_QUERY,
    DatabaseProfile,
    DatabaseSettings,
    _settings_url,
    load_telemetry_window,
)


def test_human_ground_truth_uses_effective_validated_label() -> None:
    normalized = " ".join(HUMAN_GROUND_TRUTH_QUERY.split())
    assert "vaaet_feedback.effective_human_labels" in normalized


def test_telemetry_window_requires_aware_ordered_bounds() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        load_telemetry_window(
            start=pd.Timestamp("2026-01-01"),
            end=pd.Timestamp("2026-01-02"),
        )
    with pytest.raises(ValueError, match="end must be after start"):
        load_telemetry_window(
            start=pd.Timestamp("2026-01-02T00:00:00Z"),
            end=pd.Timestamp("2026-01-01T00:00:00Z"),
        )


def test_telemetry_window_binds_optional_filters_without_sql_interpolation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_read_sql(statement, engine, *, params):
        captured["statement"] = str(statement)
        captured["engine"] = engine
        captured["params"] = params
        return pd.DataFrame({"clip_id": ["clip-a"]})

    monkeypatch.setattr("vaaet_ml.data.database.pd.read_sql", fake_read_sql)
    engine = object()
    result = load_telemetry_window(
        start=pd.Timestamp("2026-01-01T00:00:00Z"),
        end=pd.Timestamp("2026-01-02T00:00:00Z"),
        pipeline_run_ids=("run-a",),
        clip_ids=("clip-a",),
        engine=engine,  # type: ignore[arg-type]
    )

    assert result["clip_id"].tolist() == ["clip-a"]
    assert captured["engine"] is engine
    assert "pipeline_run_id IN" in str(captured["statement"])
    assert "clip_id IN" in str(captured["statement"])
    assert captured["params"] == {
        "start": pd.Timestamp("2026-01-01T00:00:00Z"),
        "end": pd.Timestamp("2026-01-02T00:00:00Z"),
        "pipeline_run_ids": ["run-a"],
        "clip_ids": ["clip-a"],
    }


class TestBuildConnectionUrl:
    """Validate URL.create encoding and secret redaction."""

    def test_standard_config(self) -> None:
        settings = DatabaseSettings(
            DatabaseProfile.TRAINING, "db.example.com", 5432, "traffic", "admin", "secret", "require"
        )
        result = _settings_url(settings)
        assert result.drivername == "postgresql+psycopg2"
        assert result.host == "db.example.com"

    def test_special_chars_in_password(self) -> None:
        settings = DatabaseSettings(
            DatabaseProfile.TRAINING, "localhost", 5432, "test", "admin", "p@ss:w0rd", "disable"
        )
        rendered = _settings_url(settings).render_as_string(hide_password=False)
        assert "p%40ss%3Aw0rd" in rendered
        assert "p@ss:w0rd" not in repr(settings)

    def test_custom_port(self) -> None:
        settings = DatabaseSettings(
            DatabaseProfile.TRAINING, "h", 15432, "d", "u", "p", "require"
        )
        assert _settings_url(settings).port == 15432

    def test_rejects_insecure_remote_connection(self) -> None:
        with pytest.raises(ValueError, match="localhost"):
            DatabaseSettings(
                DatabaseProfile.TRAINING, "db.example.com", 5432, "d", "u", "p", "disable"
            )


class TestDatabaseSettingsLoader:
    """Test profile-specific environment resolution."""

    def test_reads_colab_secrets_without_copying_to_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import os
        import sys
        import types

        from vaaet_ml.data.database import load_database_settings

        values = {
            "VAAET_DB_HOST": "db.example.com",
            "VAAET_DB_NAME": "vaaet",
            "VAAET_DB_SSLMODE": "require",
            "VAAET_TRAINING_DB_USER": "trainer",
            "VAAET_TRAINING_DB_PASSWORD": "secret",
        }

        class Secrets:
            @staticmethod
            def get(name: str) -> str:
                if name not in values:
                    raise KeyError(name)
                return values[name]

        google = types.ModuleType("google")
        colab = types.ModuleType("google.colab")
        colab.userdata = Secrets()
        google.colab = colab
        monkeypatch.setitem(sys.modules, "google", google)
        monkeypatch.setitem(sys.modules, "google.colab", colab)
        for name in values:
            monkeypatch.delenv(name, raising=False)

        settings = load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)
        assert settings.host == "db.example.com"
        assert settings.username == "trainer"
        assert "VAAET_TRAINING_DB_PASSWORD" not in os.environ

    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from vaaet_ml.data.database import load_database_settings

        monkeypatch.setenv("VAAET_DB_HOST", "test-host")
        monkeypatch.setenv("VAAET_DB_PORT", "5433")
        monkeypatch.setenv("VAAET_DB_NAME", "test-db")
        monkeypatch.setenv("VAAET_TRAINING_DB_USER", "test-user")
        monkeypatch.setenv("VAAET_TRAINING_DB_PASSWORD", "test-pass")
        monkeypatch.setenv("VAAET_DB_SSLMODE", "require")

        config = load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)
        assert config.host == "test-host"
        assert config.port == 5433
        assert config.database == "test-db"

    def test_default_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from vaaet_ml.data.database import load_database_settings
        from vaaet_ml.settings import DEFAULT_DB_PORT

        monkeypatch.setenv("VAAET_DB_HOST", "host")
        monkeypatch.setenv("VAAET_DB_NAME", "db")
        monkeypatch.setenv("VAAET_TRAINING_DB_USER", "user")
        monkeypatch.setenv("VAAET_TRAINING_DB_PASSWORD", "pass")
        monkeypatch.setenv("VAAET_DB_SSLMODE", "require")
        monkeypatch.delenv("VAAET_DB_PORT", raising=False)

        config = load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)
        assert config.port == int(DEFAULT_DB_PORT)

    def test_legacy_environment_is_visible_and_deprecated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vaaet_ml.data.database import load_database_settings

        for name in (
            "VAAET_DB_HOST",
            "VAAET_DB_NAME",
            "VAAET_TRAINING_DB_USER",
            "VAAET_TRAINING_DB_PASSWORD",
        ):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv("DB_HOST", "localhost")
        monkeypatch.setenv("DB_NAME", "vaaet")
        monkeypatch.setenv("DB_USER", "legacy")
        monkeypatch.setenv("DB_PASSWORD", "legacy-secret")
        monkeypatch.setenv("VAAET_DB_SSLMODE", "disable")
        with pytest.warns(FutureWarning, match="removed in VAAET 5.0"):
            settings = load_database_settings(DatabaseProfile.TRAINING)
        assert settings.username == "legacy"

    def test_non_interactive_raises_without_env(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """interactive=False must raise RuntimeError when env vars are missing."""
        from vaaet_ml.data.database import load_database_settings

        for var in (
            "VAAET_DB_HOST", "VAAET_DB_PORT", "VAAET_DB_NAME",
            "VAAET_TRAINING_DB_USER", "VAAET_TRAINING_DB_PASSWORD",
            "DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD",
        ):
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(RuntimeError, match="not configured"):
            load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)

    def test_env_file_is_loaded_only_when_explicit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pytest.importorskip("dotenv")
        from vaaet_ml.data.database import load_database_settings

        names = (
            "VAAET_DB_HOST",
            "VAAET_DB_NAME",
            "VAAET_TRAINING_DB_USER",
            "VAAET_TRAINING_DB_PASSWORD",
            "VAAET_DB_SSLMODE",
        )
        for name in names:
            monkeypatch.delenv(name, raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text(
            "VAAET_DB_HOST=localhost\n"
            "VAAET_DB_NAME=vaaet\n"
            "VAAET_TRAINING_DB_USER=trainer\n"
            "VAAET_TRAINING_DB_PASSWORD=secret\n"
            "VAAET_DB_SSLMODE=disable\n",
            encoding="utf-8",
        )
        with pytest.raises(RuntimeError, match="not configured"):
            load_database_settings(DatabaseProfile.TRAINING, allow_legacy=False)
        settings = load_database_settings(
            DatabaseProfile.TRAINING, env_file=env_file, allow_legacy=False
        )
        assert settings.host == "localhost"


class TestRestoreBackupToSql:
    """Test restore_backup_to_sql() error handling (no pg_restore needed)."""

    def test_missing_backup_file(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import restore_backup_to_sql

        with pytest.raises(FileNotFoundError, match="Backup file was not found"):
            restore_backup_to_sql(tmp_path / "nonexistent.backup")

    def test_missing_pg_restore(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "test.backup"
        backup.write_bytes(b"\x00" * 100)

        monkeypatch.setenv("PATH", str(tmp_path))

        with pytest.raises(FileNotFoundError, match="pg_restore not found"):
            restore_backup_to_sql(backup)

    def test_missing_explicit_pg_restore(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "test.backup"
        backup.write_bytes(b"PGDMP")

        with pytest.raises(FileNotFoundError, match="Explicit pg_restore binary was not found"):
            restore_backup_to_sql(
                backup,
                pg_restore_path=tmp_path / "missing-pg_restore",
            )

    def test_rejects_non_executable_explicit_pg_restore(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "test.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore"
        pg_restore.write_text("binary", encoding="utf-8")
        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: False)

        with pytest.raises(ValueError, match="not executable"):
            restore_backup_to_sql(backup, pg_restore_path=pg_restore)

    def test_uses_explicit_pg_restore_binary(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "test.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore-17"
        pg_restore.write_text("binary", encoding="utf-8")
        output = tmp_path / "dump.sql"
        calls: list[list[str]] = []

        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)

        def fake_run(command, **_kwargs):
            calls.append(command)
            if "--version" in command:
                return MagicMock(returncode=0, stdout="pg_restore (PostgreSQL) 17.6", stderr="")
            output.write_text("-- restored", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("vaaet_ml.data.database.subprocess.run", fake_run)

        result = restore_backup_to_sql(
            backup,
            output_path=output,
            pg_restore_path=pg_restore,
        )

        expected = str(pg_restore.resolve())
        assert result == output
        assert calls[0][0] == expected
        assert calls[1][0] == expected

    def test_version_mismatch_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Una incompatibilidad del lector no debe filtrar binarios ni stderr."""
        from unittest.mock import MagicMock, patch

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "test.backup"
        backup.write_bytes(b"\x00" * 100)

        monkeypatch.setattr("vaaet_ml.data.database.shutil.which", lambda _: "/usr/bin/pg_restore")

        ver_result = MagicMock(returncode=0, stdout="pg_restore (PostgreSQL) 14.0")
        run_result = MagicMock(
            returncode=1,
            stderr="pg_restore: error: unsupported version (1.16) in file header",
        )

        call_count = 0

        def fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ver_result
            return run_result

        with patch("vaaet_ml.data.database.subprocess.run", side_effect=fake_run):
            with pytest.raises(ValueError, match="reader version is incompatible"):
                restore_backup_to_sql(backup)

    def test_selects_exact_schema_qualified_table_via_toc(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "legacy.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore-17"
        pg_restore.write_text("binary", encoding="utf-8")
        output = tmp_path / "legacy.sql"
        commands: list[list[str]] = []
        selected_toc = ""

        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)

        def fake_run(command, **_kwargs):
            nonlocal selected_toc
            commands.append(command)
            if "--version" in command:
                return MagicMock(
                    returncode=0, stdout="pg_restore (PostgreSQL) 17.10", stderr=""
                )
            if "-l" in command:
                return MagicMock(
                    returncode=0,
                    stdout="321; 0 987 TABLE DATA public traffic_data postgres\n",
                    stderr="",
                )
            toc_path = Path(command[command.index("--use-list") + 1])
            selected_toc = toc_path.read_text(encoding="utf-8")
            output.write_text(
                "COPY public.traffic_data (clip_id, record_time) FROM stdin;\n"
                "clip-a\t2026-08-09 12:00:00\n\\.\n",
                encoding="utf-8",
            )
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("vaaet_ml.data.database.subprocess.run", fake_run)

        result = restore_backup_to_sql(
            backup,
            output_path=output,
            pg_restore_path=pg_restore,
            tables=("public.traffic_data",),
        )

        restore_command = commands[-1]
        assert result == output
        assert "--use-list" in restore_command
        assert "--table" not in restore_command
        assert "public.traffic_data" not in restore_command
        assert selected_toc == "321; 0 987 TABLE DATA public traffic_data postgres\n"

    def test_rejects_nonzero_restore_and_removes_partial_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "legacy.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore-17"
        pg_restore.write_text("binary", encoding="utf-8")
        output = tmp_path / "partial.sql"
        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)

        def fake_run(command, **_kwargs):
            if "--version" in command:
                return MagicMock(
                    returncode=0, stdout="pg_restore (PostgreSQL) 17.10", stderr=""
                )
            output.write_text("-- partial", encoding="utf-8")
            return MagicMock(returncode=1, stdout="", stderr="selection failed")

        monkeypatch.setattr("vaaet_ml.data.database.subprocess.run", fake_run)

        with pytest.raises(ValueError, match="backup extraction failed"):
            restore_backup_to_sql(
                backup, output_path=output, pg_restore_path=pg_restore
            )
        assert not output.exists()

    def test_rejects_requested_table_missing_from_catalog(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "other.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore-17"
        pg_restore.write_text("binary", encoding="utf-8")
        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)

        def fake_run(command, **_kwargs):
            if "--version" in command:
                return MagicMock(
                    returncode=0, stdout="pg_restore (PostgreSQL) 17.10", stderr=""
                )
            return MagicMock(
                returncode=0,
                stdout="7; 0 8 TABLE DATA public unrelated postgres\n",
                stderr="",
            )

        monkeypatch.setattr("vaaet_ml.data.database.subprocess.run", fake_run)

        with pytest.raises(ValueError, match="did not match requested TABLE DATA"):
            restore_backup_to_sql(
                backup,
                pg_restore_path=pg_restore,
                tables=("public.traffic_data",),
            )

    def test_rejects_successful_output_without_requested_copy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from unittest.mock import MagicMock

        from vaaet_ml.data.database import restore_backup_to_sql

        backup = tmp_path / "legacy.backup"
        backup.write_bytes(b"PGDMP")
        pg_restore = tmp_path / "pg_restore-17"
        pg_restore.write_text("binary", encoding="utf-8")
        output = tmp_path / "invalid.sql"
        monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)

        def fake_run(command, **_kwargs):
            if "--version" in command:
                return MagicMock(
                    returncode=0, stdout="pg_restore (PostgreSQL) 17.10", stderr=""
                )
            if "-l" in command:
                return MagicMock(
                    returncode=0,
                    stdout="321; 0 987 TABLE DATA public traffic_data postgres\n",
                    stderr="",
                )
            output.write_text("-- no COPY data", encoding="utf-8")
            return MagicMock(returncode=0, stdout="", stderr="")

        monkeypatch.setattr("vaaet_ml.data.database.subprocess.run", fake_run)

        with pytest.raises(ValueError, match="no COPY block"):
            restore_backup_to_sql(
                backup,
                output_path=output,
                pg_restore_path=pg_restore,
                tables=("public.traffic_data",),
            )
        assert not output.exists()


def test_backup_catalog_recognizes_modern_and_legacy_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from vaaet_ml.data.database import inspect_backup_catalog

    backup = tmp_path / "full.backup"
    backup.write_bytes(b"PGDMP")
    binary = tmp_path / "pg_restore"
    binary.write_text("binary", encoding="utf-8")
    monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)
    catalog = """
    1; 0 1 TABLE DATA vaaet_raw traffic_data owner
    2; 0 2 TABLE DATA vaaet_ml telemetry_features owner
    3; 0 3 TABLE DATA vaaet_ml traffic_predictions owner
    4; 0 4 TABLE DATA vaaet_feedback human_validations owner
    5; 0 5 TABLE DATA public unrelated owner
    6; 0 6 TABLE DATA vaaet_ops pipeline_runs owner
    7; 0 7 TABLE DATA vaaet_ops persistence_receipts owner
    """
    monkeypatch.setattr(
        "vaaet_ml.data.database.subprocess.run",
        lambda *_args, **_kwargs: MagicMock(returncode=0, stdout=catalog, stderr=""),
    )
    assert inspect_backup_catalog(backup, pg_restore_path=binary) == (
        "vaaet_feedback.human_validations",
        "vaaet_ml.telemetry_features",
        "vaaet_ml.traffic_predictions",
        "vaaet_ops.persistence_receipts",
        "vaaet_ops.pipeline_runs",
        "vaaet_raw.traffic_data",
    )


def test_backup_catalog_rejects_corrupt_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from vaaet_ml.data.database import inspect_backup_catalog

    backup = tmp_path / "corrupt.backup"
    backup.write_bytes(b"bad")
    binary = tmp_path / "pg_restore"
    binary.write_text("binary", encoding="utf-8")
    monkeypatch.setattr("vaaet_ml.data.database.os.access", lambda *_: True)
    monkeypatch.setattr(
        "vaaet_ml.data.database.subprocess.run",
        lambda *_args, **_kwargs: MagicMock(
            returncode=1, stdout="", stderr="input file does not appear to be a valid archive"
        ),
    )
    with pytest.raises(ValueError, match="Cannot inspect PostgreSQL backup"):
        inspect_backup_catalog(backup, pg_restore_path=binary)


def test_load_from_backup_propagates_explicit_pg_restore_path(tmp_path: Path) -> None:
    from unittest.mock import patch

    from vaaet_ml.data.database import load_from_backup

    backup = tmp_path / "traffic_data.backup"
    backup.write_bytes(b"PGDMP")
    sql_path = tmp_path / "traffic_data.sql"
    sql_path.write_text("-- restored", encoding="utf-8")
    pg_restore = tmp_path / "pg_restore-17"

    expected = pd.DataFrame({"id": [1]})
    with (
        patch("vaaet_ml.data.database.restore_backup_to_sql", return_value=sql_path) as restore,
        patch("vaaet_ml.data.database.parse_sql_dump", return_value=expected),
    ):
        result = load_from_backup(backup, pg_restore_path=pg_restore)

    restore.assert_called_once_with(backup, pg_restore_path=pg_restore)
    pd.testing.assert_frame_equal(result, expected)


class TestParseSqlDump:
    """Test parse_sql_dump() with synthetic SQL text."""

    @pytest.fixture()
    def sample_sql(self, tmp_path: Path) -> Path:
        """Create a minimal SQL dump with a COPY block."""
        content = textwrap.dedent("""\
            --
            -- PostgreSQL database dump
            --
            SET statement_timeout = 0;

            COPY public.traffic_data (id, clip_id, record_time, avg_speed, count_car, count_truck, count_bus, count_motorcycle, count_bicycle, total_vehicles) FROM stdin;
            1\tclip_001\t2024-01-15 08:00:00\t55.3\t10\t3\t1\t2\t0\t16
            2\tclip_001\t2024-01-15 08:01:00\t48.7\t8\t2\t0\t1\t1\t12
            3\tclip_002\t2024-01-15 08:02:00\t12.1\t15\t5\t2\t3\t0\t25
            \\.

            -- end
        """)
        sql_file = tmp_path / "dump.sql"
        sql_file.write_text(content, encoding="utf-8")
        return sql_file

    def test_parses_correct_row_count(self, sample_sql: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        df = parse_sql_dump(sample_sql)
        assert len(df) == 3

    def test_parses_correct_columns(self, sample_sql: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        df = parse_sql_dump(sample_sql)
        expected = {
            "id",
            "clip_id",
            "record_time",
            "avg_speed",
            "count_car",
            "count_truck",
            "count_bus",
            "count_motorcycle",
            "count_bicycle",
            "total_vehicles",
        }
        assert set(df.columns) == expected

    def test_numeric_types(self, sample_sql: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        df = parse_sql_dump(sample_sql)
        assert pd.api.types.is_numeric_dtype(df["avg_speed"])
        assert pd.api.types.is_numeric_dtype(df["count_car"])
        assert pd.api.types.is_numeric_dtype(df["total_vehicles"])

    def test_datetime_parsing(self, sample_sql: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        df = parse_sql_dump(sample_sql)
        assert pd.api.types.is_datetime64_any_dtype(df["record_time"])
        assert df.iloc[0]["record_time"] == pd.Timestamp("2024-01-15 11:00:00Z")

    def test_speed_values(self, sample_sql: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        df = parse_sql_dump(sample_sql)
        assert df["avg_speed"].iloc[0] == pytest.approx(55.3)
        assert df["avg_speed"].iloc[2] == pytest.approx(12.1)

    def test_missing_file(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        with pytest.raises(FileNotFoundError, match="SQL dump file was not found"):
            parse_sql_dump(tmp_path / "nonexistent.sql")

    def test_no_copy_block(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        sql_file = tmp_path / "empty.sql"
        sql_file.write_text("-- empty dump\nSELECT 1;\n", encoding="utf-8")
        with pytest.raises(ValueError, match="No COPY block"):
            parse_sql_dump(sql_file)

    def test_null_handling(self, tmp_path: Path) -> None:
        """Postgres NULL (\\N) should be parsed as NaN/NA."""
        from vaaet_ml.data.database import parse_sql_dump

        content = textwrap.dedent("""\
            COPY public.traffic_data (id, clip_id, record_time, avg_speed, count_car, count_truck, count_bus, count_motorcycle, count_bicycle, total_vehicles) FROM stdin;
            1\tclip_001\t2024-01-15 08:00:00\t\\N\t10\t3\t1\t2\t0\t16
            \\.
        """)
        sql_file = tmp_path / "nulls.sql"
        sql_file.write_text(content, encoding="utf-8")
        df = parse_sql_dump(sql_file)
        assert pd.isna(df["avg_speed"].iloc[0])

    def test_preserves_telemetry_v2_columns(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump

        sql_file = tmp_path / "v2.sql"
        sql_file.write_text(
            "COPY vaaet_raw.traffic_data (id, clip_id, record_time, avg_speed, "
            "near_zero_motion_count, speed_measurement_quality, "
            "optical_flow_tracking_ratio, telemetry_schema_version) FROM stdin;\n"
            "1\tclip\t2026-08-04 12:00:00+00\t10.5\t3\t0.8\t0.9\ttraffic-telemetry-v2\n"
            "\\.\n",
            encoding="utf-8",
        )
        frame = parse_sql_dump(sql_file)
        assert frame.iloc[0]["near_zero_motion_count"] == 3
        assert frame.iloc[0]["speed_measurement_quality"] == pytest.approx(0.8)
        assert frame.iloc[0]["telemetry_schema_version"] == "traffic-telemetry-v2"

    def test_preserves_empty_copy_schema(self, tmp_path: Path) -> None:
        from vaaet_ml.data.database import parse_sql_dump_tables

        sql_file = tmp_path / "empty-table.sql"
        sql_file.write_text(
            "COPY public.traffic_data (clip_id, record_time, total_vehicles) FROM stdin;\n"
            "\\.\n",
            encoding="utf-8",
        )
        frames = parse_sql_dump_tables(sql_file)
        assert "public.traffic_data" in frames
        assert frames["public.traffic_data"].empty
        assert list(frames["public.traffic_data"].columns) == [
            "clip_id",
            "record_time",
            "total_vehicles",
        ]
