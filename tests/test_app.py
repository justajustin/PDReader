from pathlib import Path


def test_web_dir_points_to_project_web():
    from ppt_study.app import web_dir

    project_root = Path(__file__).resolve().parents[1]
    web = web_dir()
    assert web == project_root / "web"
    assert (web / "index.html").is_file()
    assert (web / "styles.css").is_file()
    assert (web / "app.js").is_file()


def test_web_ui_has_required_markup():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    for marker in (
        'id="btn-open"',
        'id="file-name"',
        'id="btn-settings"',
        'id="thumbs"',
        'id="slide-img"',
        'id="slide-frame"',
        'id="slide-media"',
        'id="script-pane"',
        'id="resize"',
        'id="chat-pane"',
        'id="settings-dialog"',
        'id="set-auth"',
        "choose_and_open",
        "ArrowDown",
        "ArrowUp",
    ):
        assert marker in html or marker in js
    assert "--right: 360px" in css
    assert "object-fit: contain" in css


def test_three_columns_have_visible_splitters():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert 'id="split-left"' in html
    assert 'id="split-right"' in html
    assert "--left:" in css
    assert "col-resize" in css
    assert "split-left" in js
    assert "split-right" in js
    assert "max-width: 560px" not in css
    assert 'id="resize"' in html
    assert "ns-resize" in css


def test_stage_wheel_switches_slides():
    from ppt_study.app import web_dir

    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    assert 'getElementById("stage")' in js
    assert '"wheel"' in js
    assert "stepSlide" in js
    assert "passive: false" in js


def test_stage_renders_embedded_slide_media():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert 'id="slide-frame"' in html
    assert 'id="slide-media"' in html
    assert "renderSlideMedia" in js
    assert "createElement(\"video\")" in js or "createElement('video')" in js
    assert ".slide-media" in css


def test_stage_clickable_slide_hyperlinks():
    from ppt_study.app import web_dir

    web = web_dir()
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert "renderSlideLinks" in js
    assert "open_url" in js
    assert "slide-link" in css
    chunk = js[js.index("function renderSlideMedia") : js.index("function renderSlideMedia") + 2400]
    assert "renderSlideLinks" in chunk


def test_stage_accepts_pptx_drag_drop():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    app = (web.parent / "src" / "ppt_study" / "app.py").read_text(encoding="utf-8")
    assert 'id="stage-drop-hint"' in html
    assert "drop-hover" in css
    assert "dragover" in js
    assert '"drop"' in js
    assert "open_from_path" in js
    assert "bind_file_drop" in app
    assert "events.loaded" in app
    assert "PDF" in html
    assert r"/\.(pptx?|pdf)$/i" in js
    assert "请拖入 PPT、PPTX 或 PDF 课件" in js


def test_bind_file_drop_opens_pptx_on_stage(tmp_path):
    from ppt_study.api import BridgeApi
    from ppt_study.app import bind_file_drop

    class FakeEvent:
        def __init__(self):
            self.handlers = []

        def __iadd__(self, item):
            self.handlers.append(item)
            return self

    class FakeEl:
        def __init__(self):
            self.bound = []

        def on(self, event, callback):
            self.bound.append((event, callback))

    el = FakeEl()
    loaded = FakeEvent()
    window = type(
        "W",
        (),
        {
            "events": type("E", (), {"loaded": loaded})(),
            "dom": type("D", (), {"get_element": staticmethod(lambda sel: el)})(),
        },
    )()
    api = BridgeApi()
    opened = []
    api.open_from_path = lambda path: opened.append(path) or {
        "ok": True,
        "pending": True,
        "error": "",
    }
    bind_file_drop(window, api)
    assert loaded.handlers
    loaded.handlers[0]()
    assert any(name == "drop" for name, _ in el.bound)
    drop = next(cb for name, cb in el.bound if name == "drop")
    callback = drop.callback if hasattr(drop, "callback") else drop
    ppt = tmp_path / "lec.pptx"
    callback(
        {
            "dataTransfer": {
                "files": [{"name": "lec.pptx", "pywebviewFullPath": str(ppt)}]
            }
        }
    )
    assert opened == [str(ppt)]


def test_open_deck_clears_chat_log():
    from ppt_study.app import web_dir

    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    assert "onDeckReady" in js
    assert "onIngestFailed" in js
    assert "onScriptChunk" in js
    assert "onScriptDone" in js
    assert "pending" in js
    assert "replaceChildren" in js or 'innerHTML = ""' in js


def test_settings_js_handles_save_and_test_errors():
    from ppt_study.app import web_dir

    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    assert "保存出错" in js
    assert "测试出错" in js
    assert "await saveSettings()" in js


