from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

AuthMode = Literal["bearer", "raw"]
ThemeMode = Literal["light", "dark", "system", "eye"]


@dataclass
class AppSettings:
    base_url: str
    api_key: str
    model: str
    auth_mode: AuthMode
    theme: ThemeMode = "light"
    billing_url: str = "http://127.0.0.1:8765"


@dataclass
class SlideRecord:
    index: int
    title: str
    body: str
    notes: str
    thumb_path: str
    image_path: str
    script: str | None = None


@dataclass
class DeckRecord:
    source_path: str
    mtime: float
    slides: list[SlideRecord] = field(default_factory=list)

    def slide_by_index(self, index: int) -> SlideRecord:
        for slide in self.slides:
            if slide.index == index:
                return slide
        raise KeyError(index)
