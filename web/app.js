const thumbs = document.getElementById("thumbs");
const slideImg = document.getElementById("slide-img");
const fileName = document.getElementById("file-name");
const ingestStatus = document.getElementById("ingest-status");
const scriptBody = document.getElementById("script-body");
const btnScript = document.getElementById("btn-script");
const btnScriptAll = document.getElementById("btn-script-all");
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const pageHint = document.getElementById("page-hint");
const settingsDialog = document.getElementById("settings-dialog");
let currentIndex = 1;
let slideCount = 0;
let pendingThumbs = {};
let lastSlides = [];
let starredSet = new Set();
let favOnly = false;
let sessionStartedAt = 0;
let sessionEnded = false;
let lastDeck = { name: "", key: "", slides: 0 };

function api() {
  return window.pywebview.api;
}

function selectedRoute() {
  const el = document.getElementById("ai-route");
  return el && el.value === "platform" ? "platform" : "byok";
}

function webSearchOn() {
  const el = document.getElementById("web-search");
  return !!(el && el.checked);
}

function applyBillingNotice(out) {
  if (!out) return;
  if (out.balance != null && out.balance !== "") {
    setCreditsBalance(out.balance);
  }
  refreshWallet();
}

function setCreditsBalance(value) {
  const text = value == null || value === "" ? "0" : String(value);
  const chip = document.getElementById("credits-balance");
  const line = document.getElementById("credits-balance-line");
  if (chip) chip.textContent = text;
  if (line) {
    const strong = line.querySelector("b");
    if (strong) strong.textContent = "¥" + text;
    else line.textContent = "当前余额 ¥" + text;
  }
}

function renderWallet(out) {
  if (!out || !out.ok) return;
  setCreditsBalance(out.balance);
}

async function refreshWallet() {
  try {
    const out = await api().get_wallet();
    if (out && out.ok) renderWallet(out);
    const route = document.getElementById("ai-route");
    if (route && Number(out && out.balance) > 0 && !route.dataset.touched) {
      route.value = "platform";
    }
  } catch (err) {
    /* wallet optional */
  }
}

function registerWithServer() {
  (async () => {
    for (let i = 0; i < 5; i++) {
      try {
        const out = await api().hello_server();
        if (out && out.ok) {
          if (out.balance != null && out.balance !== "") setCreditsBalance(out.balance);
          checkAppUpdate();
          return;
        }
      } catch (err) {
        /* retry */
      }
      await new Promise((resolve) => setTimeout(resolve, 8000));
    }
  })();
}

async function openCredits() {
  await refreshWallet();
  document.getElementById("credits-status").textContent = "";
  document.getElementById("invite-status").textContent = "";
  document.getElementById("credits-dialog").showModal();
  await loadInviteCode();
}

let payTimer = null;
let payOrderId = "";

function stopPayPoll() {
  if (payTimer) {
    clearInterval(payTimer);
    payTimer = null;
  }
}

function markPayAmount(amount) {
  document.querySelectorAll("[data-pay-amount]").forEach((btn) => {
    btn.classList.toggle("is-on", Number(btn.getAttribute("data-pay-amount")) === Number(amount));
  });
}

function drawPayQr(url) {
  const box = document.getElementById("pay-qr");
  if (!box) return;
  box.innerHTML = "";
  if (!url) return;
  if (typeof QRCode === "undefined") {
    box.textContent = url;
    return;
  }
  new QRCode(box, { text: url, width: 220, height: 220 });
}

async function pollWechatPay() {
  if (!payOrderId) return;
  const status = document.getElementById("credits-status");
  const hint = document.getElementById("pay-hint");
  try {
    const out = await api().query_wechat_pay(payOrderId);
    if (!out || !out.ok) return;
    if (out.status === "SUCCESS") {
      stopPayPoll();
      payOrderId = "";
      if (status) status.textContent = "已到账 ¥" + (out.amount || "");
      if (hint) hint.textContent = "付款成功，积分已到账";
      setCreditsBalance(out.balance);
    }
  } catch (err) {
    /* ignore poll errors */
  }
}

async function startWechatPay(amount) {
  stopPayPoll();
  markPayAmount(amount);
  const status = document.getElementById("credits-status");
  const hint = document.getElementById("pay-hint");
  if (status) status.textContent = "正在生成收款码…";
  if (hint) hint.textContent = "正在生成收款码…";
  drawPayQr("");
  try {
    const out = await api().create_wechat_pay(amount);
    if (!out || !out.ok) {
      const msg = (out && out.error) || "下单失败";
      if (status) status.textContent = msg;
      if (hint) hint.textContent = msg;
      return;
    }
    payOrderId = out.order_id || "";
    drawPayQr(out.code_url || "");
    if (status) status.textContent = "请用微信扫描付款 ¥" + (out.amount || amount);
    if (hint) hint.textContent = "请用微信扫描付款，到账后会自动刷新余额";
    if (payOrderId) payTimer = setInterval(pollWechatPay, 2000);
  } catch (err) {
    const msg = err && err.message ? err.message : String(err);
    if (status) status.textContent = msg;
    if (hint) hint.textContent = msg;
  }
}

async function loadInviteCode() {
  const el = document.getElementById("my-invite-code");
  if (!el) return;
  try {
    const out = await api().create_invite_code();
    if (out && out.ok && out.code) {
      el.textContent = out.code;
      return;
    }
    el.textContent = (out && out.error) || "生成失败";
  } catch (err) {
    el.textContent = err && err.message ? err.message : "生成失败";
  }
}

async function copyInviteCode() {
  const el = document.getElementById("my-invite-code");
  const status = document.getElementById("invite-status");
  const text = el && el.textContent ? el.textContent.trim() : "";
  if (!text || text.indexOf("失败") >= 0 || text.indexOf("生成中") >= 0) {
    status.textContent = "还没有邀请码";
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    status.textContent = "已复制邀请码";
  } catch (err) {
    status.textContent = "复制失败，请手动选中邀请码";
  }
}

async function redeemInvite() {
  const status = document.getElementById("invite-status");
  const code = document.getElementById("invite-code").value;
  try {
    const out = await api().redeem_invite_code(code);
    if (!out || !out.ok) {
      status.textContent = (out && out.error) || "领取失败";
      return;
    }
    status.textContent = "已到账 ¥" + out.credited;
    document.getElementById("invite-code").value = "";
    setCreditsBalance(out.balance);
  } catch (err) {
    status.textContent = err && err.message ? err.message : String(err);
  }
}

async function redeemCredits() {
  const status = document.getElementById("credits-status");
  const code = document.getElementById("credit-code").value;
  try {
    const out = await api().redeem_credit_code(code);
    if (!out || !out.ok) {
      status.textContent = (out && out.error) || "兑换失败";
      return;
    }
    status.textContent = "已到账 ¥" + out.credited;
    document.getElementById("credit-code").value = "";
    setCreditsBalance(out.balance);
  } catch (err) {
    status.textContent = err && err.message ? err.message : String(err);
  }
}

