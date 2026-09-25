from __future__ import annotations

import re

from ppt_study.models import DeckRecord, SlideRecord

TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{1,2}")
SCRIPT_NEIGHBOR_CHARS = 400


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in TOKEN_RE.finditer(text)}


def _clip(text: str, n: int = SCRIPT_NEIGHBOR_CHARS) -> str:
    text = text.strip()
    return text if len(text) <= n else text[:n] + "…"


def _page_text(slide: SlideRecord) -> str:
    return "\n".join(x for x in (slide.title, slide.body, slide.notes) if x)


def retrieve_slide_indices(
    deck: DeckRecord, question: str, current_index: int, limit: int = 6
) -> list[int]:
    q = _tokens(question)
    scored: list[tuple[int, int]] = []
    for slide in deck.slides:
        if slide.index == current_index:
            continue
        overlap = len(q & _tokens(_page_text(slide)))
        if overlap:
            scored.append((overlap, slide.index))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [idx for _, idx in scored[:limit]]


def _neighbor_indices(deck: DeckRecord, current_index: int) -> list[int]:
    found = {s.index for s in deck.slides}
    out = []
    for idx in (current_index - 1, current_index + 1):
        if idx in found:
            out.append(idx)
    return out


def _pages_block(deck: DeckRecord, indices: list[int]) -> str:
    lines = []
    for idx in indices:
        slide = deck.slide_by_index(idx)
        lines.append(
            f"第{idx}页 {slide.title}\n{_clip(_page_text(slide))}"
        )
    return "\n\n".join(lines)


def _user_with_images(text: str, image_urls: list[str] | None) -> dict:
    parts: list[dict] = [{"type": "text", "text": text}]
    for url in image_urls or []:
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": "user", "content": parts}


def _user_with_image(text: str, image_data_url: str | None) -> dict:
    urls = [image_data_url] if image_data_url else []
    return _user_with_images(text, urls)


def _strip_visual_blocks(content: str) -> str:
    text = re.sub(r"```viz\s*[\s\S]*?```", "", content, flags=re.IGNORECASE)
    text = re.sub(r"```svg\s*[\s\S]*?```", "", text, flags=re.IGNORECASE)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_script_messages(
    deck: DeckRecord, current_index: int, image_data_url: str | None
) -> list[dict]:
    slide = deck.slide_by_index(current_index)
    neighbors = _neighbor_indices(deck, current_index)
    text = (
        "请根据当前幻灯片图片和文字，写一段老师会讲的本页讲稿，中文，口语清楚。"
        "先讲本页内容，不要编造页面上没有的公式数字。\n\n"
        f"当前第{current_index}页\n{_page_text(slide)}\n\n"
        f"相邻页：\n{_pages_block(deck, neighbors)}"
    )
    return [
        {
            "role": "system",
            "content": (
                "你是课件助教。讲稿必须依据当前页图文。"
                "课件没写的背景只能作为简短补充，并写明这是补充。"
                "用户用中文则用中文。"
                "公式用 LaTeX：行内用 \\( ... \\)，独立公式用 \\[ ... \\]。"
                "不要把公式放进 markdown 代码块，也不要把反斜杠命令当正文展示。"
                "提到公式时先用中文读法说一句，例如「对 x 的偏导数」。"
            ),
        },
        _user_with_image(text, image_data_url),
    ]


def build_qa_messages(
    deck: DeckRecord,
    current_index: int,
    image_data_url: str | None,
    history: list[dict],
    question: str,
    attachments: list[str] | None = None,
) -> list[dict]:
    slide = deck.slide_by_index(current_index)
    retrieved = retrieve_slide_indices(deck, question, current_index, limit=6)
    extra = []
    for idx in _neighbor_indices(deck, current_index) + retrieved:
        if idx not in extra and idx != current_index:
            extra.append(idx)
    sys = (
        "你是课件学习助教。回答要结合当前幻灯片图片、当前页文字和其它相关页。"
        "课件里有的，先依据课件；课件没有的，可以用你的知识补充，但必须明确区分"
        "「课件中的内容」和「补充解释」。不要假装课件里出现了没有的原文。"
        "公式用 LaTeX：行内 \\( ... \\)，独立公式 \\[ ... \\]，不要放进 markdown 代码块。"
        "不要在普通问答里自动附加三维曲面、示意图或动画。"
        "只有用户明确要求画图、示意图、三维、可视化、动画、演示时，才附加可视化块。"
        "解释过程、卷积、滤波、采样、插值、梯度方向时，若用户要求直观展示，优先用动画："
        '```viz 代码块，JSON 例如 {"type":"anim","title":"卷积：核在滑动","preset":"kernel_slide"}。'
        "preset 可选 kernel_slide、gaussian_blur、resample、gradient_walk、atan2、edge_detect。"
        "也可提供 frames 数组（每帧 caption、grid、window、arrows），只能用数字和字符串，不要写 script。"
        "静态三维强度曲面用 ```viz JSON，例如 "
        '{"type":"surface3d","title":"强度曲面与梯度","preset":"ramp_diag","showGradient":true,"resolution":24}'
        "。preset 可选 ramp_x、ramp_y、ramp_diag、step_x、step_y、corner、gaussian。"
        "也可提供 z 为二维数值数组。showGradient 为 true 时绘制梯度箭头：方向指向强度增加最快处，长度表示模。"
        "平面图用 ```svg 包一层内联 SVG，不要写 script。"
        "若用户附上截图，截图是他希望你重点解释的局部；请先看截图，再对照当前页。"
        "默认中文回答。"
    )
    context = (
        f"当前第{current_index}页\n{_page_text(slide)}\n\n"
        f"相关页：\n{_pages_block(deck, extra)}"
    )
    trimmed = []
    for item in history[-24:]:
        role = item.get("role")
        content = item.get("content")
        if role in ("user", "assistant") and content is not None:
            if isinstance(content, str):
                content = _strip_visual_blocks(content)
            trimmed.append({"role": role, "content": content})
    messages: list[dict] = [{"role": "system", "content": sys}]
    messages.append(_user_with_image(context, image_data_url))
    messages.append(
        {
            "role": "assistant",
            "content": "已了解当前页和相关页，可以提问。",
        }
    )
    messages.extend(trimmed)
    qtext = (question or "").strip()
    shots = [u for u in (attachments or []) if u]
    if shots:
        focus = "下面附上了截图，请重点解释截图里的内容（公式、符号、图示），当前页只作对照。"
        qtext = f"{qtext}\n\n{focus}" if qtext else focus
        messages.append(_user_with_images(qtext, shots))
    else:
        messages.append({"role": "user", "content": qtext})
    return messages
