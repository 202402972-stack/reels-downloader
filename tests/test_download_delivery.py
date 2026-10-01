from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramNetworkError
from aiogram.methods import SendMessage

from app.bot.handlers.download import _telegram_send


@pytest.mark.asyncio
async def test_telegram_delivery_retries_network_errors(monkeypatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("app.bot.handlers.download.asyncio.sleep", sleep)
    calls = 0

    async def operation():
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TelegramNetworkError(SendMessage(chat_id=1, text="test"), "offline")
        return "sent"

    assert await _telegram_send(operation, attempts=3) == "sent"
    assert calls == 3
    assert sleep.await_count == 2


@pytest.mark.asyncio
async def test_telegram_delivery_stops_after_retry_budget(monkeypatch) -> None:
    monkeypatch.setattr("app.bot.handlers.download.asyncio.sleep", AsyncMock())

    async def operation():
        raise TelegramNetworkError(SendMessage(chat_id=1, text="test"), "offline")

    with pytest.raises(TelegramNetworkError):
        await _telegram_send(operation, attempts=2)