function reportTelemetry(item) {
  try {
    api().report_telemetry([
      Object.assign({ ts: Date.now() / 1000 }, item || {}),
    ]);
  } catch (err) {
    /* ignore */
  }
}

function reportFeature(feature, durationMs, kind) {
  reportTelemetry({
    kind: kind || "feature",
    feature: feature,
    duration_ms: durationMs || 0,
  });
}

function reportRun(kind, out, durationMs) {
  const ok = !!(out && out.ok);
  const billed = !!(out && out.billed);
  reportTelemetry({
    kind: kind,
    feature: kind === "script_run" ? "script" : "qa",
    duration_ms: durationMs || 0,
    slide_index: (out && out.slide_index) || currentIndex,
    ppt_name: lastDeck.name,
    ppt_key: lastDeck.key,
    prompt_tokens: (out && out.prompt_tokens) || 0,
    completion_tokens: (out && out.completion_tokens) || 0,
    route: selectedRoute(),
    ok: ok,
    count: ok && !billed,
  });
}

function reportSessionEnd() {
  if (sessionEnded) return;
  sessionEnded = true;
  reportTelemetry({
    kind: "session_end",
    feature: "app",
    started_at: sessionStartedAt,
    duration_ms: 0,
  });
}

function escapeHtml(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function extractRich(text) {
  const mathSlots = [];
  const media = [];
  const putMath = (src, display) => {
    const i = mathSlots.length;
    mathSlots.push({ src: String(src || "").trim(), display: !!display });
    return `%%MATH${i}%%`;
  };
  const putMedia = (src, kind) => {
    const i = media.length;
    media.push({ raw: String(src || "").trim(), kind: kind });
    return `%%MEDIA${i}%%`;
  };
  let t = String(text || "");
  t = t.replace(/```viz\s*([\s\S]*?)```/gi, (_, src) => putMedia(src, "viz"));
  t = t.replace(/```svg\s*([\s\S]*?)```/gi, (_, src) => putMedia(src, "svg"));
  t = t.replace(/```(?:latex|tex|math)\s*([\s\S]*?)```/gi, (_, src) => putMath(src, true));
  t = t.replace(/\\\[([\s\S]*?)\\\]/g, (_, src) => putMath(src, true));
  t = t.replace(/\$\$([\s\S]*?)\$\$/g, (_, src) => putMath(src, true));
  t = t.replace(/\\\(([\s\S]*?)\\\)/g, (_, src) => putMath(src, false));
  t = t.replace(/\$([^$\n]+?)\$/g, (_, src) => putMath(src, false));
  return { text: t, mathSlots: mathSlots, media: media };
}

function renderMath(src, display) {
  if (window.katex) {
    try {
      return window.katex.renderToString(src, {
        displayMode: display,
        throwOnError: false,
        output: "mathml",
      });
    } catch (err) {
      return escapeHtml(src);
    }
  }
  return "<code>" + escapeHtml(src) + "</code>";
}

function extractTables(text) {
  const tables = [];
  let raw = String(text || "").replace(
    /```(?:markdown|md|text)?\s*\n([\s\S]*?)```/gi,
    (all, inner) => {
      const lines = String(inner || "").trim().split("\n");
      if (
        lines.length >= 2 &&
        lines[0].trim().startsWith("|") &&
        /^\s*\|[\s:|-]+\|\s*$/.test(lines[1].trim())
      ) {
        return inner.trim();
      }
      return all;
    }
  );
  const lines = raw.split("\n");
  const out = [];
  const isRow = (line) => {
    const t = String(line || "").trim();
    return t.startsWith("|") && t.indexOf("|", 1) >= 0;
  };
  const isSep = (line) => {
    const t = String(line || "").trim();
    if (!isRow(t)) return false;
    let inner = t;
    if (inner.startsWith("|")) inner = inner.slice(1);
    if (inner.endsWith("|")) inner = inner.slice(0, -1);
    const cells = inner.split("|");
    return cells.length > 0 && cells.every((c) => /^\s*:?-{2,}:?\s*$/.test(c));
  };
  let i = 0;
  while (i < lines.length) {
    if (i + 1 < lines.length && isRow(lines[i]) && isSep(lines[i + 1])) {
      const block = [lines[i], lines[i + 1]];
      i += 2;
      while (i < lines.length && isRow(lines[i]) && !isSep(lines[i])) {
        block.push(lines[i]);
        i += 1;
      }
      const idx = tables.length;
      tables.push(block);
      out.push("%%TABLE" + idx + "%%");
      continue;
    }
    out.push(lines[i]);
    i += 1;
  }
  return { text: out.join("\n"), tables: tables };
}

function splitTableRow(line) {
  let t = String(line || "").trim();
  if (t.startsWith("|")) t = t.slice(1);
  if (t.endsWith("|")) t = t.slice(0, -1);
  return t.split("|").map((c) => c.trim());
}

function formatTableCell(text) {
  return escapeHtml(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdownTable(rows) {
  if (!rows || rows.length < 2) return "";
  const head = splitTableRow(rows[0]);
  if (!head.length) return "";
  const body = rows.slice(2).map(splitTableRow);
  let html = '<div class="md-table-wrap"><table class="md-table"><thead><tr>';
  head.forEach((cell) => {
    html += "<th>" + formatTableCell(cell) + "</th>";
  });
  html += "</tr></thead><tbody>";
  body.forEach((cells) => {
    html += "<tr>";
    for (let i = 0; i < head.length; i++) {
      html += "<td>" + formatTableCell(cells[i] || "") + "</td>";
    }
    html += "</tr>";
  });
  html += "</tbody></table></div>";
  return html;
}

function sealStreamingRich(text) {
  let t = String(text || "");
  const lastFence = t.lastIndexOf("```");
  if (lastFence >= 0) {
    const after = t.slice(lastFence + 3);
    if (after.indexOf("```") < 0) {
      const lang = after.split(/\r?\n/, 1)[0].trim().toLowerCase();
      if (lang === "viz" || lang === "svg") {
        t = t.slice(0, lastFence);
      } else {
        t += "\n```";
      }
    }
  }
  if ((t.match(/\\\[/g) || []).length > (t.match(/\\\]/g) || []).length) t += "\\]";
  if (((t.match(/\$\$/g) || []).length % 2) === 1) t += "$$";
  if ((t.match(/\\\(/g) || []).length > (t.match(/\\\)/g) || []).length) t += "\\)";
  return t;
}

function renderRichText(text) {
  const extracted = extractRich(text);
  const tabled = extractTables(extracted.text);
  let html = escapeHtml(tabled.text);
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|\n)#{1,3} (.+)/g, "$1<h4>$2</h4>");
  html = html.replace(/(^|\n)[-*] (.+)/g, "$1<li>$2</li>");
  html = html.replace(/(?:<li>.*?<\/li>\s*)+/g, (block) => "<ul>" + block + "</ul>");
  html = html.replace(/\n/g, "<br>");
  html = html.replace(/%%TABLE(\d+)%%/g, (_, idx) => {
    const rows = tabled.tables[Number(idx)];
    return rows ? renderMarkdownTable(rows) : "";
  });
  html = html.replace(/%%MATH(\d+)%%/g, (_, idx) => {
    const item = extracted.mathSlots[Number(idx)];
    if (!item) return "";
    return renderMath(item.src, item.display);
  });
  html = html.replace(/%%MEDIA(\d+)%%/g, (_, idx) => {
    const item = extracted.media[Number(idx)];
    if (!item) return "";
    return (
      '<div class="viz-card" data-kind="' +
      escapeHtml(item.kind) +
      '" data-spec="' +
      encodeURIComponent(item.raw) +
      '"></div>'
    );
  });
  return html;
}

function hydrateVisuals(root) {
  if (!root || !window.Viz3D) return;
  root.querySelectorAll(".viz-card:not([data-ready])").forEach((el) => {
    el.setAttribute("data-ready", "1");
    let raw = el.getAttribute("data-spec") || "";
    try {
      raw = decodeURIComponent(raw);
    } catch (err) {
      /* keep raw */
    }
    window.Viz3D.mount(el, raw, el.getAttribute("data-kind") || "viz");
  });
}

function setScriptHtml(text, empty) {
  scriptBody.classList.toggle("empty", !!empty);
  if (empty) {
    scriptBody.textContent = text;
    return;
  }
  scriptBody.innerHTML = renderRichText(text);
  hydrateVisuals(scriptBody);
}

window.onIngestProgress = function (done, total) {
  ingestStatus.textContent = `正在读取课件 ${done}/${total}`;
};

window.onIngestFailed = function (error) {
  ingestStatus.textContent = "";
  addMsg("error", error);
};

window.onDeckReady = function (out) {
  ingestStatus.textContent = "";
  applyDeck(out);
};

window.onThumbReady = function (item) {
  if (!item || item.index == null) return;
  pendingThumbs[item.index] = item.thumb_url || "";
  const img = document.querySelector('#thumbs .thumb[data-index="' + item.index + '"] img');
  if (img && item.thumb_url) img.src = item.thumb_url;
};

let chatTurns = [];
let chatBusy = false;

function applyDeck(out) {
  pendingThumbs = {};
  lastSlides = out.deck.slides || [];
  starredSet = new Set(lastSlides.filter((s) => s.starred).map((s) => s.index));
  favOnly = false;
  const filterBtn = document.getElementById("btn-fav-filter");
  if (filterBtn) filterBtn.classList.remove("on");
  chatTurns = [];
  chatBusy = false;
  renderChat();
  fileName.textContent = out.deck.file_name;
  slideCount = out.deck.slides.length;
  lastDeck = {
    name: out.deck.file_name || "",
    key: String(out.deck.file_name || "unknown"),
    slides: Number(out.deck.slide_count || slideCount || 0),
  };
  reportTelemetry({
    kind: "deck_open",
    feature: "ppt",
    ppt_name: lastDeck.name,
    ppt_key: lastDeck.key,
    slide_count: lastDeck.slides,
  });
  currentIndex = 1;
  renderThumbs(lastSlides);
  selectSlide(1);
  fillMissingThumbs();
  const stageEl = document.getElementById("stage");
  if (stageEl) stageEl.classList.add("has-slide");
}

let pendingImages = [];
const MAX_ATTACH = 3;

function addMsg(role, text, images) {
  if (role === "error") {
    const div = document.createElement("div");
    div.className = "msg error";
    div.textContent = text;
    chatLog.appendChild(div);
    return;
  }
  const div = document.createElement("div");
  div.className = "msg " + role;
  if (role === "assistant") {
    div.innerHTML = "<span class=\"msg-role\">AI：</span>" + renderRichText(text);
    hydrateVisuals(div);
  } else {
    const label = document.createElement("div");
    label.textContent = (role === "user" ? "我：" : "") + (text || (images && images.length ? "（截图）" : ""));
    div.appendChild(label);
    if (images && images.length) {
      const row = document.createElement("div");
      row.className = "msg-thumbs";
      images.forEach((src) => {
        const img = document.createElement("img");
        img.src = src;
        img.alt = "截图";
        row.appendChild(img);
      });
      div.appendChild(row);
    }
  }
  chatLog.appendChild(div);
}

function scrollChatToTurn(idx) {
  const el = chatLog.querySelector('[data-turn="' + idx + '"]');
  if (!el) return;
  chatLog.scrollTop = Math.max(0, el.offsetTop);
}

function renderChat(opts) {
  const focusTurn = opts && typeof opts.focusTurn === "number" ? opts.focusTurn : null;
  const prevTop = chatLog.scrollTop;
  chatLog.replaceChildren();
  chatTurns.forEach((turn, idx) => {
    const wrap = document.createElement("div");
    wrap.className = "chat-turn";
    wrap.dataset.turn = String(idx);

    const user = document.createElement("div");
    user.className = "msg user";
    const label = document.createElement("div");
    label.textContent = "我：" + (turn.question || (turn.images && turn.images.length ? "（截图）" : ""));
    user.appendChild(label);
    if (turn.images && turn.images.length) {
      const row = document.createElement("div");
      row.className = "msg-thumbs";
      turn.images.forEach((src) => {
        const img = document.createElement("img");
        img.src = src;
        img.alt = "截图";
        row.appendChild(img);
      });
      user.appendChild(row);
    }
    wrap.appendChild(user);

    const bot = document.createElement("div");
    bot.className = "msg assistant";
    if (turn.pending && !turn.answer) {
      bot.textContent = "AI：正在回答…";
    } else {
      bot.innerHTML = "<span class=\"msg-role\">AI：</span>" + renderRichText(turn.answer || "");
      hydrateVisuals(bot);
    }
    wrap.appendChild(bot);

    if (turn.error) {
      const err = document.createElement("div");
      err.className = "msg error";
      err.textContent = turn.error;
      wrap.appendChild(err);
    }

    const actions = document.createElement("div");
    actions.className = "turn-actions";
    const star = document.createElement("button");
    star.type = "button";
    star.textContent = turn.favId ? "已收藏" : "收藏";
    star.disabled = !!turn.pending || chatBusy || !turn.answer;
    star.addEventListener("click", () => toggleQaFavorite(idx));
    const retry = document.createElement("button");
    retry.type = "button";
    retry.textContent = "重新回答";
    retry.disabled = !!turn.pending || chatBusy;
    retry.addEventListener("click", () => retryTurn(idx));
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "删除";
    del.disabled = !!turn.pending || chatBusy;
    del.addEventListener("click", () => deleteTurn(idx));
    actions.appendChild(star);
    actions.appendChild(retry);
    actions.appendChild(del);
    wrap.appendChild(actions);
    chatLog.appendChild(wrap);
  });
  if (focusTurn != null && chatTurns[focusTurn]) {
    scrollChatToTurn(focusTurn);
    return;
  }
  chatLog.scrollTop = prevTop;
}

function renderAttachChips() {
  const box = document.getElementById("chat-attach");
  box.innerHTML = "";
  pendingImages.forEach((src, idx) => {
    const chip = document.createElement("div");
    chip.className = "attach-chip";
    const img = document.createElement("img");
    img.src = src;
    img.alt = "待发送截图";
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = "×";
    del.addEventListener("click", () => {
      pendingImages.splice(idx, 1);
      renderAttachChips();
    });
    chip.appendChild(img);
    chip.appendChild(del);
    box.appendChild(chip);
  });
}

function addAttachmentDataUrl(url) {
  if (!url || !String(url).startsWith("data:image")) return;
  if (pendingImages.length >= MAX_ATTACH) return;
  pendingImages.push(url);
  renderAttachChips();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const max = 1280;
      let w = img.width;
      let h = img.height;
      const scale = Math.min(1, max / Math.max(w, h));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round(w * scale));
      canvas.height = Math.max(1, Math.round(h * scale));
      canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(img.src);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
    };
    img.onerror = () => reject(new Error("无法读取图片"));
    img.src = URL.createObjectURL(file);
  });
}

