from __future__ import annotations

import ctypes
from pathlib import Path


def write_pdf_objects(path: Path, objects: list[str | bytes]) -> Path:
    header = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    encoded: list[bytes] = []
    for i, body in enumerate(objects, start=1):
        raw = body.encode("latin-1") if isinstance(body, str) else body
        if not raw.endswith(b"\n"):
            raw += b"\n"
        encoded.append(f"{i} 0 obj\n".encode("ascii") + raw + b"endobj\n")
    offsets = [0]
    cursor = len(header)
    for blob in encoded:
        offsets.append(cursor)
        cursor += len(blob)
    xref = [b"xref\n", f"0 {len(offsets)}\n".encode("ascii"), b"0000000000 65535 f \n"]
    for off in offsets[1:]:
        xref.append(f"{off:010d} 00000 n \n".encode("ascii"))
    trailer = (
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
        f"startxref\n{cursor}\n%%EOF\n"
    ).encode("ascii")
    path.write_bytes(header + b"".join(encoded) + b"".join(xref) + trailer)
    return path


def write_hello_pdf(path: Path, text: str = "Hello PDF") -> Path:
    safe = (
        str(text)
        .replace("\\", "\\\\")
        .replace("(", "\\(")
        .replace(")", "\\)")
    )
    stream = f"BT /F1 24 Tf 72 700 Td ({safe}) Tj ET"
    stream_bytes = stream.encode("latin-1")
    return write_pdf_objects(
        path,
        [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
            ),
            f"<< /Length {len(stream_bytes)} >>\nstream\n{stream}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ],
    )


def _filespec_and_stream(blob: bytes, filename: str) -> tuple[str, bytes]:
    safe = filename.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    spec = f"<< /Type /Filespec /F ({safe}) /EF << /F 6 0 R >> >>"
    stream = f"<< /Length {len(blob)} >>\nstream\n".encode("latin-1") + blob + b"\nendstream"
    return spec, stream


def write_pdf_with_embedded_annot(
    path: Path,
    annot: str,
    blob: bytes = b"FAKEWEBM",
    filename: str = "clip.webm",
) -> Path:
    spec, stream = _filespec_and_stream(blob, filename)
    return write_pdf_objects(
        path,
        [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Annots [4 0 R] >>",
            annot,
            spec,
            stream,
        ],
    )


def write_pdf_with_uri_annot(path: Path, url: str = "https://example.com/wiki") -> Path:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c

    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(612, 792)
    annot = pdfium_c.FPDFPage_CreateAnnot(page.raw, pdfium_c.FPDF_ANNOT_LINK)
    pdfium_c.FPDFAnnot_SetRect(annot, pdfium_c.FS_RECTF(left=72, bottom=680, right=400, top=720))
    pdfium_c.FPDFAnnot_SetURI(annot, url.encode("utf-8"))
    pdfium_c.FPDFPage_CloseAnnot(annot)
    pdf.save(path)
    pdf.close()
    return path


def write_pdf_with_file_attachment(
    path: Path, blob: bytes = b"FAKEWEBM", filename: str = "clip.webm"
) -> Path:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_c
    from pypdfium2._helpers.attachment import PdfAttachment

    pdf = pdfium.PdfDocument.new()
    page = pdf.new_page(612, 792)
    annot = pdfium_c.FPDFPage_CreateAnnot(page.raw, pdfium_c.FPDF_ANNOT_FILEATTACHMENT)
    pdfium_c.FPDFAnnot_SetRect(
        annot, pdfium_c.FS_RECTF(left=100, bottom=400, right=400, top=600)
    )
    name = (filename + "\x00").encode("utf-16-le")
    att = pdfium_c.FPDFAnnot_AddFileAttachment(
        annot, ctypes.cast(name, ctypes.POINTER(ctypes.c_ushort))
    )
    PdfAttachment(att, pdf).set_data(blob)
    pdfium_c.FPDFPage_CloseAnnot(annot)
    pdf.save(path)
    pdf.close()
    return path
