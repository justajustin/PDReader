import os

from ppt_study.models import DeckRecord, SlideRecord
from ppt_study.store import load_deck, save_deck, save_script


def _deck(path: str, mtime: float) -> DeckRecord:
    return DeckRecord(
        source_path=path,
        mtime=mtime,
        slides=[
            SlideRecord(1, "T1", "body", "", "t1.png", "s1.png", None),
            SlideRecord(2, "T2", "body2", "", "t2.png", "s2.png", None),
        ],
    )


def test_save_and_load_same_mtime(appdata_tmp, tmp_path):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")
    mtime = ppt.stat().st_mtime
    save_deck(_deck(str(ppt), mtime))
    loaded = load_deck(str(ppt))
    assert loaded is not None
    assert loaded.slides[0].title == "T1"
    assert loaded.mtime == mtime


def test_load_returns_none_when_file_changed(appdata_tmp, tmp_path):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")
    save_deck(_deck(str(ppt), ppt.stat().st_mtime))
    ppt.write_bytes(b"fake2")
    os.utime(ppt, (ppt.stat().st_atime, ppt.stat().st_mtime + 1))
    assert load_deck(str(ppt)) is None


def test_save_script_persists(appdata_tmp, tmp_path):
    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")
    mtime = ppt.stat().st_mtime
    save_deck(_deck(str(ppt), mtime))
    save_script(str(ppt), mtime, 1, "讲稿内容")
    loaded = load_deck(str(ppt))
    assert loaded.slide_by_index(1).script == "讲稿内容"


def test_save_script_keeps_concurrent_pages(appdata_tmp, tmp_path):
    import threading

    ppt = tmp_path / "a.pptx"
    ppt.write_bytes(b"fake")
    mtime = ppt.stat().st_mtime
    save_deck(_deck(str(ppt), mtime))
    errors = []

    def write(index, text):
        try:
            save_script(str(ppt), mtime, index, text)
        except Exception as exc:
            errors.append(exc)

    first = threading.Thread(target=write, args=(1, "第一页"))
    second = threading.Thread(target=write, args=(2, "第二页"))
    first.start()
    second.start()
    first.join()
    second.join()
    assert not errors
    loaded = load_deck(str(ppt))
    assert loaded.slide_by_index(1).script == "第一页"
    assert loaded.slide_by_index(2).script == "第二页"


def test_favorites_are_per_pptx_file(appdata_tmp, tmp_path):
    from ppt_study.store import load_favorites, toggle_favorite

    ppt = tmp_path / "lec.pptx"
    ppt.write_bytes(b"fake")
    other = tmp_path / "other.pptx"
    other.write_bytes(b"fake")
    assert toggle_favorite(str(ppt), 11) is True
    assert load_favorites(str(ppt)) == [11]
    assert load_favorites(str(other)) == []
    assert toggle_favorite(str(ppt), 11) is False
    assert load_favorites(str(ppt)) == []
    toggle_favorite(str(ppt), 3)
    toggle_favorite(str(ppt), 11)
    assert load_favorites(str(ppt)) == [3, 11]


def test_qa_favorites_save_and_character_search(appdata_tmp):
    from ppt_study.store import add_qa_favorite, remove_qa_favorite, search_qa_favorites

    first = add_qa_favorite(
        {
            "question": "什么是双线性插值",
            "answer": "用四个邻近像素做加权平均。",
            "file_name": "lec03.pptx",
            "slide_index": 9,
        }
    )
    second = add_qa_favorite(
        {
            "question": "卷积核怎么滑动",
            "answer": "核在图像上逐格移动并求加权和。",
            "file_name": "lec01.pptx",
            "slide_index": 4,
        }
    )
    assert first["id"]
    assert second["id"] != first["id"]
    all_items = search_qa_favorites("")
    assert len(all_items) == 2
    hit = search_qa_favorites("双线性")
    assert len(hit) == 1
    assert hit[0]["question"] == "什么是双线性插值"
    hit2 = search_qa_favorites("加权")
    assert {x["id"] for x in hit2} == {first["id"], second["id"]}
    assert search_qa_favorites("不存在的词") == []
    assert remove_qa_favorite(first["id"]) is True
    assert [x["id"] for x in search_qa_favorites("")] == [second["id"]]