async function addAttachmentFile(file) {
  if (!file || !file.type || file.type.indexOf("image/") !== 0) return;
  try {
    const url = await fileToDataUrl(file);
    addAttachmentDataUrl(url);
  } catch (err) {
    addMsg("error", err && err.message ? err.message : "添加截图失败");
  }
}

function renderThumbs(slides) {
  const source = slides || lastSlides;
  const visible = favOnly ? source.filter((s) => starredSet.has(s.index)) : source;
  thumbs.innerHTML = "";
  visible.forEach((s) => {
    const starred = starredSet.has(s.index);
    const wrap = document.createElement("div");
    wrap.className = "thumb" + (s.index === currentIndex ? " active" : "") + (starred ? " starred" : "");
    wrap.dataset.index = String(s.index);
    const src = s.thumb_url || pendingThumbs[s.index] || "";
    wrap.innerHTML =
      `<button class="thumb-star${starred ? " on" : ""}" type="button" title="收藏/取消收藏">★</button>` +
      `<img alt="第${s.index}页" src="${src}" /><span>${s.index}</span>`;
    wrap.querySelector(".thumb-star").addEventListener("click", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      toggleFavorite(s.index);
    });
    wrap.addEventListener("click", () => selectSlide(s.index));
    thumbs.appendChild(wrap);
  });
}

