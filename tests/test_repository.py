import pytest

from app.database.database import Database
from app.database.repository import UserRepository


@pytest.mark.asyncio
async def test_user_and_download_repository(tmp_path) -> None:
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    try:
        repository = UserRepository(database)
        user = await repository.upsert_user(123, "tester", "Test", "ar")
        assert user.telegram_id == 123
        download_id = await repository.create_download(123, "tiktok", "https://tiktok.com/video/1")
        await repository.finish_download(download_id, "completed", 1024, 12.5)

        stats = await repository.stats_for_user(123)
        assert stats["total"] == 1
        assert stats["tiktok"] == 1

        history = await repository.recent_downloads(123)
        assert history[0]["platform"] == "tiktok"
        assert history[0]["status"] == "completed"
        assert "url" not in history[0]

        global_stats = await repository.global_stats()
        assert global_stats["total_users"] == 1
        assert global_stats["total_downloads"] == 1
    finally:
        await database.close()