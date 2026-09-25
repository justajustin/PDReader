from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_API_EDGE = 1280
MAX_API_BYTES = 1_500_000


def make_thumbnail(source: Path, dest: Path, width: int = 160) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as im:
        im = im.convert("RGB")
        ratio = width / im.width
        size = (width, max(1, int(im.height * ratio)))
        im.resize(size, Image.Resampling.LANCZOS).save(dest, "PNG")
    return dest


def _pil_to_api_data_url(im: Image.Image) -> str:
    im = im.convert("RGB")
    longest = max(im.size)
    if longest > MAX_API_EDGE:
        scale = MAX_API_EDGE / longest
        im = im.resize(
            (max(1, int(im.width * scale)), max(1, int(im.height * scale))),
            Image.Resampling.LANCZOS,
        )
    quality = 85
    data = b""
    while quality >= 40:
        buf = BytesIO()
        im.save(buf, format="JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_API_BYTES:
            break
        quality -= 10
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def image_to_api_data_url(source: Path) -> str:
    with Image.open(source) as im:
        return _pil_to_api_data_url(im)


def data_url_to_api_data_url(data_url: str) -> str:
    text = (data_url or "").strip()
    if not text.startswith("data:") or "," not in text:
        raise ValueError("invalid data url")
    raw = base64.b64decode(text.split(",", 1)[1])
    with Image.open(BytesIO(raw)) as im:
        return _pil_to_api_data_url(im)


def file_to_display_data_url(source: Path) -> str:
    data = Path(source).read_bytes()
    suffix = Path(source).suffix.lower()
    mime = "image/png" if suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