async function toggleFavorite(index) {
  try {
    const out = await api().toggle_favorite(index);
    if (!out || !out.ok) return;
    if (out.starred) starredSet.add(index);
    else starredSet.delete(index);
    const slide = lastSlides.find((s) => s.index === index);
    if (slide) slide.starred = !!out.starred;
    renderThumbs(lastSlides);
  } catch (err) {
    addMsg("error", err && err.message ? err.message : "收藏失败");
  }
}

function toggleFavFilter() {
  favOnly = !favOnly;
  document.getElementById("btn-fav-filter").classList.toggle("on", favOnly);
  renderThumbs(lastSlides);
}

async function fillMissingThumbs() {
  const nodes = document.querySelectorAll("#thumbs .thumb");
  for (const btn of nodes) {
    const img = btn.querySelector("img");
    if (!img || img.getAttribute("src")) continue;
    try {
      const out = await api().get_thumb(btn.dataset.index);
      if (out && out.ok && out.thumb_url) {
        pendingThumbs[out.index] = out.thumb_url;
        img.src = out.thumb_url;
      }
    } catch (err) {
      /* keep placeholder */
    }
  }
}

function renderSlideLinks(links) {
  const box = document.getElementById("slide-media");
  if (!box) return;
  (links || []).forEach((item) => {
    if (!item || !item.url) return;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "slide-link";
    btn.title = item.url;
    btn.style.left = item.left * 100 + "%";
    btn.style.top = item.top * 100 + "%";
    btn.style.width = item.width * 100 + "%";
    btn.style.height = item.height * 100 + "%";
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      try {
        const out = await api().open_url(item.url);
        if (out && !out.ok) addMsg("error", out.error || "无法打开链接");
      } catch (err) {
        addMsg("error", err && err.message ? err.message : "无法打开链接");
      }
    });
    box.appendChild(btn);
  });
}

function renderSlideMedia(items, links) {
  const box = document.getElementById("slide-media");
  if (!box) return;
  box.querySelectorAll("video").forEach((v) => {
    try {
      v.pause();
    } catch (err) {
      /* ignore */
    }
  });
  box.replaceChildren();
  (items || []).forEach((item) => {
    const isGif = item.kind === "gif";
    const el = isGif ? document.createElement("img") : document.createElement("video");
    el.className = "slide-media";
    el.src = item.src;
    el.style.left = item.left * 100 + "%";
    el.style.top = item.top * 100 + "%";
    el.style.width = item.width * 100 + "%";
    el.style.height = item.height * 100 + "%";
    if (!isGif) {
      el.setAttribute("controls", "");
      el.setAttribute("playsinline", "");
      el.setAttribute("preload", "metadata");
      el.setAttribute("controlslist", "nodownload");
    }
    el.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    box.appendChild(el);
  });
  renderSlideLinks(links);
}

async function selectSlide(index) {
  const out = await api().select_slide(index);
  if (!out.ok) return;
  currentIndex = out.slide.index;
  pageHint.textContent = "当前第 " + currentIndex + " 页";
  slideImg.src = out.slide.display_url || "";
  renderSlideMedia(out.slide.media, out.slide.links);
  if (out.slide.script) {
    setScriptHtml(out.slide.script, false);
  } else {
    setScriptHtml("本页还没有讲稿。", true);
  }
  document.querySelectorAll(".thumb").forEach((el) => {
    el.classList.toggle("active", Number(el.dataset.index) === currentIndex);
  });
  const active = document.querySelector(".thumb.active");
  if (active) active.scrollIntoView({ block: "nearest" });
}

function stepSlide(delta) {
  if (!slideCount) return;
  const next = Math.min(slideCount, Math.max(1, currentIndex + delta));
  if (next === currentIndex) return;
  currentIndex = next;
  selectSlide(next);
}

async function openDeckFromPath(path) {
  ingestStatus.textContent = "正在读取课件…";
  try {
    const out = await api().open_from_path(path);
    if (!out.ok) {
      ingestStatus.textContent = "";
      addMsg("error", out.error || "打开失败");
    }
  } catch (err) {
    ingestStatus.textContent = "";
    addMsg("error", err && err.message ? err.message : String(err));
  }
}

async function openDeck() {
  ingestStatus.textContent = "正在读取课件…";
  const out = await api().choose_and_open();
  if (!out.ok) {
    ingestStatus.textContent = "";
    if (out.error !== "已取消") addMsg("error", out.error);
    return;
  }
  if (out.pending) {
    return;
  }
  ingestStatus.textContent = "";
  applyDeck(out);
}

let scriptJobAt = 0;

function setScriptBusy(busy) {
  btnScript.disabled = busy;
  if (btnScriptAll) btnScriptAll.disabled = busy;
}

