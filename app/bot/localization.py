from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class Translator:
    def __init__(self, locale_dir: Path, default_language: str = "ar") -> None:
        self.default_language = default_language
        self.messages: dict[str, dict[str, Any]] = {}
        for language in ("ar", "en"):
            with (locale_dir / f"{language}.json").open(encoding="utf-8") as file:
                self.messages[language] = json.load(file)

    def get(self, key: str, language: str | None = None, **values: object) -> str:
        lang = language if language in self.messages else self.default_language
        catalog = self.messages[lang]
        # Locale files may use either flat dotted keys ("admin.stats") or
        # nested objects. Prefer the explicit flat key when present.
        if key in catalog:
            value: Any = catalog[key]
        else:
            value = catalog
        for part in key.split("."):
            if value is catalog:
                value = value.get(part, key) if isinstance(value, dict) else key
                if value == key:
                    break
        return str(value).format(**values)