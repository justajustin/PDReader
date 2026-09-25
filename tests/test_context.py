from ppt_study.context import build_qa_messages, build_script_messages, retrieve_slide_indices
from ppt_study.models import DeckRecord, SlideRecord


def _deck():
    slides = [
        SlideRecord(1, "Intro", "course overview", "", "", "", None),
        SlideRecord(2, "Blur", "gaussian blur removes high frequency", "", "", "", None),
        SlideRecord(3, "Sharpening revisited", "original minus smoothed equals detail", "", "", "", None),
        SlideRecord(4, "Next", "unsharp mask formula", "", "", "", None),
    ]
    return DeckRecord("x.pptx", 1.0, slides)


def test_retrieve_prefers_overlapping_slides():
    hits = retrieve_slide_indices(_deck(), "gaussian high frequency", current_index=3, limit=6)
    assert 2 in hits
    assert 3 not in hits


def test_script_messages_include_neighbors_and_image():
    msgs = build_script_messages(_deck(), 3, "data:image/jpeg;base64,xx")
    assert msgs[0]["role"] == "system"
    user = msgs[-1]
    parts = user["content"]
    texts = " ".join(p["text"] for p in parts if p["type"] == "text")
    assert "Sharpening" in texts
    assert "Blur" in texts
    assert "unsharp" in texts
    assert any(p["type"] == "image_url" for p in parts)


def test_script_prompt_asks_for_readable_math():
    msgs = build_script_messages(_deck(), 3, None)
    blob = msgs[0]["content"] + " " + msgs[-1]["content"][0]["text"]
    assert "LaTeX" in blob
    assert "代码块" in blob


def test_qa_keeps_history_and_marks_supplement():
    history = [
        {"role": "user", "content": "上一问"},
        {"role": "assistant", "content": "上一答"},
    ]
    msgs = build_qa_messages(
        _deck(), 3, "data:image/jpeg;base64,xx", history, "示意图在干什么？"
    )
    assert any("补充" in m["content"] for m in msgs if m["role"] == "system")
    assert msgs[-1]["content"] == "示意图在干什么？"
    assert msgs[-2]["content"] == "上一答"
    assert msgs[-3]["content"] == "上一问"


def test_qa_prompt_allows_visuals():
    msgs = build_qa_messages(_deck(), 3, None, [], "帮我直观理解梯度")
    sys = msgs[0]["content"]
    assert "```viz" in sys
    assert "surface3d" in sys
    assert "showGradient" in sys


def test_qa_prompt_does_not_force_3d_on_every_answer():
    sys = build_qa_messages(_deck(), 3, None, [], "atan2怎么计算")[0]["content"]
    assert "必须给出 surface3d" not in sys
    assert "不要在普通问答里自动附加" in sys


def test_qa_prompt_supports_process_animation():
    sys = build_qa_messages(_deck(), 3, None, [], "用动画演示卷积")[0]["content"]
    assert '"type":"anim"' in sys or "type 为 anim" in sys
    assert "kernel_slide" in sys
    assert "gradient_walk" in sys
    assert "优先用动画" in sys


def test_qa_history_strips_previous_viz():
    history = [
        {"role": "user", "content": "什么是梯度"},
        {
            "role": "assistant",
            "content": "梯度指向变化最快的方向。\n```viz\n{\"type\":\"surface3d\"}\n```",
        },
    ]
    msgs = build_qa_messages(_deck(), 3, None, history, "atan2怎么计算")
    prev = msgs[-2]["content"]
    assert "```viz" not in prev
    assert "梯度指向变化最快的方向" in prev


def test_qa_attachments_focus_on_screenshots():
    shot = "data:image/jpeg;base64,abc"
    msgs = build_qa_messages(
        _deck(), 3, "data:image/jpeg;base64,slide", [], "这个公式什么意思", [shot]
    )
    sys = msgs[0]["content"]
    assert "截图" in sys
    last = msgs[-1]
    assert last["role"] == "user"
    parts = last["content"]
    assert isinstance(parts, list)
    texts = " ".join(p["text"] for p in parts if p["type"] == "text")
    assert "截图" in texts
    images = [p for p in parts if p["type"] == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"] == shot