function finishScriptJob(out) {
  setScriptBusy(false);
  if (!out) return;
  const sameSlide = !out.slide_index || out.slide_index === currentIndex;
  if (sameSlide) {
    if (!out.ok) setScriptHtml(out.error || "生成失败", true);
    else {
      setScriptHtml(out.script || out.text || "", false);
      applyBillingNotice(out);
    }
  }
  reportRun("script_run", out, Date.now() - scriptJobAt);
}

window.onScriptChunk = function (payload) {
  if (!payload || !payload.text) return;
  if (payload.slide_index && payload.slide_index !== currentIndex) return;
  scriptBody.classList.remove("empty");
  scriptBody.innerHTML = renderRichText(sealStreamingRich(payload.text));
};

window.onScriptDone = function (out) {
  finishScriptJob(out);
};

function activeQaIndex() {
  for (let i = chatTurns.length - 1; i >= 0; i--) {
    if (chatTurns[i].streaming) return i;
  }
  return -1;
}

let qaPaintFrame = 0;
let qaPaintJob = null;

function paintQaStream(idx, text) {
  qaPaintJob = { idx: idx, text: text };
  if (qaPaintFrame) return;
  qaPaintFrame = requestAnimationFrame(function () {
    qaPaintFrame = 0;
    const job = qaPaintJob;
    qaPaintJob = null;
    if (!job) return;
    const bot = chatLog.querySelector('[data-turn="' + job.idx + '"] .msg.assistant');
    if (!bot) return;
    bot.innerHTML = "<span class=\"msg-role\">AI：</span>" + renderRichText(sealStreamingRich(job.text));
  });
}

window.onQaChunk = function (payload) {
  const idx = activeQaIndex();
  if (idx < 0 || !payload || !payload.text) return;
  const turn = chatTurns[idx];
  turn.answer = payload.text;
  turn.pending = false;
  paintQaStream(idx, turn.answer);
};

window.onQaDone = function (out) {
  const idx = activeQaIndex();
  const turn = idx >= 0 ? chatTurns[idx] : null;
  if (turn) {
    turn.pending = false;
    turn.streaming = false;
    if (!out || !out.ok) {
      if (!turn.answer) {
        chatTurns.splice(idx, 1);
        addMsg("error", (out && out.error) || "回答失败");
      } else {
        turn.error = (out && out.error) || "回答失败";
      }
    } else {
      turn.answer = ensureVisualAnswer(turn.question, out.answer || turn.answer || "");
      turn.error = "";
      applyBillingNotice(out);
    }
  }
  chatBusy = false;
  renderChat({ focusTurn: Math.max(0, idx) });
  reportRun("qa_run", out, Date.now() - ((turn && turn.startedAt) || Date.now()));
};

window.onScriptBatchProgress = function (payload) {
  if (!payload) return;
  const total = payload.total || 0;
  const done = payload.done || payload.current || 0;
  const active = Array.isArray(payload.active) ? payload.active : [];
  const page = payload.slide_index || payload.current || 0;
  if (payload.status === "running") {
    scriptBody.classList.remove("empty");
    if (active.length > 1) {
      scriptBody.textContent =
        "正在生成第 " + active.join("、") + " 页（已完成 " + done + "/" + total + "）…";
    } else {
      scriptBody.textContent = "正在生成第 " + page + " 页（已完成 " + done + "/" + total + "）…";
    }
    return;
  }
  if (payload.status === "retrying") {
    scriptBody.classList.remove("empty");
    scriptBody.textContent = "第 " + page + " 页暂时失败，正在自动重试…";
    return;
  }
  if (payload.status === "ok" && payload.slide_index === currentIndex && payload.script) {
    setScriptHtml(payload.script, false);
  }
};

window.onScriptBatchDone = function (out) {
  setScriptBusy(false);
  if (!out) return;
  const generated = Number(out.generated || 0);
  const skipped = Number(out.skipped || 0);
  const failed = Number(out.failed || 0);
  if (!out.ok) {
    setScriptHtml(
      "全部讲稿未完成：已生成 " +
        generated +
        " 页" +
        (failed ? "，失败 " + failed + " 页" : "") +
        "。" +
        (out.error || "生成失败"),
      true
    );
    applyBillingNotice(out);
    reportRun("script_run", out, Date.now() - scriptJobAt);
    return;
  }
  ingestStatus.textContent =
    "全部讲稿完成：新生成 " + generated + " 页，跳过 " + skipped + " 页";
  if (currentIndex) selectSlide(currentIndex);
  applyBillingNotice(out);
  reportRun("script_run", out, Date.now() - scriptJobAt);
};

async function generateScript() {
  setScriptBusy(true);
  scriptBody.classList.remove("empty");
  scriptBody.textContent = "正在生成…";
  scriptJobAt = Date.now();
  try {
    const out = await api().generate_script(selectedRoute());
    if (!out || !out.ok) {
      finishScriptJob(out || { ok: false, error: "生成失败" });
      return;
    }
    if (out.pending) return;
    finishScriptJob(out);
  } catch (err) {
    finishScriptJob({
      ok: false,
      error: err && err.message ? err.message : String(err),
    });
  }
}

async function generateAllScripts() {
  if (!slideCount) {
    addMsg("error", "请先打开课件");
    return;
  }
  setScriptBusy(true);
  scriptBody.classList.remove("empty");
  scriptBody.textContent = "正在生成全部讲稿…";
  ingestStatus.textContent = "正在生成全部讲稿…";
  scriptJobAt = Date.now();
  try {
    const out = await api().generate_all_scripts(selectedRoute());
    if (!out || !out.ok) {
      window.onScriptBatchDone(out || { ok: false, error: "生成失败" });
      return;
    }
    if (out.pending) return;
    window.onScriptBatchDone(out);
  } catch (err) {
    window.onScriptBatchDone({
      ok: false,
      error: err && err.message ? err.message : String(err),
    });
  }
}

function pickAnimPreset(q) {
  if (/(高斯|模糊|blur|gaussian)/i.test(q)) {
    return { preset: "gaussian_blur", title: "高斯模糊：核在滑动" };
  }
  if (/(采样|插值|resample|下采样|上采样)/i.test(q)) {
    return { preset: "resample", title: "采样与插值" };
  }
  if (/(atan2|方位角)/i.test(q)) {
    return { preset: "atan2", title: "atan2 方位角" };
  }
  if (/(边缘|edge|sobel)/i.test(q)) {
    return { preset: "edge_detect", title: "边缘检测" };
  }
  if (/(梯度|gradient)/i.test(q)) {
    return { preset: "gradient_walk", title: "沿梯度走" };
  }
  return { preset: "kernel_slide", title: "卷积：核在滑动" };
}

