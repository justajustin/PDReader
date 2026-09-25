from __future__ import annotations

import posixpath
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from ppt_study.paths import app_data_dir

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
}
R_NS = NS["r"]
VIDEO_EXT = {".webm", ".mp4", ".m4v", ".mov", ".ogg", ".ogv", ".avi"}
GIF_EXT = {".gif"}
MIME = {
    ".webm": "video/webm",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".mov": "video/quicktime",
    ".ogg": "video/ogg",
    ".ogv": "video/ogg",
    ".avi": "video/x-msvideo",
    ".gif": "image/gif",
}


def _attr(elem: ET.Element, local: str) -> str:
    for key, value in elem.attrib.items():
        if key == local or key.endswith("}" + local):
            return value
    return ""


def _slide_size(z: zipfile.ZipFile) -> tuple[int, int]:
    try:
        root = ET.fromstring(z.read("ppt/presentation.xml"))
    except KeyError:
        return 9144000, 6858000
    sz = root.find("p:sldSz", NS)
    if sz is None:
        sz = root.find(".//p:sldSz", NS)
    if sz is None:
        return 9144000, 6858000
    return int(sz.get("cx") or 9144000), int(sz.get("cy") or 6858000)


def _slide_rels(z: zipfile.ZipFile, slide_index: int) -> dict[str, tuple[str, str, str]]:
    name = f"ppt/slides/_rels/slide{slide_index}.xml.rels"
    try:
        root = ET.fromstring(z.read(name))
    except KeyError:
        return {}
    out: dict[str, tuple[str, str, str]] = {}
    for rel in root:
        rid = rel.get("Id") or ""
        target = rel.get("Target") or ""
        rtype = rel.get("Type") or ""
        mode = (rel.get("TargetMode") or "Internal").lower()
        if rid and target:
            out[rid] = (rtype, target, mode)
    return out


def _rels(z: zipfile.ZipFile, slide_index: int) -> dict[str, tuple[str, str]]:
    return {
        rid: (rtype, target)
        for rid, (rtype, target, mode) in _slide_rels(z, slide_index).items()
        if mode != "external"
    }


def _zip_target(target: str) -> str:
    return posixpath.normpath(posixpath.join("ppt/slides", target))


def _xfrm_box(
    pic: ET.Element, slide_w: int, slide_h: int
) -> tuple[float, float, float, float] | None:
    xfrm = pic.find("./p:spPr/a:xfrm", NS)
    if xfrm is None:
        xfrm = pic.find(".//a:xfrm", NS)
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    x = int(off.get("x") or 0)
    y = int(off.get("y") or 0)
    w = int(ext.get("cx") or 0)
    h = int(ext.get("cy") or 0)
    if slide_w <= 0 or slide_h <= 0 or w <= 0 or h <= 0:
        return None
    return (x / slide_w, y / slide_h, w / slide_w, h / slide_h)


def _kind_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in GIF_EXT:
        return "gif"
    return ""


def extract_slide_media(source: Path, slide_index: int) -> list[dict]:
    path = Path(source)
    if path.suffix.lower() == ".pdf":
        from ppt_study.extract_pdf import extract_pdf_slide_media

        return extract_pdf_slide_media(path, slide_index)
    if path.suffix.lower() != ".pptx" or not path.is_file():
        return []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return []
    with z:
        slide_name = f"ppt/slides/slide{slide_index}.xml"
        try:
            root = ET.fromstring(z.read(slide_name))
        except KeyError:
            return []
        slide_w, slide_h = _slide_size(z)
        rels = _rels(z, slide_index)
        items: list[dict] = []
        for pic in root.findall(".//p:pic", NS):
            box = _xfrm_box(pic, slide_w, slide_h)
            if box is None:
                continue
            rids: list[str] = []
            video = pic.find(".//a:videoFile", NS)
            if video is not None:
                rid = _attr(video, "link") or _attr(video, "embed")
                if rid:
                    rids.append(rid)
            for node in pic.iter():
                tag = node.tag.rsplit("}", 1)[-1]
                if tag in {"media", "videoFile"}:
                    rid = _attr(node, "embed") or _attr(node, "link")
                    if rid:
                        rids.append(rid)
            blip = pic.find(".//a:blip", NS)
            if blip is not None:
                rid = _attr(blip, "embed")
                if rid:
                    rids.append(rid)
            seen: set[str] = set()
            for rid in rids:
                if rid in seen or rid not in rels:
                    continue
                seen.add(rid)
                _rtype, target = rels[rid]
                zip_path = _zip_target(target)
                kind = _kind_for(zip_path)
                if not kind:
                    continue
                try:
                    blob = z.read(zip_path)
                except KeyError:
                    continue
                ext = Path(zip_path).suffix.lower()
                left, top, width, height = box
                items.append(
                    {
                        "kind": kind,
                        "ext": ext,
                        "blob": blob,
                        "mime": MIME.get(ext, "application/octet-stream"),
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                    }
                )
                break
        return items