def test_prepare_runtime_ui_copies_to_appdata(appdata_tmp):
    from ppt_study.app import prepare_runtime_ui
    from ppt_study.paths import APP_DIR_NAME

    dest = prepare_runtime_ui()
    assert dest == appdata_tmp / APP_DIR_NAME / "ui"
    assert (dest / "index.html").is_file()
    assert (dest / "app.js").is_file()
    assert (dest / "styles.css").is_file()
    assert (dest / "viz3d.js").is_file()
    assert (dest / "app-icon.png").is_file()
    assert (dest / "app-icon.ico").is_file()
    assert (dest / "vendor" / "katex" / "katex.min.js").is_file()


def test_script_pane_keeps_body_font_size():
    from ppt_study.app import web_dir

    css = (web_dir() / "styles.css").read_text(encoding="utf-8")
    assert "#script-body, #chat-log" in css
    assert "font-size: 14px" in css
    assert "1.12em" not in css
    assert "font-size: 1em !important" in css


def test_ui_renders_math_not_raw_markdown():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert "katex.min.js" in html
    assert "katex.min.css" in html
    assert "renderRichText" in js
    assert "katex.renderToString" in js
    assert 'output: "mathml"' in js
    assert (web / "vendor" / "katex" / "katex.min.js").is_file()
    assert (web / "vendor" / "katex" / "katex.min.css").is_file()


def test_ui_renders_markdown_tables():
    from ppt_study.app import web_dir

    web = web_dir()
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    start = js.index("function renderRichText")
    chunk = js[start : start + 2200]
    assert "extractTables" in js
    assert "renderMarkdownTable" in js
    assert "%%TABLE" in chunk or "%%TABLE" in js
    assert "<table" in js
    assert "md-table" in css
    assert "md-table-wrap" in css


def test_qa_ui_supports_visual_blocks():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    viz = (web / "viz3d.js").read_text(encoding="utf-8")
    assert "viz3d.js" in html
    assert "hydrateVisuals" in js
    assert "ensureVisualAnswer" in js
    assert "surface3d" in viz
    assert "showGradient" in viz


def test_viz_supports_animation_presets():
    from ppt_study.app import web_dir

    viz = (web_dir() / "viz3d.js").read_text(encoding="utf-8")
    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    assert 'type === "anim"' in viz
    assert "kernel_slide" in viz
    assert "gradient_walk" in viz
    assert "atan2" in viz
    assert "mountAnim" in viz
    chunk = js[js.index("function ensureVisualAnswer") : js.index("function ensureVisualAnswer") + 1600]
    assert "动画" in chunk
    assert '"type":"anim"' in chunk or 'type: "anim"' in chunk


def test_frontend_skips_auto_viz_unless_user_asks_to_draw():
    from ppt_study.app import web_dir

    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    start = js.index("function ensureVisualAnswer")
    chunk = js[start : start + 900]
    assert "梯度|" not in chunk
    assert "画图" in chunk


def test_qa_ui_supports_image_attachments():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert 'id="btn-attach"' in html
    assert 'id="chat-file"' in html
    assert "addAttachmentDataUrl" in js
    assert "clipboardData" in js
    assert "ask_question" in js


def test_qa_ui_applies_thumbs_after_deck_ready():
    from ppt_study.app import web_dir

    js = (web_dir() / "app.js").read_text(encoding="utf-8")
    assert "onThumbReady" in js
    assert "get_thumb" in js


def test_qa_ui_supports_clear_delete_and_retry():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert 'id="btn-clear-chat"' in html
    assert "clear_chat" in js
    assert "delete_turn" in js
    assert "retry_turn" in js
    assert "重新回答" in js
    assert "删除" in js


def test_ui_has_slide_favorite_marker():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert 'id="btn-fav-filter"' in html
    assert "toggle_favorite" in js
    assert "thumb-star" in js
    assert ".thumb-star" in css


def test_qa_ui_has_favorites_folder():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert 'id="btn-qa-favs"' in html
    assert 'id="qa-fav-dialog"' in html
    assert 'id="qa-fav-search"' in html
    assert "save_qa_favorite" in js
    assert "list_qa_favorites" in js
    assert "remove_qa_favorite" in js
    assert "收藏夹" in html
    assert "qa-fav" in css
    assert "展开回答" in js
    assert "qa-fav-preview" in js
    assert "previewPlainText" in js
    assert "scrollChatToTurn" in js
    assert "focusTurn" in js
    assert "qa-fav-preview" in css


