from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 9


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@contextmanager
def connect(path: Path | str) -> Iterator[sqlite3.Connection]:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path, timeout=30.0)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        yield connection
    finally:
        connection.close()


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if column not in _column_names(connection, table):
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_info (
            schema_version INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS works (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_work_no INTEGER NOT NULL UNIQUE,
            category TEXT NOT NULL,
            year_or_period TEXT,
            source_title TEXT,
            official_title TEXT NOT NULL,
            media_file_count INTEGER NOT NULL DEFAULT 0,
            subtitle_file_count INTEGER NOT NULL DEFAULT 0,
            subfolder_count INTEGER NOT NULL DEFAULT 0,
            media_format TEXT,
            source_folder TEXT,
            relative_path TEXT,
            director_or_direction TEXT,
            main_cast_or_voice_actors TEXT,
            verification_method TEXT,
            verification_note TEXT,
            verification_url TEXT,
            verification_status TEXT,
            credits_verification_note TEXT,
            credits_verification_url TEXT,
            credits_verification_status TEXT,
            is_visible INTEGER NOT NULL DEFAULT 1 CHECK(is_visible IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS series_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER NOT NULL,
            display_name TEXT NOT NULL,
            season_number INTEGER,
            group_type TEXT NOT NULL DEFAULT 'SERIES',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE,
            UNIQUE(work_id, display_name)
        );

        CREATE TABLE IF NOT EXISTS videos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            work_id INTEGER NOT NULL,
            series_group_id INTEGER,
            external_file_no INTEGER NOT NULL UNIQUE,
            official_title TEXT,
            episode_or_type TEXT,
            episode_number REAL,
            episode_sort_key TEXT NOT NULL,
            episode_title TEXT,
            content_type TEXT NOT NULL DEFAULT 'UNKNOWN',
            verification_url TEXT,
            verification_status TEXT,
            verification_note TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE,
            FOREIGN KEY(series_group_id) REFERENCES series_groups(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS video_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER NOT NULL UNIQUE,
            source_subfolder TEXT,
            filename TEXT NOT NULL,
            relative_path TEXT NOT NULL UNIQUE,
            extension TEXT NOT NULL,
            file_size INTEGER,
            modified_time_ns INTEGER,
            duration_ms INTEGER,
            container_format TEXT,
            video_codec TEXT,
            audio_codec TEXT,
            width INTEGER,
            height INTEGER,
            embedded_subtitle_count INTEGER NOT NULL DEFAULT 0,
            probe_status TEXT NOT NULL DEFAULT 'NOT_PROBED',
            probed_at TEXT,
            playback_support TEXT NOT NULL DEFAULT 'UNKNOWN',
            is_available INTEGER NOT NULL DEFAULT 0,
            scan_status TEXT NOT NULL DEFAULT 'NOT_SCANNED',
            last_scanned_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS subtitles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id INTEGER,
            relative_path TEXT NOT NULL UNIQUE,
            filename TEXT NOT NULL,
            extension TEXT NOT NULL,
            language TEXT,
            is_forced INTEGER NOT NULL DEFAULT 0 CHECK(is_forced IN (0, 1)),
            is_default INTEGER NOT NULL DEFAULT 0 CHECK(is_default IN (0, 1)),
            match_method TEXT NOT NULL DEFAULT 'UNMATCHED',
            file_size INTEGER,
            modified_time_ns INTEGER,
            is_available INTEGER NOT NULL DEFAULT 1 CHECK(is_available IN (0, 1)),
            last_scanned_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT NOT NULL,
            is_owner INTEGER NOT NULL DEFAULT 0 CHECK(is_owner IN (0, 1)),
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_seen_at TEXT
        );

        CREATE UNIQUE INDEX IF NOT EXISTS ux_users_single_owner
        ON users(is_owner) WHERE is_owner = 1;

        CREATE TABLE IF NOT EXISTS user_identities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            provider TEXT NOT NULL,
            subject TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE(provider, subject)
        );

        CREATE TABLE IF NOT EXISTS user_work_visibility (
            user_id INTEGER NOT NULL,
            work_id INTEGER NOT NULL,
            is_visible INTEGER NOT NULL CHECK(is_visible IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, work_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_user_work_visibility_work
            ON user_work_visibility(work_id, user_id, is_visible);

        CREATE TABLE IF NOT EXISTS user_work_state (
            user_id INTEGER NOT NULL,
            work_id INTEGER NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, work_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_video_state (
            user_id INTEGER NOT NULL,
            video_id INTEGER NOT NULL,
            favorite INTEGER NOT NULL DEFAULT 0 CHECK(favorite IN (0, 1)),
            watched INTEGER NOT NULL DEFAULT 0 CHECK(watched IN (0, 1)),
            watched_override INTEGER CHECK(watched_override IN (0, 1) OR watched_override IS NULL),
            play_count INTEGER NOT NULL DEFAULT 0 CHECK(play_count >= 0),
            position_ms INTEGER NOT NULL DEFAULT 0 CHECK(position_ms >= 0),
            duration_ms INTEGER,
            last_played_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, video_id),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(video_id) REFERENCES videos(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scan_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            status TEXT NOT NULL,
            files_found INTEGER NOT NULL DEFAULT 0,
            files_matched INTEGER NOT NULL DEFAULT 0,
            files_missing INTEGER NOT NULL DEFAULT 0,
            files_new INTEGER NOT NULL DEFAULT 0,
            subtitles_found INTEGER NOT NULL DEFAULT 0,
            subtitles_matched INTEGER NOT NULL DEFAULT 0,
            subtitles_unmatched INTEGER NOT NULL DEFAULT 0,
            probe_errors INTEGER NOT NULL DEFAULT 0,
            errors INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scan_errors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_run_id INTEGER NOT NULL,
            relative_path TEXT,
            error_type TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS scan_discoveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_run_id INTEGER NOT NULL,
            relative_path TEXT NOT NULL,
            extension TEXT NOT NULL,
            file_size INTEGER,
            modified_time_ns INTEGER,
            status TEXT NOT NULL DEFAULT 'NEW_FILE',
            created_at TEXT NOT NULL,
            FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS metadata_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schema_version TEXT,
            source_file TEXT,
            source_version TEXT,
            generated_at TEXT,
            work_count INTEGER,
            media_file_count INTEGER,
            imported_at TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT
        );

        CREATE TABLE IF NOT EXISTS tmdb_work_links (
            work_id INTEGER PRIMARY KEY,
            media_type TEXT CHECK(media_type IN ('movie', 'tv') OR media_type IS NULL),
            tmdb_id INTEGER,
            match_status TEXT NOT NULL DEFAULT 'UNMATCHED'
                CHECK(match_status IN ('UNMATCHED', 'CANDIDATE', 'MATCHED', 'REVIEW')),
            confidence REAL CHECK(confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)),
            matched_title TEXT,
            matched_year TEXT,
            poster_path TEXT,
            backdrop_path TEXT,
            overview TEXT,
            synced_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tmdb_people (
            tmdb_person_id INTEGER PRIMARY KEY,
            display_name TEXT NOT NULL,
            original_name TEXT,
            profile_path TEXT,
            known_for_department TEXT,
            synced_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tmdb_work_people (
            work_id INTEGER NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('CAST','DIRECTOR')),
            local_name TEXT NOT NULL,
            tmdb_person_id INTEGER NOT NULL,
            character_text TEXT,
            billing_order INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(work_id, role, local_name),
            FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE,
            FOREIGN KEY(tmdb_person_id) REFERENCES tmdb_people(tmdb_person_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tmdb_api_cache (
            cache_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            expires_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_tmdb_work_lookup
            ON tmdb_work_links(media_type, tmdb_id);
        CREATE INDEX IF NOT EXISTS idx_tmdb_work_status
            ON tmdb_work_links(match_status);
        CREATE INDEX IF NOT EXISTS idx_tmdb_work_people_person
            ON tmdb_work_people(tmdb_person_id);
        CREATE INDEX IF NOT EXISTS idx_tmdb_work_people_local_name
            ON tmdb_work_people(role, local_name);

        CREATE INDEX IF NOT EXISTS idx_works_category ON works(category);
        CREATE INDEX IF NOT EXISTS idx_works_title ON works(official_title);
        CREATE INDEX IF NOT EXISTS idx_series_work ON series_groups(work_id);
        CREATE INDEX IF NOT EXISTS idx_videos_work ON videos(work_id);
        CREATE INDEX IF NOT EXISTS idx_videos_series ON videos(series_group_id);
        CREATE INDEX IF NOT EXISTS idx_videos_episode
            ON videos(work_id, series_group_id, episode_sort_key);
        CREATE INDEX IF NOT EXISTS idx_video_files_available ON video_files(is_available);
        CREATE INDEX IF NOT EXISTS idx_subtitles_video ON subtitles(video_id);
        CREATE INDEX IF NOT EXISTS idx_subtitles_available ON subtitles(is_available);
        CREATE INDEX IF NOT EXISTS idx_user_work_favorite
            ON user_work_state(user_id, favorite);
        CREATE INDEX IF NOT EXISTS idx_user_video_recent
            ON user_video_state(user_id, last_played_at);
        CREATE INDEX IF NOT EXISTS idx_user_video_watched
            ON user_video_state(user_id, watched);
        CREATE INDEX IF NOT EXISTS idx_user_video_favorite
            ON user_video_state(user_id, favorite);
        CREATE INDEX IF NOT EXISTS idx_scan_discoveries_run
            ON scan_discoveries(scan_run_id);
        """
    )

    _add_column_if_missing(
        connection,
        "works",
        "is_visible",
        "INTEGER NOT NULL DEFAULT 1 CHECK(is_visible IN (0, 1))",
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_works_visible ON works(is_visible)"
    )
    _add_column_if_missing(
        connection,
        "user_video_state",
        "watched_override",
        "INTEGER CHECK(watched_override IN (0, 1) OR watched_override IS NULL)",
    )
    _add_column_if_missing(connection, "video_files", "embedded_subtitle_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "video_files", "probe_status", "TEXT NOT NULL DEFAULT 'NOT_PROBED'")
    _add_column_if_missing(connection, "video_files", "probed_at", "TEXT")
    _add_column_if_missing(connection, "scan_runs", "subtitles_found", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "scan_runs", "subtitles_matched", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "scan_runs", "subtitles_unmatched", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(connection, "scan_runs", "probe_errors", "INTEGER NOT NULL DEFAULT 0")

    table_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='tmdb_work_people'"
    ).fetchone()
    table_sql = str(table_row["sql"] or "") if table_row is not None else ""
    if table_sql and "DIRECTOR" not in table_sql:
        connection.execute("ALTER TABLE tmdb_work_people RENAME TO tmdb_work_people_v6")
        connection.execute(
            """
            CREATE TABLE tmdb_work_people (
                work_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('CAST','DIRECTOR')),
                local_name TEXT NOT NULL,
                tmdb_person_id INTEGER NOT NULL,
                character_text TEXT,
                billing_order INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(work_id, role, local_name),
                FOREIGN KEY(work_id) REFERENCES works(id) ON DELETE CASCADE,
                FOREIGN KEY(tmdb_person_id) REFERENCES tmdb_people(tmdb_person_id) ON DELETE CASCADE
            )
            """
        )
        connection.execute(
            """
            INSERT INTO tmdb_work_people(
                work_id,role,local_name,tmdb_person_id,character_text,billing_order,created_at,updated_at
            )
            SELECT work_id,role,local_name,tmdb_person_id,character_text,billing_order,created_at,updated_at
            FROM tmdb_work_people_v6
            """
        )
        connection.execute("DROP TABLE tmdb_work_people_v6")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tmdb_work_people_person ON tmdb_work_people(tmdb_person_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tmdb_work_people_local_name ON tmdb_work_people(role, local_name)"
        )

    row = connection.execute(
        "SELECT schema_version FROM schema_info ORDER BY rowid LIMIT 1"
    ).fetchone()
    stamp = now_iso()
    if row is None:
        connection.execute(
            "INSERT INTO schema_info(schema_version, created_at, updated_at) VALUES (?, ?, ?)",
            (SCHEMA_VERSION, stamp, stamp),
        )
    else:
        current = int(row["schema_version"])
        if current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Database schema {current} is newer than supported schema {SCHEMA_VERSION}"
            )
        connection.execute(
            "UPDATE schema_info SET schema_version = ?, updated_at = ?",
            (SCHEMA_VERSION, stamp),
        )
    connection.commit()


def quick_check(connection: sqlite3.Connection) -> str:
    row = connection.execute("PRAGMA quick_check").fetchone()
    return str(row[0]) if row else "unknown"


def foreign_key_error_count(connection: sqlite3.Connection) -> int:
    return len(connection.execute("PRAGMA foreign_key_check").fetchall())
