from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ppt_study.export_com import ExportError, export_slides
from ppt_study.export_pdf import export_pdf_pages
from ppt_study.extract_text import extract_pdf_text, extract_pptx_text
from ppt_study.image_util import make_thumbnail
from ppt_study.models import DeckRecord, SlideRecord
from ppt_study.paths import cache_dir
from ppt_study.store import deck_cache_key, load_deck, save_deck

ProgressCb = Callable[[int, int], None]


class IngestError(Exception):
    pass


def ingest_presentation(
    source: Path, on_progress: ProgressCb | None = None
) -> DeckRecord:
    source = source.resolve()
    cached = load_deck(str(source))
    if cached is not None:
        if on_progress:
            total = max(1, len(cached.slides))
            on_progress(total, total)
        return cached
    suffix = source.suffix.lower()
    if suffix not in {".ppt", ".pptx", ".pdf"}:
        raise IngestError("请打开 PPT、PPTX 或 PDF 课件")
    mtime = source.stat().st_mtime
    folder = cache_dir() / deck_cache_key(str(source), mtime)
    slides_dir = folder / "slides"
    thumbs_dir = folder / "thumbs"
    try:
        if suffix == ".pdf":
            images = export_pdf_pages(source, slides_dir)
            texts = {item["index"]: item for item in extract_pdf_text(source)}
        else:
            images = export_slides(source, slides_dir)
            texts = {item["index"]: item for item in extract_pptx_text(source)}
    except ExportError as exc:
        raise IngestError(str(exc)) from exc
    if images and not any(Path(p).is_file() for p in images):
        raise IngestError("全部页面导出失败")
    total = max(len(images), max(texts, default=0))
    slides: list[SlideRecord] = []
    for i in range(1, total + 1):
        image_path = ""
        thumb_path = ""
        if i <= len(images):
            candidate = Path(images[i - 1])
            if candidate.is_file():
                image_path = str(candidate)
                thumb_dest = thumbs_dir / f"slide_{i:03d}.png"
                try:
                    make_thumbnail(candidate, thumb_dest)
                    thumb_path = str(thumb_dest)
                except Exception:
                    thumb_path = image_path
        info = texts.get(i, {"title": "", "body": "", "notes": ""})
        slides.append(
            SlideRecord(
                index=i,
                title=info.get("title", ""),
                body=info.get("body", ""),
                notes=info.get("notes", ""),
                thumb_path=thumb_path,
                image_path=image_path,
            )
        )
        if on_progress:
            on_progress(i, total)
    deck = DeckRecord(str(source), mtime, slides)
    save_deck(deck)
    return deck