def test_ui_has_generate_all_scripts():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    assert 'id="btn-script-all"' in html
    assert "生成全部讲稿" in html
    assert "generate_all_scripts" in js
    assert "onScriptBatchProgress" in js
    assert "onScriptBatchDone" in js
    assert "正在自动重试" in js
    assert "暂时失败" in js
    assert "正在生成第 " in js
    assert "active.join" in js


def test_ui_has_credits_wallet():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert 'id="btn-credits"' in html
    assert 'id="credits-dialog"' in html
    assert 'id="wechat-qr"' in html
    assert 'id="pay-qr"' in html
    assert "vendor/qrcode.min.js" in html
    assert 'id="credit-code"' in html
    assert 'id="ai-route"' in html
    assert "get_wallet" in js
    assert "hello_server" in js
    assert "registerWithServer" in js
    assert "redeem_credit_code" in js
    assert "create_wechat_pay" in js
    assert "query_wechat_pay" in js
    assert "report_telemetry" in js
    assert "mint_credit_code" not in js
    assert "ask_question(q, shots, selectedRoute(), webSearchOn())" in js
    assert "onQaChunk" in js
    assert "onQaDone" in js
    assert "paintQaStream" in js
    assert "sealStreamingRich" in js
    assert "renderRichText(sealStreamingRich" in js
    assert 'id="web-search"' in html
    assert "联网搜索" in html
    assert html.index('id="web-search"') < html.index('id="page-hint"')
    assert "webSearchOn" in js
    assert "wechat-qr" in css
    assert "pay-qr" in css
    assert "set-billing" not in html
    assert "credits-steps" in html
    assert "credits-qr-caption" in html
    assert "credits-rate" in html
    assert "credits-stats" not in html
    assert "credits-usage" not in html
    assert "兑换到账" in html
    assert "添加老师" not in html
    assert "告诉老师" not in html
    assert "1 积分 = 1 元 token" in html
    assert "充值金额与积分比例为 1:2" in html
    assert "微信商户扫码付款（备选）" in html
    assert html.index('id="wechat-qr"') < html.index('id="pay-qr"')
    assert html.index("credits-steps") < html.index("credits-rate")
    assert html.index("credits-rate") < html.index('id="wechat-qr"')
    assert "credits-close" in html
    assert "credits-close" in css
    assert "分享邀请码，双方各得2积分(可生成20页PPT讲稿)" in html
    assert 'id="my-invite-code"' in html
    assert 'id="invite-code"' in html
    assert "create_invite_code" in js
    assert "redeem_invite_code" in js
    assert "reportRun" in js
    assert "deck_open" in js
    assert "session_end" in js
    assert 'id="update-dialog"' in html
    assert "check_app_update" in js
    assert "apply_app_update" in js
    assert "quit_app" in js
    assert "FORCECLOSEAPPLICATIONS" not in js
    assert "覆盖安装" in js
    assert "正在下载安装包" in js
    assert "btn-check-update" in html
    assert "setInterval(() => checkAppUpdate()" in js
    assert (web / "wechat-qr.jpg").is_file()


def test_app_window_icon_files():
    from ppt_study.app import app_icon_path, web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    assert app_icon_path().is_file()
    assert (web / "app-icon.png").is_file()
    assert 'rel="icon"' in html
    assert "app-icon.png" in html
    assert "<title>PDReader</title>" in html
    assert "PPT 学习伴侣" not in html
    assert "PDF学习助手" not in html
    source = (web.parent / "src" / "ppt_study" / "app.py").read_text(encoding="utf-8")
    assert 'start_kw["icon"]' in source
    assert "SetCurrentProcessExplicitAppUserModelID" in source
    assert "PDReader" in source
    assert "PPT 学习伴侣" not in source






def test_runtime_ui_copies_wechat_qr(appdata_tmp):
    from ppt_study.app import prepare_runtime_ui

    dest = prepare_runtime_ui()
    assert (dest / "wechat-qr.jpg").is_file()
    assert (dest / "app-icon.png").is_file()
    assert (dest / "index.html").is_file()
    assert (dest / "vendor" / "qrcode.min.js").is_file()


def test_ui_has_theme_picker():
    from ppt_study.app import web_dir

    web = web_dir()
    html = (web / "index.html").read_text(encoding="utf-8")
    js = (web / "app.js").read_text(encoding="utf-8")
    css = (web / "styles.css").read_text(encoding="utf-8")
    assert 'id="theme-select"' in html
    assert 'id="set-theme"' in html
    assert 'value="system"' in html
    assert 'value="eye"' in html
    assert "applyTheme" in js
    assert "prefers-color-scheme" in js
    assert 'data-theme="dark"' in css or "html[data-theme=\"dark\"]" in css
    assert "html[data-theme=\"eye\"]" in css
