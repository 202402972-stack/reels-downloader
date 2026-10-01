from pathlib import Path

from app.bot.localization import Translator


def test_flat_dotted_locale_keys_are_resolved() -> None:
    translator = Translator(Path(__file__).parents[1] / "app" / "locales")
    assert "صحة النظام" in translator.get(
        "admin.health", "ar", queued=1, active=0, workers="3/3", auth="مفعّلة",
        yt="2/2", gallery="1/1", users=2, failed=0,
    )
