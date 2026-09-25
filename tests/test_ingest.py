from pathlib import Path

from ppt_study.ingest import ingest_presentation
from ppt_study.models import DeckRecord, SlideRecord
from ppt_study.store import save_deck


def test_reuses_cache(appdata_tmp, tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")
    mtime = ppt.stat().st_mtime
    save_deck(
        DeckRecord(
            str(ppt),
            mtime,
            [SlideRecord(1, "Cached", "", "", "t.png", "s.png", None)],
        )
    )
    monkeypatch.setattr(
        "ppt_study.ingest.export_slides",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("export")),
    )
    loaded = ingest_presentation(ppt)
    assert loaded.slides[0].title == "Cached"


def test_builds_deck_from_export_and_text(appdata_tmp, tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")

    def fake_export(path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / "slide_001.png"
        dest.write_bytes(b"p")
        return [dest]

    monkeypatch.setattr("ppt_study.ingest.export_slides", fake_export)
    monkeypatch.setattr(
        "ppt_study.ingest.extract_pptx_text",
        lambda path: [{"index": 1, "title": "Hello", "body": "World", "notes": ""}],
    )

    def fake_thumb(source, dest, width=160):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"t")
        return dest

    monkeypatch.setattr("ppt_study.ingest.make_thumbnail", fake_thumb)
    seen: list[tuple[int, int]] = []
    deck = ingest_presentation(ppt, on_progress=lambda d, t: seen.append((d, t)))
    assert deck.slides[0].title == "Hello"
    assert Path(deck.slides[0].image_path).exists()
    assert seen[-1] == (1, 1)


def test_missing_slide_image_is_placeholder(appdata_tmp, tmp_path, monkeypatch):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")

    def fake_export(path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        missing = out_dir / "slide_001.png"
        dest = out_dir / "slide_002.png"
        dest.write_bytes(b"p")
        return [missing, dest]

    monkeypatch.setattr("ppt_study.ingest.export_slides", fake_export)
    monkeypatch.setattr(
        "ppt_study.ingest.extract_pptx_text",
        lambda path: [
            {"index": 1, "title": "A", "body": "", "notes": ""},
            {"index": 2, "title": "B", "body": "", "notes": ""},
        ],
    )

    def fake_thumb(source, dest, width=160):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"t")
        return dest

    monkeypatch.setattr("ppt_study.ingest.make_thumbnail", fake_thumb)
    deck = ingest_presentation(ppt)
    assert deck.slides[0].image_path == ""
    assert deck.slides[0].title == "A"
    assert Path(deck.slides[1].image_path).exists()
    assert deck.slides[1].title == "B"


def test_ingest_pdf_does_not_call_powerpoint(appdata_tmp, tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    def fake_export(path, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / "slide_001.png"
        dest.write_bytes(b"p")
        return [dest]

    monkeypatch.setattr(
        "ppt_study.ingest.export_slides",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("ppt")),
    )
    monkeypatch.setattr("ppt_study.ingest.export_pdf_pages", fake_export)
    monkeypatch.setattr(
        "ppt_study.ingest.extract_pdf_text",
        lambda path: [{"index": 1, "title": "PDF Title", "body": "Body", "notes": ""}],
    )

    def fake_thumb(source, dest, width=160):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"t")
        return dest

    monkeypatch.setattr("ppt_study.ingest.make_thumbnail", fake_thumb)
    deck = ingest_presentation(pdf)
    assert deck.slides[0].title == "PDF Title"
    assert Path(deck.slides[0].image_path).exists()


def test_ingest_pdf_renders_real_pages(appdata_tmp, tmp_path):
    from pdf_util import write_hello_pdf

    pdf = write_hello_pdf(tmp_path / "hello.pdf", "Hello PDF")
    deck = ingest_presentation(pdf)
    assert len(deck.slides) == 1
    assert Path(deck.slides[0].image_path).is_file()
    assert "Hello" in (deck.slides[0].title or deck.slides[0].body)


def test_ingest_rejects_unknown_suffix(appdata_tmp, tmp_path):
    from ppt_study.ingest import IngestError

    other = tmp_path / "notes.txt"
    other.write_text("x", encoding="utf-8")
    try:
        ingest_presentation(other)
    except IngestError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("expected IngestError")
