(function (global) {
  const PRESETS = {
    ramp_x: (x) => x,
    ramp_y: (_x, y) => y,
    ramp_diag: (x, y) => 0.5 * (x + y),
    step_x: (x) => (x > 0.5 ? 1 : 0),
    step_y: (_x, y) => (y > 0.5 ? 1 : 0),
    corner: (x, y) => (x > 0.5 && y < 0.5 ? 1 : 0),
    gaussian: (x, y) =>
      Math.exp(-((x - 0.5) * (x - 0.5) + (y - 0.5) * (y - 0.5)) / 0.06),
  };

  function clamp(n, lo, hi) {
    return Math.max(lo, Math.min(hi, n));
  }

  function parseSpec(raw) {
    const text = String(raw || "").trim();
    const tryParse = (s) => {
      try {
        return JSON.parse(s);
      } catch (err) {
        return null;
      }
    };
    let spec = tryParse(text);
    if (!spec) {
      const a = text.indexOf("{");
      const b = text.lastIndexOf("}");
      if (a >= 0 && b > a) spec = tryParse(text.slice(a, b + 1));
    }
    return spec && typeof spec === "object" ? spec : null;
  }

  function sampleGrid(fn, n) {
    const z = [];
    for (let j = 0; j < n; j++) {
      const row = [];
      const y = 1 - j / (n - 1);
      for (let i = 0; i < n; i++) {
        const x = i / (n - 1);
        row.push(fn(x, y));
      }
      z.push(row);
    }
    return z;
  }

  function resolveZ(spec) {
    if (Array.isArray(spec.z) && spec.z.length && Array.isArray(spec.z[0])) {
      return spec.z.slice(0, 48).map((row) =>
        row.slice(0, 48).map((v) => Number(v) || 0)
      );
    }
    const n = clamp(Number(spec.resolution) || 24, 12, 36);
    const fn = PRESETS[spec.preset] || PRESETS.ramp_diag;
    return sampleGrid(fn, n);
  }

  function heightColor(t) {
    const u = clamp(t, 0, 1);
    const r = Math.round(15 + 230 * u);
    const g = Math.round(23 + 180 * u);
    const b = Math.round(42 + 80 * (1 - u));
    return "rgb(" + r + "," + g + "," + b + ")";
  }

  function mountSurface(el, spec) {
    const grid = resolveZ(spec);
    const n = grid.length;
    const m = grid[0].length;
    const showG = spec.showGradient !== false;

    const title = document.createElement("div");
    title.className = "viz-title";
    title.textContent = spec.title || "强度曲面";

    const canvas = document.createElement("canvas");
    canvas.className = "viz-canvas";
    const wrap = document.createElement("div");
    wrap.className = "viz-canvas-wrap";
    wrap.appendChild(canvas);

    const hint = document.createElement("div");
    hint.className = "viz-hint";
    hint.textContent =
      spec.hint ||
      "拖动旋转。红箭头是梯度：指向强度增加最快的方向，长度表示模。";

    el.replaceChildren(title, wrap, hint);

    let yaw = 0.7;
    let pitch = 0.55;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;

    function world(i, j) {
      const x = (i / (m - 1)) * 2 - 1;
      const y = (j / (n - 1)) * 2 - 1;
      const z = (grid[j][i] - 0.15) * 1.35;
      return { x: x, y: y, z: z, i: i, j: j };
    }

    function transform(p) {
      const cy = Math.cos(yaw);
      const sy = Math.sin(yaw);
      let x = p.x * cy - p.y * sy;
      let y = p.x * sy + p.y * cy;
      let z = p.z;
      const cp = Math.cos(pitch);
      const sp = Math.sin(pitch);
      const y2 = y * cp - z * sp;
      const z2 = y * sp + z * cp;
      return { x: x, y: y2, z: z2 };
    }

    function project(p, w, h) {
      const t = transform(p);
      const dist = 3.4;
      const s = 2.15 / (dist - t.y);
      return {
        x: w * 0.5 + t.x * s * w * 0.38,
        y: h * 0.62 - t.z * s * h * 0.42,
        d: t.y,
      };
    }

    function gradAt(i, j) {
      const il = Math.max(0, i - 1);
      const ir = Math.min(m - 1, i + 1);
      const jl = Math.max(0, j - 1);
      const jr = Math.min(n - 1, j + 1);
      const gx = (grid[j][ir] - grid[j][il]) / Math.max(1e-6, (ir - il) / (m - 1));
      const gy = (grid[jr][i] - grid[jl][i]) / Math.max(1e-6, (jr - jl) / (n - 1));
      return { gx: gx, gy: gy };
    }

    function draw() {
      const rect = wrap.getBoundingClientRect();
      const w = Math.max(280, Math.floor(rect.width || 320));
      const h = 240;
      const scale = window.devicePixelRatio || 1;
      canvas.width = w * scale;
      canvas.height = h * scale;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#0f172a";
      ctx.fillRect(0, 0, w, h);

      const faces = [];
      for (let j = 0; j < n - 1; j++) {
        for (let i = 0; i < m - 1; i++) {
          const a = world(i, j);
          const b = world(i + 1, j);
          const c = world(i + 1, j + 1);
          const d = world(i, j + 1);
          const pa = project(a, w, h);
          const pb = project(b, w, h);
          const pc = project(c, w, h);
          const pd = project(d, w, h);
          faces.push({
            pts: [pa, pb, pc, pd],
            d: (pa.d + pb.d + pc.d + pd.d) / 4,
            z: (grid[j][i] + grid[j][i + 1] + grid[j + 1][i] + grid[j + 1][i + 1]) / 4,
          });
        }
      }
      faces.sort((a, b) => a.d - b.d);
      faces.forEach((f) => {
        ctx.beginPath();
        ctx.moveTo(f.pts[0].x, f.pts[0].y);
        f.pts.forEach((p) => ctx.lineTo(p.x, p.y));
        ctx.closePath();
        ctx.fillStyle = heightColor(f.z);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.18)";
        ctx.lineWidth = 0.6;
        ctx.stroke();
      });

      if (showG) {
        const step = Math.max(2, Math.floor(n / 8));
        ctx.strokeStyle = "#fb7185";
        ctx.fillStyle = "#fb7185";
        ctx.lineWidth = 1.6;
        for (let j = step; j < n - 1; j += step) {
          for (let i = step; i < m - 1; i += step) {
            const g = gradAt(i, j);
            const mag = Math.sqrt(g.gx * g.gx + g.gy * g.gy);
            if (mag < 0.08) continue;
            const len = 0.18 * clamp(mag / 3, 0.25, 1.4);
            const nx = g.gx / mag;
            const ny = -g.gy / mag;
            const p0 = world(i, j);
            const p1 = {
              x: p0.x + nx * len,
              y: p0.y + ny * len,
              z: p0.z + 0.02,
            };
            const a = project(p0, w, h);
            const b = project(p1, w, h);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
            const ang = Math.atan2(b.y - a.y, b.x - a.x);
            ctx.beginPath();
            ctx.moveTo(b.x, b.y);
            ctx.lineTo(
              b.x - 7 * Math.cos(ang - 0.4),
              b.y - 7 * Math.sin(ang - 0.4)
            );
            ctx.lineTo(
              b.x - 7 * Math.cos(ang + 0.4),
              b.y - 7 * Math.sin(ang + 0.4)
            );
            ctx.closePath();
            ctx.fill();
          }
        }
      }

      ctx.fillStyle = "#94a3b8";
      ctx.font = "11px Segoe UI, Microsoft YaHei, sans-serif";
      ctx.fillText("x →", w - 36, h - 14);
      ctx.fillText("亮/高", 10, 16);
    }

    wrap.addEventListener("mousedown", (e) => {
      e.preventDefault();
      dragging = true;
      lastX = e.clientX;
      lastY = e.clientY;
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      yaw += (e.clientX - lastX) * 0.01;
      pitch = clamp(pitch + (e.clientY - lastY) * 0.01, 0.15, 1.2);
      lastX = e.clientX;
      lastY = e.clientY;
      draw();
    });
    window.addEventListener("mouseup", () => {
      dragging = false;
    });

    requestAnimationFrame(draw);
  }

  function sanitizeSvg(raw) {
    let src = String(raw || "").trim();
    if (!src) return "";
    if (!/^<svg[\s>]/i.test(src)) {
      src =
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">' +
        src +
        "</svg>";
    }
    const doc = new DOMParser().parseFromString(src, "image/svg+xml");
    const root = doc.documentElement;
    if (!root || root.nodeName.toLowerCase() === "parsererror") return "";
    root.querySelectorAll("script, iframe, foreignObject, object, embed").forEach((n) => n.remove());
    root.querySelectorAll("*").forEach((node) => {
      [...node.attributes].forEach((attr) => {
        const name = attr.name.toLowerCase();
        const val = attr.value || "";
        if (name.startsWith("on") || /javascript:/i.test(val)) {
          node.removeAttribute(attr.name);
        }
      });
    });
    if (!root.getAttribute("viewBox") && !root.getAttribute("width")) {
      root.setAttribute("viewBox", "0 0 320 180");
    }
    root.setAttribute("width", "100%");
    if (!root.getAttribute("xmlns")) {
      root.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    }
    return new XMLSerializer().serializeToString(root);
  }

  function mountSvg(el, raw) {
    const html = sanitizeSvg(raw);
    el.classList.add("svg-card");
    el.innerHTML = html || "<div class='viz-hint'>示意图无法显示</div>";
  }

  function gridFromFn(rows, cols, fn) {
    const g = [];
    for (let r = 0; r < rows; r++) {
      const row = [];
      for (let c = 0; c < cols; c++) {
        row.push(fn(c / Math.max(1, cols - 1), r / Math.max(1, rows - 1), r, c));
      }
      g.push(row);
    }
    return g;
  }

  function cloneGrid(grid) {
    return grid.map((row) => row.slice());
  }

  function sanitizeGrid(raw) {
    if (!Array.isArray(raw) || !raw.length || !Array.isArray(raw[0])) return null;
    return raw.slice(0, 24).map((row) =>
      row.slice(0, 24).map((v) => {
        const n = Number(v);
        return Number.isFinite(n) ? n : -1;
      })
    );
  }

  function sanitizeFrames(raw) {
    if (!Array.isArray(raw)) return [];
    return raw.slice(0, 96).map((f) => {
      const src = f && typeof f === "object" ? f : {};
      const win = src.window && typeof src.window === "object" ? src.window : null;
      const arrows = Array.isArray(src.arrows) ? src.arrows.slice(0, 24) : [];
      return {
        kind: String(src.kind || "grid").slice(0, 20),
        caption: String(src.caption || "").slice(0, 240),
        grid: sanitizeGrid(src.grid),
        out: sanitizeGrid(src.out),
        window: win
          ? {
              r: Number(win.r) || 0,
              c: Number(win.c) || 0,
              rows: clamp(Number(win.rows) || 3, 1, 8),
              cols: clamp(Number(win.cols) || 3, 1, 8),
            }
          : null,
        marker: src.marker && typeof src.marker === "object"
          ? { r: Number(src.marker.r) || 0, c: Number(src.marker.c) || 0 }
          : null,
        arrows: arrows.map((a) => ({
          r: Number(a && a.r) || 0,
          c: Number(a && a.c) || 0,
          dx: Number(a && a.dx) || 0,
          dy: Number(a && a.dy) || 0,
        })),
        x: Number(src.x) || 0,
        y: Number(src.y) || 0,
        ang: Number(src.ang) || 0,
      };
    });
  }

  function convolveAt(img, r, c, kernel, ksum) {
    const k = kernel.length;
    let s = 0;
    for (let i = 0; i < k; i++) {
      for (let j = 0; j < k; j++) {
        s += img[r + i][c + j] * kernel[i][j];
      }
    }
    return s / (ksum || 1);
  }

  function slideKernelFrames(img, kernel, ksum, outFn, captionFn) {
    const k = kernel.length;
    const H = img.length;
    const W = img[0].length;
    const outH = H - k + 1;
    const outW = W - k + 1;
    const out = Array.from({ length: outH }, () => Array(outW).fill(-1));
    const frames = [];
    for (let r = 0; r < outH; r++) {
      for (let c = 0; c < outW; c++) {
        const val = outFn(img, r, c, kernel, ksum);
        out[r][c] = val;
        frames.push({
          kind: "grid",
          caption: captionFn(r, c, val),
          grid: img,
          out: cloneGrid(out),
          window: { r: r, c: c, rows: k, cols: k },
        });
      }
    }
    return frames;
  }

  function buildKernelSlide() {
    const img = gridFromFn(6, 8, (_x, _y, r, c) => (c >= 4 ? 0.95 : 0.12));
    const kernel = [
      [1, 1, 1],
      [1, 1, 1],
      [1, 1, 1],
    ];
    return slideKernelFrames(
      img,
      kernel,
      9,
      convolveAt,
      (r, c, val) =>
        "核滑到 (" + (c + 1) + "," + (r + 1) + ")：邻域平均 = " + val.toFixed(2)
    );
  }

  function buildGaussianBlur() {
    const img = gridFromFn(7, 8, (x, y, r, c) => {
      const blob = Math.exp(-((x - 0.45) * (x - 0.45) + (y - 0.5) * (y - 0.5)) / 0.08);
      const noise = ((r * 13 + c * 7) % 5) / 18;
      return clamp(blob * 0.75 + noise, 0, 1);
    });
    const kernel = [
      [1, 2, 1],
      [2, 4, 2],
      [1, 2, 1],
    ];
    return slideKernelFrames(
      img,
      kernel,
      16,
      convolveAt,
      (r, c, val) =>
        "高斯核在 (" + (c + 1) + "," + (r + 1) + ")：加权平均 = " + val.toFixed(2)
    );
  }

  function buildEdgeDetect() {
    const img = gridFromFn(6, 8, (_x, _y, r, c) => (c >= 4 ? 1 : 0.08));
    const kernel = [
      [-1, 0, 1],
      [-2, 0, 2],
      [-1, 0, 1],
    ];
    return slideKernelFrames(
      img,
      kernel,
      1,
      (src, r, c, k) => Math.abs(convolveAt(src, r, c, k, 1)) / 4,
      (r, c, val) =>
        "Sobel 窗在 (" +
        (c + 1) +
        "," +
        (r + 1) +
        ")：|Gx| = " +
        val.toFixed(2) +
        (val > 0.4 ? "  ← 边缘" : "")
    );
  }

  function buildResample() {
    const coarse = gridFromFn(4, 4, (x, y) =>
      Math.exp(-((x - 0.35) * (x - 0.35) + (y - 0.4) * (y - 0.4)) / 0.18)
    );
    const frames = [
      {
        kind: "grid",
        caption: "粗采样：只保留 4×4 个样点",
        grid: coarse,
        out: null,
      },
    ];
    const fine = Array.from({ length: 8 }, () => Array(8).fill(-1));
    for (let r = 0; r < 8; r++) {
      for (let c = 0; c < 8; c++) {
        const y = r / 7;
        const x = c / 7;
        const r0 = Math.min(3, Math.floor(y * 3));
        const c0 = Math.min(3, Math.floor(x * 3));
        const r1 = Math.min(3, r0 + 1);
        const c1 = Math.min(3, c0 + 1);
        const fy = y * 3 - r0;
        const fx = x * 3 - c0;
        const v00 = coarse[r0][c0];
        const v10 = coarse[r0][c1];
        const v01 = coarse[r1][c0];
        const v11 = coarse[r1][c1];
        fine[r][c] =
          v00 * (1 - fx) * (1 - fy) +
          v10 * fx * (1 - fy) +
          v01 * (1 - fx) * fy +
          v11 * fx * fy;
        frames.push({
          kind: "grid",
          caption:
            "双线性插值填入 (" +
            (c + 1) +
            "," +
            (r + 1) +
            ") = " +
            fine[r][c].toFixed(2),
          grid: coarse,
          out: cloneGrid(fine),
        });
      }
    }
    return frames;
  }

  function buildGradientWalk() {
    const n = 12;
    const fn = (x, y) =>
      Math.exp(-((x - 0.72) * (x - 0.72) + (y - 0.28) * (y - 0.28)) / 0.11);
    const grid = gridFromFn(n, n, (x, y) => fn(x, y));
    let x = 0.18;
    let y = 0.78;
    const frames = [];
    for (let s = 0; s < 28; s++) {
      const eps = 0.04;
      const gx = (fn(x + eps, y) - fn(x - eps, y)) / (2 * eps);
      const gy = (fn(x, y + eps) - fn(x, y - eps)) / (2 * eps);
      const mag = Math.sqrt(gx * gx + gy * gy);
      const c = clamp(Math.round(x * (n - 1)), 0, n - 1);
      const r = clamp(Math.round(y * (n - 1)), 0, n - 1);
      frames.push({
        kind: "grid",
        caption:
          "沿梯度走：∇I ≈ (" +
          gx.toFixed(2) +
          ", " +
          gy.toFixed(2) +
          ")，模 " +
          mag.toFixed(2),
        grid: grid,
        marker: { r: r, c: c },
        arrows: [{ r: r, c: c, dx: gx, dy: gy }],
      });
      if (mag < 0.08) break;
      x = clamp(x + 0.045 * (gx / mag), 0.05, 0.95);
      y = clamp(y + 0.045 * (gy / mag), 0.05, 0.95);
    }
    return frames;
  }

  function buildAtan2() {
    const frames = [];
    for (let t = 0; t < 48; t++) {
      const ang = (t / 48) * Math.PI * 2 - Math.PI;
      const x = Math.cos(ang);
      const y = Math.sin(ang);
      const deg = (ang * 180) / Math.PI;
      frames.push({
        kind: "atan2",
        caption:
          "x=" +
          x.toFixed(2) +
          "  y=" +
          y.toFixed(2) +
          "  θ=atan2(y,x)=" +
          deg.toFixed(0) +
          "°",
        x: x,
        y: y,
        ang: ang,
      });
    }
    return frames;
  }

  const ANIM_PRESETS = {
    kernel_slide: buildKernelSlide,
    gaussian_blur: buildGaussianBlur,
    resample: buildResample,
    gradient_walk: buildGradientWalk,
    atan2: buildAtan2,
    edge_detect: buildEdgeDetect,
  };

  function resolveAnimFrames(spec) {
    const builder = ANIM_PRESETS[String(spec.preset || "")];
    if (builder) return builder(spec);
    const custom = sanitizeFrames(spec.frames);
    return custom.length ? custom : buildKernelSlide();
  }

  function cellColor(v) {
    if (v < 0) return "rgba(148,163,184,0.12)";
    return heightColor(v);
  }

  function drawOneGrid(ctx, grid, x0, y0, size, frame) {
    const rows = grid.length;
    const cols = grid[0].length;
    const cell = size / Math.max(rows, cols);
    const gw = cols * cell;
    const gh = rows * cell;
    const ox = x0 + (size - gw) / 2;
    const oy = y0 + (size - gh) / 2;
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const v = grid[r][c];
        ctx.fillStyle = cellColor(v);
        ctx.fillRect(ox + c * cell, oy + r * cell, cell - 0.8, cell - 0.8);
        if (v < 0) {
          ctx.strokeStyle = "rgba(148,163,184,0.35)";
          ctx.strokeRect(ox + c * cell, oy + r * cell, cell - 0.8, cell - 0.8);
        }
      }
    }
    if (frame.window && grid === frame.grid) {
      const w = frame.window;
      ctx.strokeStyle = "#fbbf24";
      ctx.lineWidth = 2;
      ctx.strokeRect(
        ox + w.c * cell,
        oy + w.r * cell,
        w.cols * cell - 0.8,
        w.rows * cell - 0.8
      );
    }
    if (frame.marker && grid === frame.grid) {
      const m = frame.marker;
      ctx.beginPath();
      ctx.fillStyle = "#38bdf8";
      ctx.arc(
        ox + (m.c + 0.5) * cell,
        oy + (m.r + 0.5) * cell,
        Math.max(3, cell * 0.28),
        0,
        Math.PI * 2
      );
      ctx.fill();
    }
    if (frame.arrows && grid === frame.grid) {
      ctx.strokeStyle = "#fb7185";
      ctx.fillStyle = "#fb7185";
      ctx.lineWidth = 2;
      frame.arrows.forEach((a) => {
        const mag = Math.sqrt(a.dx * a.dx + a.dy * a.dy) || 1;
        const len = cell * 1.6 * clamp(mag / 3, 0.35, 1.2);
        const x1 = ox + (a.c + 0.5) * cell;
        const y1 = oy + (a.r + 0.5) * cell;
        const x2 = x1 + (a.dx / mag) * len;
        const y2 = y1 + (a.dy / mag) * len;
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
        const ang = Math.atan2(y2 - y1, x2 - x1);
        ctx.beginPath();
        ctx.moveTo(x2, y2);
        ctx.lineTo(x2 - 7 * Math.cos(ang - 0.4), y2 - 7 * Math.sin(ang - 0.4));
        ctx.lineTo(x2 - 7 * Math.cos(ang + 0.4), y2 - 7 * Math.sin(ang + 0.4));
        ctx.closePath();
        ctx.fill();
      });
    }
  }

  function drawAtan2Frame(ctx, w, h, frame) {
    const cx = w * 0.5;
    const cy = h * 0.54;
    const R = Math.min(w, h) * 0.32;
    ctx.strokeStyle = "#64748b";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(24, cy);
    ctx.lineTo(w - 24, cy);
    ctx.moveTo(cx, 18);
    ctx.lineTo(cx, h - 18);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(cx, cy, R, 0, Math.PI * 2);
    ctx.stroke();
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px Segoe UI, Microsoft YaHei, sans-serif";
    ctx.fillText("x", w - 28, cy - 6);
    ctx.fillText("y", cx + 6, 16);
    const ang = frame.ang;
    ctx.fillStyle = "rgba(251,113,133,0.18)";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, R * 0.42, 0, -ang, ang > 0);
    ctx.closePath();
    ctx.fill();
    const x2 = cx + Math.cos(ang) * R;
    const y2 = cy - Math.sin(ang) * R;
    ctx.strokeStyle = "#38bdf8";
    ctx.fillStyle = "#38bdf8";
    ctx.lineWidth = 2.4;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x2, y2);
    ctx.stroke();
    const head = Math.atan2(y2 - cy, x2 - cx);
    ctx.beginPath();
    ctx.moveTo(x2, y2);
    ctx.lineTo(x2 - 10 * Math.cos(head - 0.4), y2 - 10 * Math.sin(head - 0.4));
    ctx.lineTo(x2 - 10 * Math.cos(head + 0.4), y2 - 10 * Math.sin(head + 0.4));
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#e2e8f0";
    ctx.fillText("θ", cx + 10, cy - 10);
  }

  function drawAnimFrame(ctx, w, h, frame) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "#0f172a";
    ctx.fillRect(0, 0, w, h);
    if (frame.kind === "atan2") {
      drawAtan2Frame(ctx, w, h, frame);
      return;
    }
    const grid = frame.grid;
    if (!grid) return;
    const pad = 12;
    const hasOut = !!frame.out;
    const size = hasOut ? Math.min((w - pad * 3) / 2, h - 28) : Math.min(w - pad * 2, h - 28);
    ctx.fillStyle = "#94a3b8";
    ctx.font = "11px Segoe UI, Microsoft YaHei, sans-serif";
    if (hasOut) {
      ctx.fillText("输入", pad, 16);
      ctx.fillText("输出", pad * 2 + size, 16);
      drawOneGrid(ctx, grid, pad, 22, size, frame);
      drawOneGrid(ctx, frame.out, pad * 2 + size, 22, size, { arrows: [], marker: null, window: null });
    } else {
      drawOneGrid(ctx, grid, (w - size) / 2, 18, size, frame);
    }
  }

  function mountAnim(el, spec) {
    const frames = resolveAnimFrames(spec);
    const title = document.createElement("div");
    title.className = "viz-title";
    title.textContent = spec.title || "过程动画";

    const canvas = document.createElement("canvas");
    canvas.className = "viz-canvas viz-anim-canvas";
    const wrap = document.createElement("div");
    wrap.className = "viz-canvas-wrap";
    wrap.appendChild(canvas);

    const caption = document.createElement("div");
    caption.className = "viz-caption";

    const bar = document.createElement("div");
    bar.className = "viz-anim-bar";
    const btnPlay = document.createElement("button");
    btnPlay.type = "button";
    const btnPrev = document.createElement("button");
    btnPrev.type = "button";
    btnPrev.textContent = "上一步";
    const btnNext = document.createElement("button");
    btnNext.type = "button";
    btnNext.textContent = "下一步";
    const progress = document.createElement("span");
    progress.className = "viz-anim-progress";
    bar.append(btnPlay, btnPrev, btnNext, progress);

    const hint = document.createElement("div");
    hint.className = "viz-hint";
    hint.textContent = spec.hint || "动画会循环播放。可暂停后单步查看每一步。";

    el.replaceChildren(title, wrap, caption, bar, hint);

    let idx = 0;
    let playing = true;
    let last = 0;
    const period = 1000 / clamp(Number(spec.fps) || 5, 1, 12);

    function paint() {
      const rect = wrap.getBoundingClientRect();
      const w = Math.max(280, Math.floor(rect.width || 320));
      const h = 260;
      const scale = window.devicePixelRatio || 1;
      canvas.width = w * scale;
      canvas.height = h * scale;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      const ctx = canvas.getContext("2d");
      ctx.setTransform(scale, 0, 0, scale, 0, 0);
      const frame = frames[idx] || { kind: "grid", caption: "" };
      drawAnimFrame(ctx, w, h, frame);
      caption.textContent = frame.caption || "";
      progress.textContent = idx + 1 + " / " + frames.length;
      btnPlay.textContent = playing ? "暂停" : "播放";
    }

    function loop(ts) {
      if (!el.isConnected) return;
      if (playing) {
        if (!last) last = ts;
        if (ts - last >= period) {
          last = ts;
          idx = (idx + 1) % frames.length;
          paint();
        }
      }
      requestAnimationFrame(loop);
    }

    btnPlay.addEventListener("click", () => {
      playing = !playing;
      last = 0;
      paint();
    });
    btnPrev.addEventListener("click", () => {
      playing = false;
      idx = (idx - 1 + frames.length) % frames.length;
      paint();
    });
    btnNext.addEventListener("click", () => {
      playing = false;
      idx = (idx + 1) % frames.length;
      paint();
    });

    requestAnimationFrame(paint);
    requestAnimationFrame(loop);
  }

  function mount(el, specOrRaw, kind) {
    if (kind === "svg") {
      mountSvg(el, specOrRaw);
      return;
    }
    const spec = typeof specOrRaw === "string" ? parseSpec(specOrRaw) : specOrRaw;
    if (!spec) {
      el.innerHTML = "<div class='viz-hint'>示意图无法解析</div>";
      return;
    }
    const type = spec.type || "surface3d";
    if (type === "anim") {
      mountAnim(el, spec);
      return;
    }
    if (type === "svg" && spec.svg) {
      mountSvg(el, spec.svg);
      return;
    }
    mountSurface(el, spec);
  }

  global.Viz3D = { mount, parseSpec, PRESETS, ANIM_PRESETS };
})(window);
