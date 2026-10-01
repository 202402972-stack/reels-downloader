from __future__ import annotations

import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .bot.context import AppContext
from .bot.handlers import admin, callbacks, download, help, start
from .bot.localization import Translator
from .config import Settings
from .database.database import Database
from .database.repository import UserRepository
from .logging_config import configure_logging
from .services.cleanup import cleanup_loop
from .services.cookies import materialize_instagram_cookies
from .services.downloader import DownloadManager
from .services.instagram import InstagramService
from .services.health import start_health_server
from .services.rate_limiter import RateLimiter
from .services.tiktok import TikTokService

logger = logging.getLogger(__name__)


async def run() -> None:
    settings = Settings.from_env()
    settings.validate()
    configure_logging(settings.log_level)
    settings.root_dir.joinpath("downloads").mkdir(exist_ok=True)
    settings.root_dir.joinpath("temp").mkdir(exist_ok=True)

    database = Database(str(settings.database_path))
    await database.connect()
    users = UserRepository(database)
    try:
        instagram_cookies = materialize_instagram_cookies(
            settings.instagram_cookies_base64, settings.root_dir / ".runtime"
        )
    except ValueError as exc:
        logger.warning("Instagram authentication is disabled: %s", exc)
        instagram_cookies = None
    downloader = DownloadManager(
        max_concurrent=settings.max_concurrent_downloads,
        timeout_seconds=settings.download_timeout,
        max_file_size_bytes=settings.max_file_size_bytes,
        temp_root=settings.root_dir / "temp",
        instagram_cookies_file=instagram_cookies,
        max_media_per_post=settings.max_media_per_post,
        engine_attempts=settings.engine_attempts,
        retry_base_delay=settings.retry_base_delay,
    )
    translator = Translator(settings.root_dir / "app" / "locales", settings.default_language)
    context = AppContext(
        settings=settings,
        users=users,
        downloader=downloader,
        tiktok=TikTokService(downloader),
        instagram=InstagramService(downloader),
        rate_limiter=RateLimiter(settings.rate_limit_seconds, settings.max_requests_per_minute),
        translator=translator,
    )
    health_runner = None
    if settings.port:
        health_runner = await start_health_server(context, settings.port)
        logger.info("Health server listening on port %s", settings.port)
    if not settings.admin_ids:
        logger.warning("ADMIN_IDS is not configured; admin panel is disabled")

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_short_description(
        short_description="Reelkeep — Telegram media downloader | reels-landing-zeta.vercel.app"
    )
    await bot.set_my_description(
        description=(
            "حمّل محتوى TikTok وInstagram العام مباشرة إلى Telegram. "
            "الموقع: https://reels-landing-zeta.vercel.app/"
        )
    )
    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["context"] = context
    dispatcher.include_router(start.router)
    dispatcher.include_router(admin.router)
    dispatcher.include_router(callbacks.router)
    dispatcher.include_router(help.router)
    dispatcher.include_router(download.router)
    cleanup_task = asyncio.create_task(
        cleanup_loop(
            [settings.root_dir / "temp", settings.root_dir / "downloads"],
            settings.temp_retention_minutes,
        )
    )
    try:
        # Avoid processing stale updates when a deployment restarts.
        await bot.delete_webhook(drop_pending_updates=settings.drop_pending_updates)
        await bot.set_my_commands(
            [
                BotCommand(command="start", description="Start the bot"),
                BotCommand(command="download", description="Download TikTok or Instagram media"),
                BotCommand(command="batch", description="Download multiple links in one batch"),
                BotCommand(command="stats", description="View your download statistics"),
                BotCommand(command="history", description="View recent downloads"),
                BotCommand(command="settings", description="Open your settings"),
                BotCommand(command="help", description="How to use the bot"),
                BotCommand(command="privacy", description="Read our privacy policy"),
                BotCommand(command="admin", description="Admin panel"),
            ]
        )
        logger.info("Telegram downloader bot started")
        await dispatcher.start_polling(bot, context=context)
    finally:
        cleanup_task.cancel()
        if health_runner is not None:
            await health_runner.cleanup()
        await downloader.close()
        if instagram_cookies is not None:
            instagram_cookies.unlink(missing_ok=True)
        await database.close()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
