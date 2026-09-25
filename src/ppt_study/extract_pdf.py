from __future__ import annotations

import ctypes
from codecs import decode
from pathlib import Path

from ppt_study.extract_media import GIF_EXT, MIME, VIDEO_EXT, _kind_for
from ppt_study.pdf_cos import PdfCos

_HTTP = ("http://", "https://")


def extract_pdf_slide_links(source: Path, slide_index: int) -> list[dict]:
    path = Path(source)
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return []
    items: list[dict] = []
    try:
        items.extend(_pdfium_links(path, slide_index))
    except Exception:
        pass
    try:
        items.extend(_cos_links(path, slide_index))
    except Exception:
        pass
    return _unique_boxes(items, url=True)


def extract_pdf_slide_media(source: Path, slide_index: int) -> list[dict]:
    path = Path(source)
    if path.suffix.lower() != ".pdf" or not path.is_file():
        return []
    items: list[dict] = []
    try:
        items.extend(_pdfium_file_attachments(path, slide_index))
    except Exception:
        pass
    try:
        items.extend(_cos_media(path, slide_index))
    except Exception:
        pass
    return _unique_boxes(items, url=False)


def _unique_boxes(items: list[dict], url: bool) -> list[dict]:
    seen: set[tuple] = set()
    unique: list[dict] = []
    for item in items:
        if url:
            key = (
                item.get("url"),
                round(item["left"], 4),
                round(item["top"], 4),
                round(item["width"], 4),
                round(item["height"], 4),
            )
        else:
            key = (
                item.get("kind"),
                item.get("ext"),
                round(item["left"], 4),
                round(item["top"], 4),
                round(item["width"], 4),
                round(item["height"], 4),
            )
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _http_url(value: str) -> str:
    text = str(value or "").strip()
    if any(ch in text for ch in ("\n", "\r", "\x00")):
        return ""
    if text.lower().startswith(_HTTP):
        return text
    return ""


def _ui_box(left: float, bottom: float, right: float, top: float, page_w: float, page_h: float):
    x0, x1 = sorted((float(left), float(right)))
    y0, y1 = sorted((float(bottom), float(top)))
    if page_w <= 0 or page_h <= 0 or x1 <= x0 or y1 <= y0:
        return None
    box = (
        x0 / page_w,
        (page_h - y1) / page_h,
        (x1 - x0) / page_w,
        (y1 - y0) / page_h,
    )
    return _clamp_box(box)


def _clamp_box(box: tuple[float, float, float, float] | None):
    if box is None:
        return None
    left, top, width, height = box
    left = max(0.0, min(1.0, left))
    top = max(0.0, min(1.0, top))
    width = max(0.0, min(1.0 - left, width))
    height = max(0.0, min(1.0 - top, height))
    if width <= 0 or height <= 0:
        return None
    return {"left": left, "top": top, "width": width, "height": height}


def _media_item(name: str, blob: bytes, box: dict | None) -> dict | None:
    if not blob or box is None:
        return None
    ext = _sniff_ext(name, blob)
    kind = _kind_for(f"x{ext}" if ext else name)
    if not kind:
        return None
    return {
        "kind": kind,
        "ext": ext or Path(name).suffix.lower(),
        "blob": blob,
        "mime": MIME.get(ext, "application/octet-stream"),
        **box,
    }


def _sniff_ext(name: str, blob: bytes) -> str:
    ext = Path(str(name or "")).suffix.lower()
    if ext in VIDEO_EXT or ext in GIF_EXT:
        return ext
    if blob.startswith(b"GIF87a") or blob.startswith(b"GIF89a"):
        return ".gif"
    if blob.startswith(b"\x1aE\xdf\xa3"):
        return ".webm"
    if len(blob) >= 12 and blob[4:8] == b"ftyp":
        return ".mp4"
    if blob.startswith(b"RIFF") and blob[8:12] == b"AVI ":
        return ".avi"
    return ext


def _pdfium_page(path: Path, slide_index: int):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    index0 = slide_index - 1
    if index0 < 0 or index0 >= len(pdf):
        pdf.close()
        return None, None
    page = pdf[index0]
    return pdf, page


def _pdfium_links(path: Path, slide_index: int) -> list[dict]:
    import pypdfium2.raw as pdfium_c

    items: list[dict] = []
    pdf, page = _pdfium_page(path, slide_index)
    if pdf is None or page is None:
        return items
    try:
        pw, ph = float(page.get_width() or 0), float(page.get_height() or 0)
        count = pdfium_c.FPDFPage_GetAnnotCount(page.raw)
        for i in range(count):
            annot = pdfium_c.FPDFPage_GetAnnot(page.raw, i)
            if not annot:
                continue
            try:
                if pdfium_c.FPDFAnnot_GetSubtype(annot) != pdfium_c.FPDF_ANNOT_LINK:
                    continue
                url = _pdfium_annot_uri(pdf.raw, annot)
                if not url:
                    continue
                rect = pdfium_c.FS_RECTF()
                if not pdfium_c.FPDFAnnot_GetRect(annot, rect):
                    continue
                box = _ui_box(rect.left, rect.bottom, rect.right, rect.top, pw, ph)
                if box:
                    items.append({"url": url, **box})
            finally:
                pdfium_c.FPDFPage_CloseAnnot(annot)
        items.extend(_pdfium_web_links(page, pw, ph))
    finally:
        page.close()
        pdf.close()
    return items