function ensureVisualAnswer(question, answer) {
  const text = String(answer || "");
  if (/```viz/i.test(text) || /```svg/i.test(text)) return text;
  const q = String(question || "");
  const wantsAnim = /(动画|演示|动起来)/.test(q);
  if (wantsAnim) {
    const picked = pickAnimPreset(q);
    const spec = { type: "anim", title: picked.title, preset: picked.preset };
    return text + "\n\n```viz\n" + JSON.stringify(spec) + "\n```";
  }
  if (!/(画图|示意图|三维|可视化|3d|3D|强度曲面)/i.test(q)) return text;
  let preset = "ramp_diag";
  if (/(水平|∂x|\\partial x|x\s*方向)/i.test(q)) preset = "step_x";
  else if (/(垂直|∂y|\\partial y|y\s*方向)/i.test(q)) preset = "step_y";
  else if (/(角点|对角|corner)/i.test(q)) preset = "corner";
  else if (/(高斯|gaussian|鼓包)/i.test(q)) preset = "gaussian";
  const spec = {
    type: "surface3d",
    title: "强度曲面与梯度",
    preset: preset,
    showGradient: true,
    resolution: 24,
  };
  return text + "\n\n```viz\n" + JSON.stringify(spec) + "\n```";
}

async function sendQuestion() {
  if (chatBusy) return;
  const q = chatInput.value.trim();
  const shots = pendingImages.slice();
  if (!q && !shots.length) return;
  chatInput.value = "";
  pendingImages = [];
  renderAttachChips();
  const turn = { question: q, images: shots, answer: "", pending: true, streaming: true, error: "" };
  chatTurns.push(turn);
  chatBusy = true;
  renderChat({ focusTurn: chatTurns.length - 1 });
  let notice = "";
  const t0 = Date.now();
  let out = null;
  try {
    out = await api().ask_question(q, shots, selectedRoute(), webSearchOn());
    if (out && out.pending) {
      turn.startedAt = t0;
      return;
    }
    turn.pending = false;
    turn.streaming = false;
    if (!out.ok) {
      chatTurns.pop();
      notice = out.error;
      return;
    }
    turn.answer = ensureVisualAnswer(q, out.answer);
    turn.error = "";
    applyBillingNotice(out);
  } catch (err) {
    chatTurns.pop();
    notice = err && err.message ? err.message : String(err);
  } finally {
    if (out && out.pending) return;
    chatBusy = false;
    renderChat({ focusTurn: Math.max(0, chatTurns.length - 1) });
    if (notice) addMsg("error", notice);
    reportRun("qa_run", out, Date.now() - t0);
  }
}

async function clearChat() {
  if (chatBusy) return;
  if (!chatTurns.length) return;
  const out = await api().clear_chat();
  if (!out.ok) {
    addMsg("error", out.error || "清空失败");
    return;
  }
  chatTurns = [];
  renderChat();
}

async function deleteTurn(idx) {
  if (chatBusy) return;
  const turn = chatTurns[idx];
  if (!turn || turn.pending) return;
  chatBusy = true;
  renderChat();
  let notice = "";
  try {
    const out = await api().delete_turn(idx);
    if (!out.ok) {
      notice = out.error || "删除失败";
      return;
    }
    chatTurns.splice(idx, 1);
  } catch (err) {
    notice = err && err.message ? err.message : String(err);
  } finally {
    chatBusy = false;
    renderChat();
    if (notice) addMsg("error", notice);
  }
}

async function retryTurn(idx) {
  if (chatBusy) return;
  const turn = chatTurns[idx];
  if (!turn || turn.pending) return;
  chatBusy = true;
  turn.pending = true;
  turn.streaming = true;
  turn.error = "";
  renderChat({ focusTurn: idx });
  const t0 = Date.now();
  let out = null;
  try {
    out = await api().retry_turn(idx, selectedRoute(), webSearchOn());
    if (out && out.pending) {
      turn.startedAt = t0;
      return;
    }
    turn.pending = false;
    turn.streaming = false;
    if (!out.ok) {
      turn.error = out.error || "重新回答失败";
      return;
    }
    turn.answer = ensureVisualAnswer(turn.question, out.answer);
    turn.error = "";
    turn.favId = "";
    applyBillingNotice(out);
  } catch (err) {
    turn.pending = false;
    turn.streaming = false;
    turn.error = err && err.message ? err.message : String(err);
  } finally {
    if (out && out.pending) return;
    chatBusy = false;
    renderChat({ focusTurn: idx });
    reportRun("qa_run", out, Date.now() - t0);
  }
}

async function toggleQaFavorite(idx) {
  const turn = chatTurns[idx];
  if (!turn || turn.pending || !turn.answer) return;
  try {
    if (turn.favId) {
      const out = await api().remove_qa_favorite(turn.favId);
      if (!out || !out.ok) {
        addMsg("error", (out && out.error) || "取消收藏失败");
        return;
      }
      turn.favId = "";
      renderChat();
      return;
    }
    const out = await api().save_qa_favorite({
      question: turn.question || "",
      answer: turn.answer || "",
      file_name: fileName.textContent || "",
      slide_index: currentIndex,
    });
    if (!out || !out.ok) {
      addMsg("error", (out && out.error) || "收藏失败");
      return;
    }
    turn.favId = out.item && out.item.id ? out.item.id : "";
    renderChat();
  } catch (err) {
    addMsg("error", err && err.message ? err.message : "收藏失败");
  }
}

function previewPlainText(text, max) {
  const plain = String(text || "")
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/\$\$[\s\S]*?\$\$/g, " ")
    .replace(/\$[^$]+\$/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const limit = Number(max) || 90;
  if (plain.length <= limit) return plain || "（无文字）";
  return plain.slice(0, limit) + "…";
}

async function renderQaFavList(query) {
  const box = document.getElementById("qa-fav-list");
  if (!box) return;
  try {
    const out = await api().list_qa_favorites(query || "");
    const items = (out && out.items) || [];
    box.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "qa-fav-empty";
      empty.textContent = query
        ? "没有匹配的收藏"
        : "还没有收藏问答。可在回答下方点「收藏」。";
      box.appendChild(empty);
      return;
    }
    items.forEach((item) => {
      const card = document.createElement("article");
      card.className = "qa-fav-item";
      const meta = document.createElement("div");
      meta.className = "qa-fav-meta";
      const bits = [];
      if (item.file_name) bits.push(item.file_name);
      if (item.slide_index) bits.push("第" + item.slide_index + "页");
      meta.textContent = bits.join(" · ") || "问答收藏";
      const q = document.createElement("div");
      q.className = "qa-fav-q";
      q.textContent = "问：" + (item.question || "（无文字）");
      const preview = document.createElement("div");
      preview.className = "qa-fav-preview";
      preview.textContent = "答：" + previewPlainText(item.answer || "", 90);
      const body = document.createElement("div");
      body.className = "qa-fav-a";
      body.hidden = true;
      const actions = document.createElement("div");
      actions.className = "qa-fav-actions";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.textContent = "展开回答";
      toggle.addEventListener("click", () => {
        const opening = body.hidden;
        if (opening && !body.dataset.ready) {
          body.innerHTML = renderRichText(item.answer || "");
          hydrateVisuals(body);
          body.dataset.ready = "1";
        }
        body.hidden = !opening;
        preview.hidden = opening;
        card.classList.toggle("is-open", opening);
        toggle.textContent = opening ? "收起回答" : "展开回答";
      });
      const del = document.createElement("button");
      del.type = "button";
      del.textContent = "取消收藏";
      del.addEventListener("click", async () => {
        await api().remove_qa_favorite(item.id);
        chatTurns.forEach((turn) => {
          if (turn.favId === item.id) turn.favId = "";
        });
        renderChat();
        const search = document.getElementById("qa-fav-search");
        renderQaFavList(search ? search.value : "");
      });
      actions.append(toggle, del);
      card.append(meta, q, preview, body, actions);
      box.appendChild(card);
    });
  } catch (err) {
    box.textContent = err && err.message ? err.message : "无法读取收藏夹";
  }
}

