from pathlib import Path

from PIL import Image

from ppt_study.image_util import file_to_display_data_url, image_to_api_data_url, make_thumbnail


def test_make_thumbnail_resizes_width(tmp_path: Path):
    src = tmp_path / "slide.png"
    Image.new("RGB", (1920, 1080), "white").save(src)
    dest = tmp_path / "thumb.png"
    make_thumbnail(src, dest, width=160)
    with Image.open(dest) as im:
        assert im.size[0] == 160
        assert im.size[1] == 90


def test_api_data_url_is_jpeg_and_capped(tmp_path: Path):
    src = tmp_path / "big.png"
    Image.new("RGB", (3000, 2000), "blue").save(src)
    url = image_to_api_data_url(src)
    assert url.startswith("data:image/jpeg;base64,")
    payload = url.split(",", 1)[1]
    import base64
    raw = base64.b64decode(payload)
    assert len(raw) < 1_500_000
    from io import BytesIO
    with Image.open(BytesIO(raw)) as im:
        assert max(im.size) <= 1280


def test_display_data_url_png(tmp_path: Path):
    src = tmp_path / "slide.png"
    Image.new("RGB", (20, 10), "red").save(src)
    url = file_to_display_data_url(src)
    assert url.startswith("data:image/png;base64,")


def test_data_url_is_compressed_for_api(tmp_path: Path):
    from ppt_study.image_util import data_url_to_api_data_url

    src = tmp_path / "clip.png"
    Image.new("RGB", (2000, 1200), "green").save(src)
    display = file_to_display_data_url(src)
    url = data_url_to_api_data_url(display)
    assert url.startswith("data:image/jpeg;base64,")
    import base64
    from io import BytesIO

    raw = base64.b64decode(url.split(",", 1)[1])
    with Image.open(BytesIO(raw)) as im:
        assert max(im.size) <= 1280
