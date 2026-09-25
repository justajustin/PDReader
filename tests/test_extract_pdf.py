from pathlib import Path

from ppt_study.extract_media import extract_slide_links, extract_slide_media, publish_slide_media
from ppt_study.pdf_cos import PdfCos
from pdf_util import (
    write_hello_pdf,
    write_pdf_with_embedded_annot,
    write_pdf_with_file_attachment,
    write_pdf_with_uri_annot,
)


def test_pdf_cos_reads_hello_page(tmp_path: Path):
    path = write_hello_pdf(tmp_path / "hello.pdf", "Hello PDF")
    cos = PdfCos(path.read_bytes())
    pages = cos.pages()
    assert len(pages) == 1
    assert pages[0].get("/Type") == "/Page"


def test_extract_pdf_links_from_uri_annot(tmp_path: Path):
    path = write_pdf_with_uri_annot(tmp_path / "link.pdf")
    links = extract_slide_links(path, 1)
    assert links
    assert links[0]["url"] == "https://example.com/wiki"
    assert 0 <= links[0]["left"] < 1
    assert 0 < links[0]["width"] <= 1
    assert 0 < links[0]["height"] <= 1


def test_extract_pdf_links_from_text_url(tmp_path: Path):
    path = write_hello_pdf(tmp_path / "url.pdf", "https://example.org/path")
    links = extract_slide_links(path, 1)
    assert any(item["url"] == "https://example.org/path" for item in links)


def test_extract_pdf_links_empty_without_url(tmp_path: Path):
    path = write_hello_pdf(tmp_path / "plain.pdf", "Hello PDF")
    assert extract_slide_links(path, 1) == []


def test_extract_pdf_media_from_file_attachment(tmp_path: Path):
    path = write_pdf_with_file_attachment(tmp_path / "att.pdf")
    items = extract_slide_media(path, 1)
    assert len(items) == 1
    assert items[0]["kind"] == "video"
    assert items[0]["ext"] == ".webm"
    assert items[0]["blob"] == b"FAKEWEBM"
    assert 0 <= items[0]["left"] < 1
    assert 0 < items[0]["width"] < 1


def test_extract_pdf_media_from_movie_annot(tmp_path: Path):
    path = write_pdf_with_embedded_annot(
        tmp_path / "movie.pdf",
        "<< /Type /Annot /Subtype /Movie /Rect [100 400 400 600] /Movie << /F 5 0 R >> >>",
    )
    items = extract_slide_media(path, 1)
    assert items
    assert items[0]["blob"] == b"FAKEWEBM"
    assert items[0]["kind"] == "video"


def test_extract_pdf_media_from_screen_rendition(tmp_path: Path):
    path = write_pdf_with_embedded_annot(
        tmp_path / "screen.pdf",
        (
            "<< /Type /Annot /Subtype /Screen /Rect [100 400 400 600] "
            "/A << /S /Rendition /OP 4 /R << /S /MR /C << /S /MCD /D 5 0 R /CT (video/webm) >> >> >> >>"
        ),
    )
    items = extract_slide_media(path, 1)
    assert items
    assert items[0]["blob"] == b"FAKEWEBM"


def test_extract_pdf_media_from_rich_media(tmp_path: Path):
    path = write_pdf_with_embedded_annot(
        tmp_path / "rich.pdf",
        (
            "<< /Type /Annot /Subtype /RichMedia /Rect [100 400 400 600] "
            "/RichMediaContent << /Assets << /Names [(clip.webm) 5 0 R] >> >> >>"
        ),
    )
    items = extract_slide_media(path, 1)
    assert items
    assert items[0]["ext"] == ".webm"
    assert items[0]["blob"] == b"FAKEWEBM"


def test_extract_pdf_media_empty_without_embed(tmp_path: Path):
    path = write_hello_pdf(tmp_path / "plain.pdf", "Hello PDF")
    assert extract_slide_media(path, 1) == []


def test_publish_pdf_slide_media_writes_ui_files(appdata_tmp, tmp_path: Path):
    path = write_pdf_with_file_attachment(tmp_path / "att.pdf")
    items = publish_slide_media(path, 1, "pdfdeck")
    assert items[0]["src"].startswith("media/pdfdeck/")
    assert items[0]["src"].endswith(".webm")
    dest = appdata_tmp / "PPTStudyCompanion" / "ui" / Path(items[0]["src"])
    assert dest.is_file()
    assert dest.read_bytes() == b"FAKEWEBM"