function openQaFavs() {
  const dlg = document.getElementById("qa-fav-dialog");
  const search = document.getElementById("qa-fav-search");
  if (search) search.value = "";
  renderQaFavList("");
  if (dlg && dlg.showModal) dlg.showModal();
}

let themePref = "light";

function resolvedTheme(pref) {
  if (pref === "system") {
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  if (pref === "dark" || pref === "eye") return pref;
  return "light";
}

function applyTheme(pref) {
  themePref = pref === "dark" || pref === "eye" || pref === "system" ? pref : "light";
  document.documentElement.setAttribute("data-theme", resolvedTheme(themePref));
  const header = document.getElementById("theme-select");
  const setting = document.getElementById("set-theme");
  if (header) header.value = themePref;
  if (setting) setting.value = themePref;
}

async function persistTheme(pref) {
  applyTheme(pref);
  try {
    await api().save_settings({ theme: themePref });
  } catch (err) {
    /* keep local theme */
  }
}

async function openSettings() {
  const s = await api().get_settings();
  document.getElementById("set-base").value = s.base_url || "";
  document.getElementById("set-model").value = s.model || "";
  document.getElementById("set-auth").value = s.auth_mode;
  document.getElementById("set-theme").value = s.theme || "light";
  applyTheme(s.theme || "light");
  document.getElementById("set-key").value = "";
  document.getElementById("set-status").textContent = s.api_key_set ? "已保存密钥" : "尚未填写密钥";
  document.getElementById("set-update-status").textContent = "";
  try {
    const ver = await api().app_version();
    document.getElementById("set-app-version").textContent = (ver && ver.version) || "";
  } catch (err) {
    document.getElementById("set-app-version").textContent = "";
  }
  settingsDialog.showModal();
}

async function saveSettings() {
  const status = document.getElementById("set-status");
  try {
    const out = await api().save_settings({
      base_url: document.getElementById("set-base").value,
      api_key: document.getElementById("set-key").value,
      model: document.getElementById("set-model").value,
      auth_mode: document.getElementById("set-auth").value,
      theme: document.getElementById("set-theme").value,
    });
    if (!out || !out.ok) {
      status.textContent = (out && out.error) || "保存失败";
      return false;
    }
    status.textContent = "已保存";
    document.getElementById("set-key").value = "";
    applyTheme(document.getElementById("set-theme").value);
    return true;
  } catch (err) {
    status.textContent = "保存出错：" + (err && err.message ? err.message : String(err));
    return false;
  }
}

async function testConn() {
  const status = document.getElementById("set-status");
  try {
    const saved = await saveSettings();
    if (!saved) return;
    const out = await api().test_connection();
    if (!out || !out.ok) {
      status.textContent = (out && out.error) || "连接失败";
      return;
    }
    status.textContent = "连接成功：" + (out.reply || "").slice(0, 80);
  } catch (err) {
    status.textContent = "测试出错：" + (err && err.message ? err.message : String(err));
  }
}

document.getElementById("btn-open").addEventListener("click", openDeck);
document.getElementById("btn-fav-filter").addEventListener("click", toggleFavFilter);
document.getElementById("btn-credits").addEventListener("click", openCredits);
document.getElementById("btn-redeem").addEventListener("click", redeemCredits);
document.getElementById("btn-copy-invite").addEventListener("click", copyInviteCode);
document.getElementById("btn-invite-redeem").addEventListener("click", redeemInvite);
document.getElementById("credits-dialog").addEventListener("close", stopPayPoll);
document.querySelectorAll("[data-pay-amount]").forEach((btn) => {
  btn.addEventListener("click", () => startWechatPay(Number(btn.getAttribute("data-pay-amount"))));
});
document.getElementById("ai-route").addEventListener("change", () => {
  document.getElementById("ai-route").dataset.touched = "1";
});
document.getElementById("btn-settings").addEventListener("click", openSettings);
document.getElementById("theme-select").addEventListener("change", (e) => persistTheme(e.target.value));
document.getElementById("set-theme").addEventListener("change", (e) => persistTheme(e.target.value));
document.getElementById("btn-script").addEventListener("click", generateScript);
document.getElementById("btn-script-all").addEventListener("click", generateAllScripts);
document.getElementById("btn-send").addEventListener("click", sendQuestion);
document.getElementById("btn-clear-chat").addEventListener("click", clearChat);
document.getElementById("btn-qa-favs").addEventListener("click", openQaFavs);
document.getElementById("qa-fav-search").addEventListener("input", (e) => {
  renderQaFavList(e.target.value);
});
document.getElementById("btn-attach").addEventListener("click", () => {
  document.getElementById("chat-file").click();
});
document.getElementById("chat-file").addEventListener("change", (e) => {
  const files = e.target.files || [];
  Array.from(files).forEach((file) => addAttachmentFile(file));
  e.target.value = "";
});
chatInput.addEventListener("paste", (e) => {
  const items = (e.clipboardData && e.clipboardData.items) || [];
  let usedImage = false;
  for (const item of items) {
    if (item.type && item.type.indexOf("image/") === 0) {
      const file = item.getAsFile();
      if (file) {
        usedImage = true;
        addAttachmentFile(file);
      }
    }
  }
  if (usedImage) e.preventDefault();
});
document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
document.getElementById("btn-test").addEventListener("click", testConn);
document.getElementById("btn-check-update").addEventListener("click", () => checkAppUpdate({ force: true }));
document.getElementById("settings-form").addEventListener("submit", (e) => {
  if (e.submitter && e.submitter.id === "btn-save-settings") {
    e.preventDefault();
  }
});
chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendQuestion();
  }
});
document.addEventListener("keydown", (e) => {
  if (e.target.tagName === "TEXTAREA" || e.target.tagName === "INPUT") return;
  if (e.key === "ArrowDown" || e.key === "PageDown") {
    e.preventDefault();
    stepSlide(1);
  }
  if (e.key === "ArrowUp" || e.key === "PageUp") {
    e.preventDefault();
    stepSlide(-1);
  }
});

const stage = document.getElementById("stage");
let wheelLockUntil = 0;
let wheelAcc = 0;

function isPptName(name) {
  return /\.(pptx?|pdf)$/i.test(String(name || ""));
}