def _pdfium_annot_uri(doc, annot) -> str:
    import pypdfium2.raw as pdfium_c

    link = pdfium_c.FPDFAnnot_GetLink(annot)
    if not link:
        return ""
    action = pdfium_c.FPDFLink_GetAction(link)
    if not action:
        return ""
    kind = pdfium_c.FPDFAction_GetType(action)
    if kind == pdfium_c.PDFACTION_URI:
        n = pdfium_c.FPDFAction_GetURIPath(doc, action, None, 0)
        if not n:
            return ""
        buf = ctypes.create_string_buffer(n)
        pdfium_c.FPDFAction_GetURIPath(doc, action, buf, n)
        return _http_url(buf.raw[: max(0, n - 1)].decode("utf-8", errors="ignore"))
    if kind == pdfium_c.PDFACTION_LAUNCH:
        n = pdfium_c.FPDFAction_GetFilePath(action, None, 0)
        if not n:
            return ""
        buf = ctypes.create_string_buffer(n)
        pdfium_c.FPDFAction_GetFilePath(action, buf, n)
        return _http_url(buf.raw[: max(0, n - 1)].decode("utf-8", errors="ignore"))
    return ""


def _pdfium_web_links(page, pw: float, ph: float) -> list[dict]:
    import pypdfium2.raw as pdfium_c

    items: list[dict] = []
    textpage = page.get_textpage()
    pagelink = pdfium_c.FPDFLink_LoadWebLinks(textpage.raw)
    try:
        count = pdfium_c.FPDFLink_CountWebLinks(pagelink)
        for i in range(count):
            n = pdfium_c.FPDFLink_GetURL(pagelink, i, None, 0)
            if n <= 1:
                continue
            buf = (pdfium_c.FPDF_WCHAR * n)()
            pdfium_c.FPDFLink_GetURL(pagelink, i, buf, n)
            url = _http_url(decode(memoryview(buf)[: n - 1], "utf-16-le", errors="ignore"))
            if not url:
                continue
            rects = pdfium_c.FPDFLink_CountRects(pagelink, i)
            for j in range(rects):
                left = ctypes.c_double()
                top = ctypes.c_double()
                right = ctypes.c_double()
                bottom = ctypes.c_double()
                if not pdfium_c.FPDFLink_GetRect(
                    pagelink, i, j, left, top, right, bottom
                ):
                    continue
                box = _ui_box(left.value, bottom.value, right.value, top.value, pw, ph)
                if box:
                    items.append({"url": url, **box})
    finally:
        pdfium_c.FPDFLink_CloseWebLinks(pagelink)
        textpage.close()
    return items


def _pdfium_file_attachments(path: Path, slide_index: int) -> list[dict]:
    import pypdfium2.raw as pdfium_c
    from pypdfium2._helpers.attachment import PdfAttachment

    items: list[dict] = []
    pdf, page = _pdfium_page(path, slide_index)
    if pdf is None or page is None:
        return items
    try:
        pw, ph = float(page.get_width() or 0), float(page.get_height() or 0)
        count = pdfium_c.FPDFPage_GetAnnotCount(page.raw)
        for i in range(count):
            annot = pdfium_c.FPDFPage_GetAnnot(page.raw, i)
            if not annot:
                continue
            try:
                if pdfium_c.FPDFAnnot_GetSubtype(annot) != pdfium_c.FPDF_ANNOT_FILEATTACHMENT:
                    continue
                att = pdfium_c.FPDFAnnot_GetFileAttachment(annot)
                if not att:
                    continue
                wrap = PdfAttachment(att, pdf)
                try:
                    blob = bytes(wrap.get_data())
                    name = wrap.get_name() or ""
                except Exception:
                    continue
                rect = pdfium_c.FS_RECTF()
                if not pdfium_c.FPDFAnnot_GetRect(annot, rect):
                    continue
                item = _media_item(
                    name,
                    blob,
                    _ui_box(rect.left, rect.bottom, rect.right, rect.top, pw, ph),
                )
                if item:
                    items.append(item)
            finally:
                pdfium_c.FPDFPage_CloseAnnot(annot)
    finally:
        page.close()
        pdf.close()
    return items


