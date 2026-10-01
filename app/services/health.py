from __future__ import annotations

import time
from typing import Any

from aiohttp import web

from ..bot.context import AppContext
from .. import __version__


def _snapshot(context: AppContext) -> dict[str, Any]:
    diagnostics = context.downloader.diagnostics()
    return {
        "status": "ok",
        "service": "telegram-downloader",
        "version": __version__,
        "uptime_seconds": round(time.monotonic() - context.started_at, 1),
        "queue_size": diagnostics["queued"],
        "active_downloads": diagnostics["active"],
        "workers_alive": diagnostics["workers_alive"],
        "workers_expected": diagnostics["workers_expected"],
        "instagram_authenticated": diagnostics["instagram_authenticated"],
        "engine_metrics": diagnostics["engines"],
    }


async def health_handler(request: web.Request) -> web.Response:
    context: AppContext = request.app["context"]
    return web.json_response(_snapshot(context))


async def readiness_handler(request: web.Request) -> web.Response:
    context: AppContext = request.app["context"]
    ready = (
        context.settings.root_dir.exists()
        and context.users.database.connection is not None
    )
    payload = _snapshot(context)
    payload["ready"] = ready
    return web.json_response(payload, status=200 if ready else 503)


async def start_health_server(context: AppContext, port: int) -> web.AppRunner:
    app = web.Application()
    app["context"] = context
    app.add_routes(
        [
            web.get("/healthz", health_handler),
            web.get("/readyz", readiness_handler),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    return runner
