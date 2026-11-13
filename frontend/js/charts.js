/* Tiny dependency-free SVG charts for the Brightloop dashboard.
 * Exposes window.Charts = { line, bars, donut, hbars, spark }.
 * Every chart takes real values; nothing here invents data. */
(() => {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  let uid = 0;
  // Timers (not requestAnimationFrame) so charts still reach their final state in background tabs.
  const settle = (fn) => setTimeout(fn, 60);

  const svgEl = (tag, attrs = {}, parent) => {
    const n = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => n.setAttribute(k, v));
    if (parent) parent.appendChild(n);
    return n;
  };
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  /** ₹1.2k / ₹3.4L / ₹1.1Cr for axis labels. */
  function inrShort(n) {
    const v = Number(n || 0), a = Math.abs(v);
    const f = (x) => String(+x.toFixed(1));
    if (a >= 1e7) return "₹" + f(v / 1e7) + "Cr";
    if (a >= 1e5) return "₹" + f(v / 1e5) + "L";
    if (a >= 1e3) return "₹" + f(v / 1e3) + "k";
    return "₹" + Math.round(v);
  }
  const inrFull = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");

  // Rounds up to a value whose quarter is also "nice", so 4 axis steps read evenly.
  function niceMax(v) {
    if (v <= 0) return 4;
    const p = Math.pow(10, Math.floor(Math.log10(v)));
    const n = v / p;
    const m = [1, 1.2, 1.6, 2, 2.4, 3.2, 4, 6, 8, 10].find((c) => n <= c + 1e-9);
    return m * p;
  }

  /* ---- shared tooltip ---- */
  let tipEl;
  function tip(title, value, x, y) {
    if (!tipEl) {
      tipEl = document.createElement("div");
      tipEl.id = "tip";
      document.body.appendChild(tipEl);
    }
    tipEl.innerHTML = `${esc(value)}<span>${esc(title)}</span>`;
    tipEl.style.left = x + "px";
    tipEl.style.top = y + "px";
    tipEl.classList.add("on");
  }
  const hideTip = () => tipEl && tipEl.classList.remove("on");

  /* ---- draw now, and again whenever the container's width changes ---- */
  function mount(host, draw) {
    let width = 0, first = true;
    const run = () => {
      const w = Math.round(host.clientWidth);
      if (!w || w === width) return;
      width = w;
      draw(w, first);
      first = false;
    };
    run();
    if ("ResizeObserver" in window) {
      const ro = new ResizeObserver(() => {
        if (!host.isConnected) { ro.disconnect(); return; }
        run();
      });
      ro.observe(host);
    }
  }

  /* ------------------------------------------------------------------ *
   * Line chart (thin coral line, soft area, hover guide + tooltip)
   * ------------------------------------------------------------------ */
  function line(host, { labels, values, height = 230, format = inrShort, tipFormat = inrFull }) {
    host.classList.add("chart");
    mount(host, (W, animate) => {
      host.innerHTML = "";
      const H = height, m = { l: 46, r: 14, t: 14, b: 30 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const max = niceMax(Math.max(...values, 0));
      const n = values.length;
      const x = (i) => m.l + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
      const y = (v) => m.t + ih - (ih * v) / max;

      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Line chart" }, host);
      const gid = "lg" + ++uid;
      const defs = svgEl("defs", {}, svg);
      const grad = svgEl("linearGradient", { id: gid, x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
      svgEl("stop", { offset: "0%", "stop-color": "#1877f2", "stop-opacity": ".18" }, grad);
      svgEl("stop", { offset: "100%", "stop-color": "#1877f2", "stop-opacity": "0" }, grad);

      for (let t = 0; t <= 4; t++) {
        const gy = m.t + (ih * t) / 4;
        svgEl("line", { class: "grid", x1: m.l, x2: W - m.r, y1: gy, y2: gy }, svg);
        const lab = svgEl("text", { class: "axis", x: m.l - 10, y: gy + 4, "text-anchor": "end" }, svg);
        lab.textContent = format(max * (1 - t / 4));
      }
      labels.forEach((lb, i) => {
        const t = svgEl("text", { class: "axis", x: x(i), y: H - 8, "text-anchor": n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle" }, svg);
        t.textContent = lb;
      });

      // Smooth path with horizontal tangents (never overshoots below zero).
      let d = `M ${x(0)} ${y(values[0])}`;
      for (let i = 1; i < n; i++) {
        const mx = (x(i - 1) + x(i)) / 2;
        d += ` C ${mx} ${y(values[i - 1])}, ${mx} ${y(values[i])}, ${x(i)} ${y(values[i])}`;
      }
      if (n > 1) svgEl("path", { d: `${d} L ${x(n - 1)} ${m.t + ih} L ${x(0)} ${m.t + ih} Z`, fill: `url(#${gid})` }, svg);
      const path = svgEl("path", { class: "line", d }, svg);
      if (animate && !reduceMotion && path.getTotalLength) {
        const len = path.getTotalLength();
        path.style.strokeDasharray = len;
        path.style.strokeDashoffset = len;
        path.getBoundingClientRect();
        path.style.transition = "stroke-dashoffset 1.1s cubic-bezier(.2,.7,.2,1)";
        settle(() => { path.style.strokeDashoffset = 0; });
      }

      const guide = svgEl("line", { class: "guide", y1: m.t, y2: m.t + ih, opacity: 0 }, svg);
      const dot = svgEl("circle", { class: "dot-end", r: 5, cx: x(n - 1), cy: y(values[n - 1]) }, svg);
      const hit = svgEl("rect", { x: m.l, y: 0, width: iw, height: H, fill: "transparent" }, svg);
      const move = (ev) => {
        const box = svg.getBoundingClientRect();
        const px = ev.clientX - box.left;
        let idx = n === 1 ? 0 : Math.round(((px - m.l) / iw) * (n - 1));
        idx = Math.max(0, Math.min(n - 1, idx));
        guide.setAttribute("x1", x(idx)); guide.setAttribute("x2", x(idx)); guide.setAttribute("opacity", 1);
        dot.setAttribute("cx", x(idx)); dot.setAttribute("cy", y(values[idx]));
        tip(labels[idx], tipFormat(values[idx]), box.left + x(idx), box.top + y(values[idx]));
      };
      hit.addEventListener("pointermove", move);
      hit.addEventListener("pointerleave", () => {
        guide.setAttribute("opacity", 0);
        dot.setAttribute("cx", x(n - 1)); dot.setAttribute("cy", y(values[n - 1]));
        hideTip();
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Grouped bars with rounded tops
   * ------------------------------------------------------------------ */
  function bars(host, { labels, series, height = 200, format = inrShort, tipFormat = inrFull }) {
    host.classList.add("chart");
    mount(host, (W, animate) => {
      host.innerHTML = "";
      const H = height, m = { l: 40, r: 6, t: 10, b: 28 };
      const iw = W - m.l - m.r, ih = H - m.t - m.b;
      const max = niceMax(Math.max(...series.flatMap((s) => s.values), 0));
      const n = labels.length;
      const gw = iw / n;
      const bw = Math.max(6, Math.min(20, (gw - 14) / series.length - 4));
      const svg = svgEl("svg", { width: W, height: H, viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Bar chart" }, host);

      for (let t = 0; t <= 4; t++) {
        const gy = m.t + (ih * t) / 4;
        svgEl("line", { class: "grid", x1: m.l, x2: W - m.r, y1: gy, y2: gy }, svg);
        const lab = svgEl("text", { class: "axis", x: m.l - 8, y: gy + 4, "text-anchor": "end" }, svg);
        lab.textContent = format(max * (1 - t / 4));
      }
      labels.forEach((lb, i) => {
        const t = svgEl("text", { class: "axis", x: m.l + gw * i + gw / 2, y: H - 8, "text-anchor": "middle" }, svg);
        t.textContent = lb;
      });

      const groupW = series.length * bw + (series.length - 1) * 4;
      labels.forEach((lb, i) => {
        series.forEach((s, si) => {
          const v = s.values[i];
          const h = (ih * v) / max;
          if (!(h > 0)) return;
          const bx = m.l + gw * i + (gw - groupW) / 2 + si * (bw + 4);
          const by = m.t + ih - h, r = Math.min(6, h, bw / 2);
          const bar = svgEl("path", {
            class: "bar", fill: s.colors ? s.colors[i] : s.color,
            d: `M ${bx} ${by + h} L ${bx} ${by + r} Q ${bx} ${by} ${bx + r} ${by} L ${bx + bw - r} ${by} Q ${bx + bw} ${by} ${bx + bw} ${by + r} L ${bx + bw} ${by + h} Z`,
          }, svg);
          if (animate && !reduceMotion) {
            bar.style.transform = "scaleY(0)";
            bar.style.transition = `transform .8s cubic-bezier(.2,.7,.2,1) ${i * 70 + si * 40}ms`;
            settle(() => { bar.style.transform = "scaleY(1)"; });
          }
          bar.addEventListener("pointermove", (ev) => {
            const box = bar.getBoundingClientRect();
            tip(`${s.name} · ${lb}`, tipFormat(v), box.left + box.width / 2, box.top);
          });
          bar.addEventListener("pointerleave", hideTip);
        });
      });
    });
  }

  /* ------------------------------------------------------------------ *
   * Donut with an interactive legend
   * ------------------------------------------------------------------ */
  function donut(host, { segments, centerValue, centerLabel, size = 164, thickness = 18, unit = "" }) {
    const total = segments.reduce((a, s) => a + s.value, 0);
    const R = (size - thickness) / 2, C = 2 * Math.PI * R, gap = total > 0 && segments.filter((s) => s.value > 0).length > 1 ? 3 : 0;
    host.innerHTML = `<div class="donut-wrap"></div>`;
    const wrap = host.firstChild;
    const svg = svgEl("svg", { width: size, height: size, viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": "Distribution" });
    wrap.appendChild(svg);
    svgEl("circle", { cx: size / 2, cy: size / 2, r: R, fill: "none", stroke: "#e4e6eb", "stroke-width": thickness }, svg);

    const arcs = [];
    let offset = 0;
    segments.forEach((s, i) => {
      if (!(s.value > 0)) { arcs.push(null); return; }
      const len = (s.value / total) * C;
      const arc = svgEl("circle", {
        cx: size / 2, cy: size / 2, r: R, fill: "none", stroke: s.color, "stroke-width": thickness, "stroke-linecap": "butt",
        transform: `rotate(-90 ${size / 2} ${size / 2})`, "stroke-dashoffset": -offset,
      }, svg);
      const target = `${Math.max(len - gap, 0.01)} ${C}`;
      if (reduceMotion) arc.setAttribute("stroke-dasharray", target);
      else {
        arc.setAttribute("stroke-dasharray", `0 ${C}`);
        arc.style.transition = `stroke-dasharray .9s cubic-bezier(.2,.7,.2,1) ${i * 90}ms, opacity .15s`;
        settle(() => arc.setAttribute("stroke-dasharray", target));
      }
      arc.addEventListener("pointermove", (ev) => tip(s.label, `${s.value}${unit}`, ev.clientX, ev.clientY - 4));
      arc.addEventListener("pointerleave", hideTip);
      arcs.push(arc);
      offset += len;
    });

    const cv = svgEl("text", { class: "donut-center", x: size / 2, y: size / 2 + 4, "text-anchor": "middle" }, svg);
    cv.textContent = centerValue ?? total;
    const cl = svgEl("text", { class: "donut-sub", x: size / 2, y: size / 2 + 22, "text-anchor": "middle" }, svg);
    cl.textContent = centerLabel || "";

    const ul = document.createElement("ul");
    ul.className = "legend";
    segments.forEach((s, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<i style="background:${esc(s.color)}"></i><span>${esc(s.label)}</span><b>${esc(s.value)}</b>`;
      li.addEventListener("pointerenter", () => arcs.forEach((a, j) => a && (a.style.opacity = j === i ? 1 : 0.25)));
      li.addEventListener("pointerleave", () => arcs.forEach((a) => a && (a.style.opacity = 1)));
      ul.appendChild(li);
    });
    wrap.appendChild(ul);
  }

  /* ------------------------------------------------------------------ *
   * Horizontal bars (plain HTML, animated width)
   * ------------------------------------------------------------------ */
  function hbars(host, items) {
    const max = Math.max(...items.map((i) => i.value), 1);
    host.innerHTML = `<div class="hbar">${items
      .map((i) => `<div class="hbar-row"><div class="meta"><span>${esc(i.label)}</span><b>${esc(i.text)}</b></div><div class="hbar-track"><div class="hbar-fill" data-w="${((i.value / max) * 100).toFixed(1)}"></div></div></div>`)
      .join("")}</div>`;
    const fills = host.querySelectorAll(".hbar-fill");
    const apply = () => fills.forEach((f) => (f.style.width = f.dataset.w + "%"));
    if (reduceMotion) apply(); else settle(apply);
  }

  /* ------------------------------------------------------------------ *
   * Sparkline for the coral tile (white on coral)
   * ------------------------------------------------------------------ */
  function spark(host, values) {
    const W = 200, H = 56, pad = 4, n = values.length;
    const max = Math.max(...values, 1);
    const x = (i) => (n === 1 ? W / 2 : pad + ((W - pad * 2) * i) / (n - 1));
    const y = (v) => H - pad - ((H - pad * 2) * v) / max;
    let d = `M ${x(0)} ${y(values[0])}`;
    for (let i = 1; i < n; i++) {
      const mx = (x(i - 1) + x(i)) / 2;
      d += ` C ${mx} ${y(values[i - 1])}, ${mx} ${y(values[i])}, ${x(i)} ${y(values[i])}`;
    }
    host.innerHTML = `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
      <path d="${d} L ${x(n - 1)} ${H} L ${x(0)} ${H} Z" fill="rgba(255,255,255,.16)"/>
      <path d="${d}" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/></svg>`;
  }

  window.Charts = { line, bars, donut, hbars, spark, inrShort, inrFull };
})();
