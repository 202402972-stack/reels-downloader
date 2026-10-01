import base64

import pytest

from app.config import Settings
from app.services.cookies import materialize_instagram_cookies


def test_materializes_netscape_instagram_cookies_securely(tmp_path) -> None:
    text = (
        "# Netscape HTTP Cookie File\n"
        ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\ttest-value\n"
    )
    path = materialize_instagram_cookies(
        base64.b64encode(text.encode()).decode(), tmp_path
    )
    assert path is not None
    assert path.read_text() == text
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("value", ["not-base64", base64.b64encode(b"wrong").decode()])
def test_rejects_invalid_cookie_secrets(value: str, tmp_path) -> None:
    with pytest.raises(ValueError):
        materialize_instagram_cookies(value, tmp_path)


def test_empty_cookie_configuration_is_optional(tmp_path) -> None:
    assert materialize_instagram_cookies("", tmp_path) is None


def test_cookie_secret_is_hidden_from_settings_repr(monkeypatch) -> None:
    secret = "sensitive-cookie-value"
    monkeypatch.setenv("INSTAGRAM_COOKIES_BASE64", secret)
    settings = Settings.from_env()
    assert secret not in repr(settings)