function droppedFilePath(file) {
  if (!file) return "";
  return file.path || file.pywebviewFullPath || "";
}

stage.addEventListener("dragenter", (e) => {
  e.preventDefault();
  stage.classList.add("drop-hover");
});
stage.addEventListener("dragover", (e) => {
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
  stage.classList.add("drop-hover");
});
stage.addEventListener("dragleave", (e) => {
  if (e.relatedTarget && stage.contains(e.relatedTarget)) return;
  stage.classList.remove("drop-hover");
});
stage.addEventListener("drop", (e) => {
  e.preventDefault();
  stage.classList.remove("drop-hover");
  const files = (e.dataTransfer && e.dataTransfer.files) || [];
  const ppt = Array.from(files).find(
    (f) => isPptName(f.name) || isPptName(droppedFilePath(f))
  );
  if (!ppt) {
    if (files.length) addMsg("error", "请拖入 PPT、PPTX 或 PDF 课件");
    return;
  }
  const path = droppedFilePath(ppt);
  if (path) openDeckFromPath(path);
  else ingestStatus.textContent = "正在读取课件…";
});

stage.addEventListener(
  "wheel",
  (e) => {
    if (!slideCount) return;
    e.preventDefault();
    const now = Date.now();
    if (now < wheelLockUntil) return;
    const primary = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    wheelAcc += primary;
    if (Math.abs(wheelAcc) < 40) return;
    const dir = wheelAcc > 0 ? 1 : -1;
    wheelAcc = 0;
    wheelLockUntil = now + 180;
    stepSlide(dir);
  },
  { passive: false }
);

const ai = document.getElementById("ai");
const resize = document.getElementById("resize");
const SPLIT_W = 6;

function paneLeft() {
  return parseInt(getComputedStyle(document.documentElement).getPropertyValue("--left"), 10) || 180;
}

function paneRight() {
  return parseInt(getComputedStyle(document.documentElement).getPropertyValue("--right"), 10) || 360;
}

function setPaneWidths(left, right) {
  const maxRight = Math.max(280, window.innerWidth - left - 200 - SPLIT_W * 2);
  left = Math.min(Math.max(120, left), 420);
  right = Math.min(Math.max(280, right), maxRight);
  document.documentElement.style.setProperty("--left", left + "px");
  document.documentElement.style.setProperty("--right", right + "px");
}

function bindSplitter(el, axis, onMove) {
  el.addEventListener("mousedown", (e) => {
    e.preventDefault();
    document.body.classList.add(axis === "y" ? "resizing-y" : "resizing");
    function move(ev) {
      onMove(ev);
    }
    function up() {
      document.body.classList.remove("resizing", "resizing-y");
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", up);
    }
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
  });
}

bindSplitter(document.getElementById("split-left"), "x", (ev) => {
  setPaneWidths(ev.clientX, paneRight());
});
bindSplitter(document.getElementById("split-right"), "x", (ev) => {
  setPaneWidths(paneLeft(), window.innerWidth - ev.clientX);
});

resize.addEventListener("mousedown", (e) => {
  e.preventDefault();
  document.body.classList.add("resizing-y");
  const startY = e.clientY;
  const script = document.getElementById("script-pane");
  const startH = script.getBoundingClientRect().height;
  const aiH = ai.getBoundingClientRect().height;
  function move(ev) {
    const maxH = Math.max(80, aiH - 160 - SPLIT_W);
    const next = Math.min(maxH, Math.max(80, startH + (ev.clientY - startY)));
    script.style.flex = "none";
    script.style.height = next + "px";
  }
  function up() {
    document.body.classList.remove("resizing-y");
    window.removeEventListener("mousemove", move);
    window.removeEventListener("mouseup", up);
  }
  window.addEventListener("mousemove", move);
  window.addEventListener("mouseup", up);
});

let dismissedUpdateVersion = "";
let offeredUpdateVersion = "";

async function checkAppUpdate(opts) {
  const force = Boolean(opts && opts.force);
  const statusEl = document.getElementById("set-update-status");
  try {
    const out = await api().check_app_update();
    if (!out || !out.ok) {
      if (force && statusEl) statusEl.textContent = (out && out.error) || "无法检查更新";
      return;
    }
    if (!out.newer) {
      if (force && statusEl) {
        statusEl.textContent = out.available
          ? ("服务器 " + (out.version || "") + "，当前 " + (out.current || "") + "，已是最新")
          : "服务器还没有发布新安装包";
      }
      return;
    }
    if (!force && dismissedUpdateVersion === out.version) return;
    const dlg = document.getElementById("update-dialog");
    if (dlg.open && offeredUpdateVersion === out.version) return;
    offeredUpdateVersion = out.version || "";
    const sizeMb = out.size ? (out.size / 1024 / 1024).toFixed(1) + " MB" : "";
    document.getElementById("update-copy").textContent =
      "当前 " + (out.current || "") + "，服务器 " + (out.version || "") +
      (sizeMb ? "（" + sizeMb + "）" : "") +
      "。更新会先关闭当前程序，再覆盖原来的安装目录。";
    document.getElementById("update-status").textContent = "";
    document.getElementById("btn-update-now").disabled = false;
    if (force && statusEl) statusEl.textContent = "发现新版本 " + (out.version || "");
    if (!dlg.open) dlg.showModal();
  } catch (err) {
    if (force && statusEl) statusEl.textContent = "无法检查更新";
  }
}

document.getElementById("btn-update-later").addEventListener("click", () => {
  dismissedUpdateVersion = offeredUpdateVersion;
  document.getElementById("update-dialog").close();
});

document.getElementById("btn-update-now").addEventListener("click", async () => {
  const btn = document.getElementById("btn-update-now");
  const status = document.getElementById("update-status");
  btn.disabled = true;
  status.textContent = "正在下载安装包…";
  try {
    const out = await api().apply_app_update();
    if (!out || !out.ok) {
      status.textContent = (out && out.error) || "更新失败";
      btn.disabled = false;
      return;
    }
    status.textContent = "已打开安装程序，即将退出当前程序以便覆盖安装…";
    try {
      await api().quit_app();
    } catch (err) {
      /* installer will close the running app */
    }
  } catch (err) {
    status.textContent = "更新失败";
    btn.disabled = false;
  }
});

window.addEventListener("pywebviewready", async () => {
  try {
    const s = await api().get_settings();
    applyTheme((s && s.theme) || "light");
    registerWithServer();
    await refreshWallet();
    sessionStartedAt = Date.now() / 1000;
    sessionEnded = false;
    reportFeature("app", 0, "session_start");
    setInterval(() => reportFeature("app", 60000, "heartbeat"), 60000);
    window.addEventListener("pagehide", reportSessionEnd);
    window.addEventListener("beforeunload", reportSessionEnd);
    checkAppUpdate();
    setInterval(() => checkAppUpdate(), 120000);
  } catch (err) {
    applyTheme("light");
  }
});
window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (themePref === "system") applyTheme("system");
});
