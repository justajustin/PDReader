from __future__ import annotations

from pathlib import Path

from ppt_study.export_com import EXPORT_WIDTH, ExportError


def export_pdf_pages(pdf_path: Path, out_dir: Path) -> list[Path]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:
        raise ExportError("当前程序未包含 PDF 支持") from exc
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        pdf = pdfium.PdfDocument(str(pdf_path))
    except Exception as exc:
        raise ExportError("无法打开这个 PDF") from exc
    paths: list[Path] = []
    try:
        count = len(pdf)
        if count <= 0:
            raise ExportError("这个 PDF 没有页面")
        for i in range(count):
            page = pdf[i]
            try:
                width = float(page.get_width() or 0)
                scale = EXPORT_WIDTH / width if width > 0 else 2.0
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil().convert("RGB")
                finally:
                    bitmap.close()
                dest = out_dir / f"slide_{i + 1:03d}.png"
                image.save(dest, "PNG")
                paths.append(dest)
            finally:
                page.close()
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError("导出 PDF 页面失败") from exc
    finally:
        pdf.close()
    if not paths:
        raise ExportError("这个 PDF 没有页面")
    return paths