def _xfrm_tuple(xfrm: ET.Element | None) -> tuple[int, int, int, int] | None:
    if xfrm is None:
        return None
    off = xfrm.find("a:off", NS)
    ext = xfrm.find("a:ext", NS)
    if off is None or ext is None:
        return None
    w = int(ext.get("cx") or 0)
    h = int(ext.get("cy") or 0)
    if w <= 0 or h <= 0:
        return None
    return (int(off.get("x") or 0), int(off.get("y") or 0), w, h)


def _http_urls(el: ET.Element, rels: dict[str, tuple[str, str, str]]) -> list[str]:
    found: list[str] = []
    for node in el.iter():
        if node.tag.rsplit("}", 1)[-1] != "hlinkClick":
            continue
        rid = _attr(node, "id")
        if not rid or rid not in rels:
            continue
        _rtype, target, _mode = rels[rid]
        url = str(target or "").strip()
        low = url.lower()
        if low.startswith("http://") or low.startswith("https://"):
            found.append(url)
    return found


def _collect_links(
    parent: ET.Element,
    mapper,
    rels: dict[str, tuple[str, str, str]],
    slide_w: int,
    slide_h: int,
    items: list[dict],
) -> None:
    for child in list(parent):
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "grpSp":
            xfrm = child.find("./p:grpSpPr/a:xfrm", NS)
            box = _xfrm_tuple(xfrm)
            ch_off = xfrm.find("a:chOff", NS) if xfrm is not None else None
            ch_ext = xfrm.find("a:chExt", NS) if xfrm is not None else None
            if box and ch_off is not None and ch_ext is not None:
                gx, gy, gw, gh = mapper(*box)
                chx = int(ch_off.get("x") or 0)
                chy = int(ch_off.get("y") or 0)
                chw = int(ch_ext.get("cx") or 0) or 1
                chh = int(ch_ext.get("cy") or 0) or 1

                def child_map(
                    x: int,
                    y: int,
                    w: int,
                    h: int,
                    gx: int = gx,
                    gy: int = gy,
                    gw: int = gw,
                    gh: int = gh,
                    chx: int = chx,
                    chy: int = chy,
                    chw: int = chw,
                    chh: int = chh,
                ) -> tuple[int, int, int, int]:
                    return (
                        int(gx + (x - chx) * gw / chw),
                        int(gy + (y - chy) * gh / chh),
                        int(w * gw / chw),
                        int(h * gh / chh),
                    )

                _collect_links(child, child_map, rels, slide_w, slide_h, items)
            else:
                _collect_links(child, mapper, rels, slide_w, slide_h, items)
            continue
        if tag not in ("sp", "pic", "cxnSp", "graphicFrame"):
            continue
        xfrm = child.find("./p:spPr/a:xfrm", NS)
        if xfrm is None:
            xfrm = child.find("./p:xfrm", NS)
        box = _xfrm_tuple(xfrm)
        if box is None:
            continue
        ax, ay, aw, ah = mapper(*box)
        if slide_w <= 0 or slide_h <= 0 or aw <= 0 or ah <= 0:
            continue
        for url in _http_urls(child, rels):
            items.append(
                {
                    "url": url,
                    "left": ax / slide_w,
                    "top": ay / slide_h,
                    "width": aw / slide_w,
                    "height": ah / slide_h,
                }
            )


def extract_slide_links(source: Path, slide_index: int) -> list[dict]:
    path = Path(source)
    if path.suffix.lower() == ".pdf":
        from ppt_study.extract_pdf import extract_pdf_slide_links

        return extract_pdf_slide_links(path, slide_index)
    if path.suffix.lower() != ".pptx" or not path.is_file():
        return []
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        return []
    with z:
        slide_name = f"ppt/slides/slide{slide_index}.xml"
        try:
            root = ET.fromstring(z.read(slide_name))
        except KeyError:
            return []
        slide_w, slide_h = _slide_size(z)
        rels = _slide_rels(z, slide_index)
        tree = root.find(".//p:spTree", NS)
        if tree is None:
            return []
        items: list[dict] = []
        _collect_links(tree, lambda x, y, w, h: (x, y, w, h), rels, slide_w, slide_h, items)
        seen: set[tuple] = set()
        unique: list[dict] = []
        for item in items:
            key = (
                item["url"],
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


def publish_slide_media(source: Path, slide_index: int, deck_key: str) -> list[dict]:
    extracted = extract_slide_media(source, slide_index)
    if not extracted:
        return []
    folder = app_data_dir() / "ui" / "media" / deck_key
    folder.mkdir(parents=True, exist_ok=True)
    published: list[dict] = []
    for i, item in enumerate(extracted):
        name = f"s{slide_index}_{i}{item['ext']}"
        dest = folder / name
        if not dest.exists() or dest.stat().st_size != len(item["blob"]):
            dest.write_bytes(item["blob"])
        published.append(
            {
                "kind": item["kind"],
                "src": f"media/{deck_key}/{name}",
                "mime": item["mime"],
                "left": item["left"],
                "top": item["top"],
                "width": item["width"],
                "height": item["height"],
            }
        )
    return published
