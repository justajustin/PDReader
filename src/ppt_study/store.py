from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from pathlib import Path

from ppt_study.models import DeckRecord, SlideRecord
from ppt_study.paths import app_data_dir, cache_dir

_deck_io_lock = threading.Lock()


def deck_cache_key(source_path: str, mtime: float) -> str:
    raw = f"{Path(source_path).resolve()}::{mtime}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _deck_dir(source_path: str, mtime: float) -> Path:
    return cache_dir() / deck_cache_key(source_path, mtime)


def _to_dict(deck: DeckRecord) -> dict:
    return {
        "source_path": deck.source_path,
        "mtime": deck.mtime,
        "slides": [
            {
                "index": s.index,
                "title": s.title,
                "body": s.body,
                "notes": s.notes,
                "thumb_path": s.thumb_path,
                "image_path": s.image_path,
                "script": s.script,
            }
            for s in deck.slides
        ],
    }


def _from_dict(data: dict) -> DeckRecord:
    slides = [SlideRecord(**item) for item in data["slides"]]
    return DeckRecord(data["source_path"], data["mtime"], slides)


def _write_deck(deck: DeckRecord) -> Path:
    folder = _deck_dir(deck.source_path, deck.mtime)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "deck.json"
    path.write_text(json.dumps(_to_dict(deck), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_deck(deck: DeckRecord) -> Path:
    with _deck_io_lock:
        return _write_deck(deck)


def load_deck(source_path: str) -> DeckRecord | None:
    src = Path(source_path)
    if not src.exists():
        return None
    mtime = src.stat().st_mtime
    path = _deck_dir(str(src), mtime) / "deck.json"
    if not path.exists():
        return None
    return _from_dict(json.loads(path.read_text(encoding="utf-8")))


def save_script(source_path: str, mtime: float, index: int, script: str) -> None:
    path = _deck_dir(source_path, mtime) / "deck.json"
    with _deck_io_lock:
        if not path.exists():
            raise FileNotFoundError(path)
        deck = _from_dict(json.loads(path.read_text(encoding="utf-8")))
        slide = deck.slide_by_index(index)
        slide.script = script
        _write_deck(deck)


def _fav_key(source_path: str) -> str:
    return str(Path(source_path).resolve())


def _favorites_file() -> Path:
    return app_data_dir() / "favorites.json"


def _read_favorites_map() -> dict:
    path = _favorites_file()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_favorites(source_path: str) -> list[int]:
    raw = _read_favorites_map().get(_fav_key(source_path), [])
    out: list[int] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(out))


def toggle_favorite(source_path: str, index: int) -> bool:
    key = _fav_key(source_path)
    data = _read_favorites_map()
    items = set(load_favorites(source_path))
    idx = int(index)
    if idx in items:
        items.remove(idx)
        starred = False
    else:
        items.add(idx)
        starred = True
    data[key] = sorted(items)
    _favorites_file().write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return starred


def _qa_fav_file() -> Path:
    return app_data_dir() / "qa_favorites.json"


def _read_qa_favorites() -> list[dict]:
    path = _qa_fav_file()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict) and item.get("id")]


def _write_qa_favorites(items: list[dict]) -> None:
    _qa_fav_file().write_text(
        json.dumps(items, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _qa_key(question: str, answer: str) -> str:
    raw = f"{question}\n{answer}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def add_qa_favorite(record: dict) -> dict:
    data = record if isinstance(record, dict) else {}
    question = str(data.get("question") or "").strip()
    answer = str(data.get("answer") or "").strip()
    if not question and not answer:
        raise ValueError("empty qa favorite")
    key = _qa_key(question, answer)
    items = _read_qa_favorites()
    for item in items:
        if item.get("key") == key:
            return item
    try:
        slide_index = int(data.get("slide_index") or 0)
    except (TypeError, ValueError):
        slide_index = 0
    item = {
        "id": uuid.uuid4().hex,
        "key": key,
        "question": question,
        "answer": answer,
        "file_name": str(data.get("file_name") or "").strip(),
        "source_path": str(data.get("source_path") or "").strip(),
        "slide_index": slide_index,
        "created_at": time.time(),
    }
    items.append(item)
    _write_qa_favorites(items)
    return item


def remove_qa_favorite(fav_id: str) -> bool:
    target = str(fav_id or "")
    items = _read_qa_favorites()
    kept = [item for item in items if str(item.get("id")) != target]
    if len(kept) == len(items):
        return False
    _write_qa_favorites(kept)
    return True


def search_qa_favorites(query: str) -> list[dict]:
    needle = str(query or "").strip().casefold()
    tokens = [tok for tok in needle.split() if tok]
    items = list(reversed(_read_qa_favorites()))
    if not tokens:
        return items
    hits: list[dict] = []
    for item in items:
        blob = f"{item.get('question') or ''}\n{item.get('answer') or ''}".casefold()
        if all(tok in blob for tok in tokens):
            hits.append(item)
    return hits
