from pathlib import Path

from ppt_study.export_com import ExportError
from ppt_study.export_pdf import export_pdf_pages
from pdf_util import write_hello_pdf


def test_export_pdf_pages_writes_png(tmp_path: Path):
    pdf = write_hello_pdf(tmp_path / "hello.pdf", "Hello PDF")
    out = tmp_path / "slides"
    paths = export_pdf_pages(pdf, out)
    assert len(paths) == 1
    assert paths[0].is_file()
    assert paths[0].name == "slide_001.png"


def test_export_pdf_pages_rejects_bad_file(tmp_path: Path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"not a pdf")
    try:
        export_pdf_pages(bad, tmp_path / "slides")
    except ExportError as exc:
        assert "PDF" in str(exc)
    else:
        raise AssertionError("expected ExportError")
