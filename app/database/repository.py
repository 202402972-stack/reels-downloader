from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .database import Database
from .models import PlatformStats, User


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRepository:
    """SQLite implementation kept behind a small interface for future PostgreSQL migration."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_user(
        self,
        telegram_id: int,
        username: str | None,
        first_name: str,
        language: str,
        is_blocked: bool = False,
    ) -> User:
        db = self.database.require_connection()
        now = _now()
        await db.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, language, last_activity, is_blocked)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                last_activity = excluded.last_activity
            """,
            (telegram_id, username, first_name, language, now, int(is_blocked)),
        )
        await db.execute(
            """
            INSERT INTO settings (user_id, language, auto_delete)
            VALUES (?, ?, 1)
            ON CONFLICT(user_id) DO NOTHING
            """,
            (telegram_id, language),
        )
        await db.commit()
        return await self.get_user(telegram_id)  # type: ignore[return-value]

    async def get_user(self, telegram_id: int) -> User | None:
        db = self.database.require_connection()
        async with db.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return User(
            telegram_id=row["telegram_id"],
            username=row["username"],
            first_name=row["first_name"],
            language=row["language"],
            downloads_count=row["downloads_count"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_activity=datetime.fromisoformat(row["last_activity"]),
            is_blocked=bool(row["is_blocked"]),
        )

    async def set_language(self, telegram_id: int, language: str) -> None:
        db = self.database.require_connection()
        await db.execute(
            "UPDATE users SET language = ?, last_activity = ? WHERE telegram_id = ?",
            (language, _now(), telegram_id),
        )
        await db.execute(
            "INSERT INTO settings (user_id, language) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET language = excluded.language",
            (telegram_id, language),
        )
        await db.commit()

    async def set_auto_delete(self, telegram_id: int, enabled: bool) -> None:
        db = self.database.require_connection()
        await db.execute(
            "INSERT INTO settings (user_id, auto_delete) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET auto_delete = excluded.auto_delete",
            (telegram_id, int(enabled)),
        )
        await db.commit()

    async def get_auto_delete(self, telegram_id: int) -> bool:
        db = self.database.require_connection()
        async with db.execute(
            "SELECT auto_delete FROM settings WHERE user_id = ?", (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
        return True if row is None else bool(row["auto_delete"])

    async def create_download(self, user_id: int, platform: str, url: str) -> int:
        db = self.database.require_connection()
        cursor = await db.execute(
            "INSERT INTO downloads (telegram_user_id, platform, url, status) VALUES (?, ?, ?, 'queued')",
            (user_id, platform, url),
        )
        await db.commit()
        return int(cursor.lastrowid)

    async def finish_download(
        self,
        download_id: int,
        status: str,
        file_size: int | None = None,
        duration: float | None = None,
    ) -> None:
        db = self.database.require_connection()
        await db.execute(
            "UPDATE downloads SET status = ?, file_size = ?, duration = ? WHERE id = ?",
            (status, file_size, duration, download_id),
        )
        # Activity should reflect an attempted request as well as a successful
        # upload. The counter remains success-only for accurate user stats.
        if status == "completed":
            await db.execute(
                """
                UPDATE users SET downloads_count = downloads_count + 1, last_activity = ?
                WHERE telegram_id = (SELECT telegram_user_id FROM downloads WHERE id = ?)
                """,
                (_now(), download_id),
            )
        else:
            await db.execute(
                """
                UPDATE users SET last_activity = ?
                WHERE telegram_id = (SELECT telegram_user_id FROM downloads WHERE id = ?)
                """,
                (_now(), download_id),
            )
        await db.commit()

    async def stats_for_user(self, telegram_id: int) -> dict[str, Any]:
        db = self.database.require_connection()
        async with db.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN platform = 'tiktok' AND status = 'completed' THEN 1 ELSE 0 END) AS tiktok,
                SUM(CASE WHEN platform = 'instagram' AND status = 'completed' THEN 1 ELSE 0 END) AS instagram,
                MIN(created_at) AS first_download
            FROM downloads WHERE telegram_user_id = ?
            """,
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
        user = await self.get_user(telegram_id)
        return {
            "total": int(row["total"] or 0),
            "tiktok": int(row["tiktok"] or 0),
            "instagram": int(row["instagram"] or 0),
            "joined": (user.created_at if user else None),
            "first_download": row["first_download"],
        }

    async def recent_downloads(self, telegram_id: int, limit: int = 5) -> list[dict[str, Any]]:
        """Return a small, presentation-ready history without exposing raw URLs."""
        safe_limit = max(1, min(limit, 20))
        rows = await self.database.require_connection().execute_fetchall(
            """
            SELECT platform, status, file_size, created_at
            FROM downloads
            WHERE telegram_user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (telegram_id, safe_limit),
        )
        return [dict(row) for row in rows]

    async def global_stats(self) -> dict[str, int]:
        db = self.database.require_connection()
        async with db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM users) AS total_users,
                (SELECT COUNT(*) FROM users WHERE julianday(last_activity) >= julianday('now', '-7 day')) AS active_users,
                (SELECT COUNT(*) FROM downloads WHERE status = 'completed') AS total_downloads,
                (SELECT COUNT(*) FROM downloads WHERE platform = 'tiktok' AND status = 'completed') AS tiktok_downloads,
                (SELECT COUNT(*) FROM downloads WHERE platform = 'instagram' AND status = 'completed') AS instagram_downloads,
                (SELECT COUNT(*) FROM downloads WHERE status = 'failed') AS failed_downloads,
                (SELECT COUNT(*) FROM downloads WHERE status = 'completed' AND date(created_at) >= date('now')) AS downloads_today,
                (SELECT COUNT(*) FROM downloads WHERE status = 'completed' AND julianday(created_at) >= julianday('now', '-7 day')) AS downloads_week
            """
        ) as cursor:
            row = await cursor.fetchone()
        return {key: int(row[key] or 0) for key in row.keys()}

    async def all_user_ids(self) -> list[int]:
        rows = await self.database.require_connection().execute_fetchall(
            "SELECT telegram_id FROM users WHERE is_blocked = 0"
        )
        return [int(row["telegram_id"]) for row in rows]

    async def mark_blocked(self, telegram_id: int, blocked: bool) -> None:
        db = self.database.require_connection()
        await db.execute(
            "UPDATE users SET is_blocked = ? WHERE telegram_id = ?",
            (int(blocked), telegram_id),
        )
        await db.commit()