def _cos_links(path: Path, slide_index: int) -> list[dict]:
    cos = PdfCos(path.read_bytes())
    page = cos.page(slide_index - 1)
    if page is None:
        return []
    pw, ph, origin = _page_metrics(page)
    items: list[dict] = []
    for annot in cos.annots(page):
        if annot.get("/Subtype") != "/Link":
            continue
        url = _action_url(cos, annot.get("/A"))
        if not url:
            continue
        box = _rect_box(annot.get("/Rect"), pw, ph, origin)
        if box:
            items.append({"url": url, **box})
    return items


def _cos_media(path: Path, slide_index: int) -> list[dict]:
    cos = PdfCos(path.read_bytes())
    page = cos.page(slide_index - 1)
    if page is None:
        return []
    pw, ph, origin = _page_metrics(page)
    items: list[dict] = []
    for annot in cos.annots(page):
        box = _rect_box(annot.get("/Rect"), pw, ph, origin)
        subtype = annot.get("/Subtype")
        found: list[tuple[str, bytes]] = []
        if subtype == "/FileAttachment":
            found.append(cos.filespec(annot.get("/FS")))
        elif subtype == "/Movie":
            movie = cos.resolve(annot.get("/Movie")) or {}
            spec = movie.get("/F") if isinstance(movie, dict) else movie
            found.append(cos.filespec(spec))
        elif subtype == "/Screen":
            found.extend(_action_files(cos, annot.get("/A")))
        elif subtype == "/RichMedia":
            found.extend(_rich_media_files(cos, annot))
        for name, blob in found:
            item = _media_item(name, blob, box)
            if item:
                items.append(item)
    return items


def _page_metrics(page: dict) -> tuple[float, float, tuple[float, float]]:
    box = page.get("/CropBox") or page.get("/MediaBox") or [0, 0, 612, 792]
    nums = [float(v) for v in box[:4]]
    x0, x1 = sorted((nums[0], nums[2]))
    y0, y1 = sorted((nums[1], nums[3]))
    w, h = x1 - x0, y1 - y0
    rot = int(page.get("/Rotate") or 0) % 360
    if rot in (90, 270):
        w, h = h, w
    return w, h, (x0, y0)


def _rect_box(rect, page_w: float, page_h: float, origin: tuple[float, float]):
    if not isinstance(rect, list) or len(rect) < 4:
        return None
    left, bottom, right, top = [float(v) for v in rect[:4]]
    return _ui_box(
        left - origin[0],
        bottom - origin[1],
        right - origin[0],
        top - origin[1],
        page_w,
        page_h,
    )


def _action_url(cos: PdfCos, action) -> str:
    action = cos.resolve(action)
    if isinstance(action, list):
        for item in action:
            url = _action_url(cos, item)
            if url:
                return url
        return ""
    if not isinstance(action, dict):
        return ""
    kind = action.get("/S")
    if kind == "/URI":
        return _http_url(str(action.get("/URI") or ""))
    if kind == "/Launch":
        return _http_url(_as_text(action.get("/F")))
    nxt = action.get("/Next")
    if nxt is not None:
        return _action_url(cos, nxt)
    return ""


def _as_text(value) -> str:
    if isinstance(value, dict):
        value = value.get("/F") or value.get("/UF") or ""
    return str(value or "")


def _action_files(cos: PdfCos, action) -> list[tuple[str, bytes]]:
    action = cos.resolve(action)
    found: list[tuple[str, bytes]] = []
    if isinstance(action, list):
        for item in action:
            found.extend(_action_files(cos, item))
        return found
    if not isinstance(action, dict):
        return found
    kind = action.get("/S")
    if kind == "/Rendition":
        rendition = cos.resolve(action.get("/R"))
        if isinstance(rendition, list) and rendition:
            rendition = rendition[0]
        rendition = cos.resolve(rendition) or {}
        clip = cos.resolve(rendition.get("/C")) or {}
        if isinstance(clip, dict) and clip.get("/D") is not None:
            found.append(cos.filespec(clip.get("/D")))
    elif kind == "/Movie":
        movie = cos.resolve(action.get("/Movie") or action.get("/F")) or {}
        spec = movie.get("/F") if isinstance(movie, dict) else movie
        found.append(cos.filespec(spec))
    nxt = action.get("/Next")
    if nxt is not None:
        found.extend(_action_files(cos, nxt))
    return found


def _rich_media_files(cos: PdfCos, annot: dict) -> list[tuple[str, bytes]]:
    content = cos.resolve(annot.get("/RichMediaContent")) or {}
    if not isinstance(content, dict):
        return []
    assets = cos.resolve(content.get("/Assets")) or {}
    names = cos._name_tree(assets) if isinstance(assets, dict) else {}
    found: list[tuple[str, bytes]] = []
    for key, spec in names.items():
        name, blob = cos.filespec(spec)
        found.append((name or key, blob))
    return found
