/* Brightloop frontend: a dependency-free single-page app that reads and
 * writes everything through the backend REST API (/api/v1). */
(() => {
  "use strict";

  const API = (window.BRIGHTLOOP_API || "http://127.0.0.1:8000/api/v1").replace(/\/$/, "");

  /* ------------------------------------------------------------------ *
   * Small helpers
   * ------------------------------------------------------------------ */
  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN");
  const dateOnly = (v) => (v ? String(v).slice(0, 10) : "—");
  const dateTime = (v) => (v ? String(v).replace("T", " ").slice(0, 16) : "—");
  const title = (s) => String(s).replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  const today = () => new Date().toISOString().slice(0, 10);
  const badge = (s) => `<span class="badge b-${esc(s)}">${esc(s)}</span>`;
  const ICONS = {
    dashboard: '<rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/>',
    templates: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
    subscriptions: '<path d="M17 2l4 4-4 4"/><path d="M3 11V9a3 3 0 0 1 3-3h15"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v2a3 3 0 0 1-3 3H3"/>',
    invoices: '<path d="M5 3h14v18l-3-2-2 2-2-2-2 2-2-2-3 2z"/><path d="M9 8h6M9 12h6"/>',
    payments: '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20M6 15h3"/>',
    billing: '<circle cx="12" cy="12" r="9"/><path d="M10 8.5l5 3.5-5 3.5z"/>',
    taxes: '<path d="M19 5L5 19"/><circle cx="7" cy="7" r="2.5"/><circle cx="17" cy="17" r="2.5"/>',
    discounts: '<path d="M20.6 13.4l-7.2 7.2a2 2 0 0 1-2.8 0L3 13V3h10l7.6 7.6a2 2 0 0 1 0 2.8z"/><circle cx="7.5" cy="7.5" r="1.2"/>',
    products: '<path d="M21 8l-9-5-9 5v8l9 5 9-5z"/><path d="M3 8l9 5 9-5M12 13v8"/>',
    variants: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    plans: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
    users: '<path d="M16 20v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="8" r="3.5"/><path d="M22 20v-2a4 4 0 0 0-3-3.9M16 4.2a3.5 3.5 0 0 1 0 7"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    x: '<path d="M18 6L6 18M6 6l12 12"/>',
    menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
    logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.7 21a2 2 0 0 1-3.4 0"/>',
    chevron: '<path d="M6 9l6 6 6-6"/>',
  };
  const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ""}</svg>`;
  const yesNo = (b) => badge(b ? "yes" : "no").replace(">yes<", ">Yes<").replace(">no<", ">No<");

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* storage unavailable */ } },
    del(k) { try { localStorage.removeItem(k); } catch { /* storage unavailable */ } },
  };

  const state = { token: store.get("bl_token"), user: null, view: "dashboard", cache: {}, search: "" };

  function toast(msg, bad = false) {
    const t = document.createElement("div");
    t.className = "toast" + (bad ? " bad" : "");
    t.textContent = msg;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), bad ? 6000 : 3500);
  }

  /* ------------------------------------------------------------------ *
   * API client
   * ------------------------------------------------------------------ */
  function errorText(body, status) {
    const d = body && body.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e) => `${(e.loc || []).slice(1).join(".")}: ${e.msg}`).join("; ");
    return `Request failed (${status})`;
  }

  async function api(path, { method = "GET", body, params, raw = false, headers: extraHeaders } = {}) {
    let url = API + path;
    if (params) {
      const q = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => v !== undefined && v !== null && v !== "" && q.set(k, v));
      const qs = q.toString();
      if (qs) url += "?" + qs;
    }
    const headers = {};
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (state.token) headers.Authorization = "Bearer " + state.token;
    Object.assign(headers, extraHeaders);

    let res;
    try {
      res = await fetch(url, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
    } catch {
      throw new Error(`Cannot reach the backend at ${API}. Is it running?`);
    }
    if (res.status === 401 && state.token && !path.startsWith("/auth/")) {
      logout();
      throw new Error("Your session expired. Please sign in again.");
    }
    if (!res.ok) {
      let data = null;
      try { data = await res.json(); } catch { /* not JSON */ }
      throw new Error(errorText(data, res.status));
    }
    if (raw) return res.text();
    if (res.status === 204) return null;
    return res.json();
  }

  // The list endpoints for users/products/variants/plans are paginated (max 100).
  async function allPages(path, params = {}) {
    const out = [];
    let offset = 0;
    for (;;) {
      const page = await api(path, { params: { ...params, limit: 100, offset } });
      out.push(...page.items);
      offset += page.items.length;
      if (!page.items.length || offset >= page.total) return out;
    }
  }

  /* ------------------------------------------------------------------ *
   * Data loaders (cached until a mutation happens)
   * ------------------------------------------------------------------ */
  const loaders = {
    users: () => allPages("/users"),
    products: () => allPages("/products"),
    // Variants are listed per product and plans per variant, so crawl the tree.
    variants: async () => {
      const products = await data("products");
      return (await Promise.all(products.map((p) => allPages("/variants", { product_id: p.id })))).flat();
    },
    plans: async () => {
      const variants = await data("variants");
      return (await Promise.all(variants.map((v) => allPages("/plans", { variant_id: v.id })))).flat();
    },
    taxes: () => api("/taxes"),
    discounts: () => api("/discounts"),
    templates: () => api("/quotation-templates"),
    subscriptions: () => api("/subscriptions"),
    invoices: () => api("/invoices"),
    payments: () => api("/payments"),
    dashboard: () => api("/reports/dashboard"),
  };

  async function data(name, force = false) {
    if (force || !state.cache[name]) state.cache[name] = await loaders[name]();
    return state.cache[name];
  }
  const byId = (rows) => Object.fromEntries((rows || []).map((r) => [r.id, r]));
  const isStaff = () => state.user && state.user.role !== "customer";
  const isAdmin = () => state.user && state.user.role === "admin";

  /* ------------------------------------------------------------------ *
   * Generic rendering: tables, key/value grids, modals, forms
   * ------------------------------------------------------------------ */
  const MONEY_KEYS = new Set([
    "price_inr", "unit_price", "amount", "subtotal", "tax_total", "discount_total", "total_amount",
    "amount_paid", "balance_due", "tax_amount", "discount_amount", "total_recurring_amount",
    "min_purchase_amount", "sales_price", "cost_price",
  ]);

  function fmtValue(key, v) {
    if (v === null || v === undefined || v === "") return '<span class="muted">—</span>';
    if (typeof v === "boolean") return yesNo(v);
    if (MONEY_KEYS.has(key)) return inr(v);
    if (key === "status" || key === "role") return badge(v);
    if (typeof v === "string" && /^\d{4}-\d{2}-\d{2}T/.test(v)) return esc(dateTime(v));
    if (typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-/.test(v)) return `<span class="mono">${esc(v)}</span>`;
    return esc(v);
  }

  const isTechnical = (k) => k === "id" || k.endsWith("_id") || k === "created_at" || k === "updated_at";

  // Key/value grid. Ids and timestamps go in a collapsed "Technical details" block.
  function kv(obj, skip = []) {
    const cell = ([k, v]) => `<div><dt>${esc(title(k))}</dt><dd>${fmtValue(k, v)}</dd></div>`;
    const entries = Object.entries(obj).filter(([k, v]) => !skip.includes(k) && (v === null || typeof v !== "object"));
    const main = entries.filter(([k]) => !isTechnical(k)).map(cell).join("");
    const tech = entries.filter(([k]) => isTechnical(k)).map(cell).join("");
    return `<dl class="kv">${main}</dl>` +
      (tech ? `<details class="tech"><summary>Technical details</summary><dl class="kv">${tech}</dl></details>` : "");
  }

  // columns: [{ h, v: row => html, num?: bool }]
  function tableHtml(columns, rows, { clickable = false, empty = "No records yet." } = {}) {
    if (!rows.length) return `<div class="empty">${esc(empty)}</div>`;
    const head = columns.map((c) => `<th class="${c.num ? "num" : ""}">${esc(c.h)}</th>`).join("");
    const body = rows
      .map(
        (r, i) =>
          `<tr data-i="${i}" class="${clickable ? "clickable" : ""}">` +
          columns.map((c) => `<td class="${c.num ? "num" : ""}">${c.v(r)}</td>`).join("") +
          "</tr>"
      )
      .join("");
    return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function openModal({ heading, body, actions = [], narrow = false }) {
    closeModal();
    const bd = document.createElement("div");
    // Forms open in a narrow dialog, record details in a wide one.
    bd.className = "backdrop";
    bd.id = "modal";
    bd.innerHTML = `
      <div class="modal ${narrow ? "narrow" : "wide"}" role="dialog" aria-modal="true" aria-label="${esc(heading)}">
        <div class="modal-head"><h2>${esc(heading)}</h2><button class="btn round" data-close aria-label="Close">${icon("x")}</button></div>
        <div class="modal-body"></div>
        <div class="modal-foot"></div>
      </div>`;
    const bodyEl = $(".modal-body", bd);
    if (typeof body === "string") bodyEl.innerHTML = body; else bodyEl.appendChild(body);
    const foot = $(".modal-foot", bd);
    if (!actions.length) foot.remove();
    actions.forEach((a) => {
      const b = document.createElement("button");
      b.className = "btn " + (a.kind || "");
      b.textContent = a.label;
      b.addEventListener("click", async () => {
        b.disabled = true;
        try { await a.run(b); } catch (e) { toast(e.message, true); } finally { b.disabled = false; }
      });
      foot.appendChild(b);
    });
    bd.addEventListener("mousedown", (e) => { if (e.target === bd) closeModal(); });
    $("[data-close]", bd).addEventListener("click", closeModal);
    document.body.appendChild(bd);
    return bd;
  }
  function closeModal() { const m = $("#modal"); if (m) m.remove(); }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

  // fields: [{ name, label, type, options, req, value, hint, step, min }]
  function formModal({ heading, fields, submitLabel = "Save", onSubmit }) {
    const form = document.createElement("form");
    form.innerHTML =
      '<div class="err hidden"></div>' +
      fields
        .map((f) => {
          const id = "f_" + f.name;
          if (f.type === "checkbox")
            return `<label class="check"><input type="checkbox" id="${id}" name="${f.name}" ${f.value ? "checked" : ""}/> ${esc(f.label)}</label>`;
          let input;
          if (f.type === "select") {
            const opts = (f.options || [])
              .map(([v, l]) => `<option value="${esc(v)}" ${String(f.value) === String(v) ? "selected" : ""}>${esc(l)}</option>`)
              .join("");
            input = `<select id="${id}" name="${f.name}" ${f.req ? "required" : ""}>${f.req ? "" : '<option value="">—</option>'}${opts}</select>`;
          } else if (f.type === "textarea") {
            input = `<textarea id="${id}" name="${f.name}" rows="3">${esc(f.value ?? "")}</textarea>`;
          } else {
            input = `<input id="${id}" name="${f.name}" type="${f.type || "text"}" value="${esc(f.value ?? "")}"
                      ${f.req ? "required" : ""} ${f.step ? `step="${f.step}"` : ""} ${f.min !== undefined ? `min="${f.min}"` : ""}/>`;
          }
          return `<label class="field"><span>${esc(f.label)}${f.req ? " *" : ""}</span>${input}${f.hint ? `<small>${esc(f.hint)}</small>` : ""}</label>`;
        })
        .join("");

    const submit = async (btn) => {
      if (!form.reportValidity()) return;
      const out = {};
      fields.forEach((f) => {
        const el = form.elements[f.name];
        if (f.type === "checkbox") out[f.name] = el.checked;
        else if (el.value !== "") out[f.name] = f.type === "number" ? Number(el.value) : el.value;
      });
      const errBox = $(".err", form);
      errBox.classList.add("hidden");
      try {
        await onSubmit(out);
        closeModal();
      } catch (e) {
        errBox.textContent = e.message;
        errBox.classList.remove("hidden");
      }
    };
    form.addEventListener("submit", (e) => { e.preventDefault(); submit(); });
    openModal({ heading, body: form, narrow: true, actions: [{ label: submitLabel, kind: "primary", run: submit }] });
  }

  async function mutate(promise, okMsg) {
    const result = await promise;
    state.cache = {};
    if (okMsg) toast(okMsg);
    await render();
    return result;
  }

  /* ------------------------------------------------------------------ *
   * Views
   * ------------------------------------------------------------------ */
  const ALL = ["admin", "staff", "customer"];
  const STAFF = ["admin", "staff"];

  const NAV = [
    { group: "Overview", items: [{ id: "dashboard", label: "Dashboard", roles: ALL }] },
    {
      group: "Sales",
      items: [
        { id: "templates", label: "Quotation Templates", roles: ALL, src: "templates" },
        { id: "subscriptions", label: "Subscriptions", roles: ALL, src: "subscriptions" },
      ],
    },
    {
      group: "Finance",
      items: [
        { id: "invoices", label: "Invoices", roles: ALL, src: "invoices" },
        { id: "payments", label: "Payments", roles: ALL, src: "payments" },
        { id: "billing", label: "Billing Run", roles: STAFF },
        { id: "taxes", label: "Taxes", roles: ALL, src: "taxes" },
        { id: "discounts", label: "Discounts", roles: STAFF, src: "discounts" },
      ],
    },
    {
      group: "Catalog",
      items: [
        { id: "products", label: "Products", roles: ALL, src: "products" },
        { id: "variants", label: "Variants", roles: ALL, src: "variants" },
        { id: "plans", label: "Plans", roles: ALL, src: "plans" },
      ],
    },
    { group: "Admin", items: [{ id: "users", label: "Users", roles: ["admin"], src: "users" }] },
  ];
  const navItems = () => NAV.flatMap((g) => g.items).filter((i) => i.roles.includes(state.user.role));

  /* ---- lookup helpers shared by several views ---- */
  async function catalog() {
    const [products, variants, plans] = await Promise.all([data("products"), data("variants"), data("plans")]);
    return { products, variants, plans, P: byId(products), V: byId(variants), L: byId(plans) };
  }
  function variantLabel(v, P) {
    return `${(P[v.product_id] || {}).name || "Product"} / ${v.name}`;
  }
  function planLabel(pl, c) {
    const v = c.V[pl.variant_id];
    return `${v ? variantLabel(v, c.P) + " — " : ""}${pl.name}`;
  }
  function intervalText(pl) {
    const n = pl.interval_count;
    return `every ${n > 1 ? n + " " : ""}${pl.billing_interval}${n > 1 ? "s" : ""}`;
  }
  // Customers a staff user can pick from. Only admins may list /users, so
  // staff get the customers that already appear on subscriptions/invoices.
  async function customerOptions() {
    if (!isStaff()) return [[state.user.id, `${state.user.name} (me)`]];
    const map = new Map();
    if (isAdmin()) (await data("users")).filter((u) => u.role === "customer").forEach((u) => map.set(u.id, `${u.name} <${u.email}>`));
    [...(await data("subscriptions")), ...(await data("invoices"))].forEach((r) => {
      if (r.customer_id && !map.has(r.customer_id)) map.set(r.customer_id, `${r.customer_name || "Customer"} <${r.customer_email || r.customer_id}>`);
    });
    return [...map.entries()];
  }

  /* ---- generic list-view factory ---- */
  function listView(cfg) {
    return async (root) => {
      root.innerHTML = tableSkeleton();
      const rows = await cfg.rows();
      root.innerHTML = `
        <div class="page-head">
          <div><h1>${esc(cfg.heading)}</h1><p>${esc(cfg.blurb)}</p></div>
          <div class="toolbar">
            <label class="search">${icon("search")}<input type="search" placeholder="Search…" value="${esc(state.search)}" aria-label="Search" /></label>
            <button class="btn" data-refresh title="Reload from the database">${icon("refresh")}</button>
            ${cfg.create && cfg.create.roles.includes(state.user.role) ? `<button class="btn primary" data-create>${icon("plus")}${esc(cfg.create.label.replace(/^\+\s*/, ""))}</button>` : ""}
          </div>
        </div>
        <div class="panel"><div data-table></div><div class="tbl-foot" data-foot></div></div>`;
      const draw = () => {
        const q = state.search.toLowerCase();
        const shown = q ? rows.filter((r) => JSON.stringify(r).toLowerCase().includes(q)) : rows;
        const host = $("[data-table]", root);
        host.innerHTML = tableHtml(cfg.columns, shown, { clickable: !!cfg.detail, empty: cfg.empty });
        $("[data-foot]", root).textContent = `${shown.length} of ${rows.length} record${rows.length === 1 ? "" : "s"}`;
        if (cfg.detail) host.querySelectorAll("tbody tr").forEach((tr) => tr.addEventListener("click", () => cfg.detail(shown[+tr.dataset.i])));
      };
      draw();
      $("input[type=search]", root).addEventListener("input", (e) => { state.search = e.target.value; draw(); });
      $("[data-refresh]", root).addEventListener("click", () => { state.cache = {}; render(); });
      const c = $("[data-create]", root);
      if (c) c.addEventListener("click", cfg.create.run);
    };
  }

  /* ---- Users ---- */
  const usersView = listView({
    heading: "Users",
    blurb: "Every account in the platform (admin only).",
    rows: () => data("users"),
    columns: [
      { h: "Name", v: (r) => esc(r.name) },
      { h: "Email", v: (r) => esc(r.email) },
      { h: "Role", v: (r) => badge(r.role) },
      { h: "Active", v: (r) => yesNo(r.is_active) },
      { h: "Created", v: (r) => esc(dateOnly(r.created_at)) },
      { h: "ID", v: (r) => `<span class="mono">${esc(r.id.slice(0, 8))}…</span>` },
    ],
    detail: (u) =>
      openModal({
        heading: u.name,
        body: kv(u),
        actions: u.id === state.user.id ? [] : [
          { label: u.is_active ? "Deactivate" : "Activate", kind: u.is_active ? "danger" : "primary",
            run: () => mutate(api(`/users/${u.id}/${u.is_active ? "deactivate" : "activate"}`, { method: "POST" }), "User updated").then(closeModal) },
          { label: "Change role…", run: () => changeRole(u) },
        ],
      }),
  });
  function changeRole(u) {
    formModal({
      heading: `Role for ${u.name}`,
      fields: [{ name: "role", label: "Role", type: "select", req: true, value: u.role, options: [["customer", "customer"], ["staff", "staff"], ["admin", "admin"]] }],
      onSubmit: (v) => mutate(api(`/users/${u.id}/role`, { method: "PATCH", body: v }), "Role updated"),
    });
  }

  /* ---- Products / Variants / Plans ---- */
  async function deleteBtn(path, what, after) {
    if (!confirm(`Delete this ${what}? This cannot be undone.`)) return;
    await mutate(api(path, { method: "DELETE" }), `${title(what)} deleted`);
    if (after) after();
  }

  const productsView = listView({
    heading: "Products",
    blurb: "What you sell. Each product has variants, and each variant has plans.",
    rows: async () => { await catalog(); return data("products"); },
    columns: [
      { h: "SKU", v: (r) => `<span class="mono">${esc(r.sku)}</span>` },
      { h: "Name", v: (r) => esc(r.name) },
      { h: "Description", v: (r) => esc(r.description || "—") },
      { h: "Variants", num: true, v: (r) => state.cache.variants.filter((v) => v.product_id === r.id).length },
      { h: "Active", v: (r) => yesNo(r.is_active) },
      { h: "Created", v: (r) => esc(dateOnly(r.created_at)) },
    ],
    create: { label: "+ New product", roles: ["admin"], run: () => formModal({
      heading: "New product",
      fields: [
        { name: "sku", label: "SKU", req: true, hint: "Letters, digits, - or _ (saved in uppercase), e.g. BL-CRM" },
        { name: "name", label: "Name", req: true },
        { name: "description", label: "Description", type: "textarea" },
      ],
      onSubmit: (v) => mutate(api("/products", { method: "POST", body: v }), "Product created"),
    }) },
    detail: async (p) => {
      const c = await catalog();
      const vars = c.variants.filter((v) => v.product_id === p.id);
      const body = kv(p) + `<h3 class="section-title">Variants & plans</h3>` +
        (vars.length
          ? vars.map((v) => {
              const pls = c.plans.filter((pl) => pl.variant_id === v.id);
              return `<div class="inner-table"><div style="padding:8px 14px"><strong>${esc(v.name)}</strong> <span class="mono muted">${esc(v.sku)}</span></div>` +
                tableHtml([
                  { h: "Plan", v: (r) => esc(r.name) },
                  { h: "Billing", v: (r) => esc(intervalText(r)) },
                  { h: "Price", num: true, v: (r) => inr(r.price_inr) },
                  { h: "Trial", num: true, v: (r) => r.trial_days + " d" },
                  { h: "Active", v: (r) => yesNo(r.is_active) },
                ], pls, { empty: "No plans for this variant." }) + "</div>";
            }).join("")
          : '<div class="empty">No variants yet.</div>');
      openModal({ heading: p.name, body, actions: isAdmin() ? [
        { label: p.is_active ? "Deactivate" : "Activate", run: () => mutate(api(`/products/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }), "Product updated").then(closeModal) },
        { label: "Delete", kind: "danger", run: () => deleteBtn(`/products/${p.id}`, "product", closeModal) },
      ] : [] });
    },
  });

  const variantsView = listView({
    heading: "Variants",
    blurb: "Editions or options of a product (e.g. Standard, Pro).",
    rows: async () => { await catalog(); return data("variants"); },
    columns: [
      { h: "SKU", v: (r) => `<span class="mono">${esc(r.sku)}</span>` },
      { h: "Variant", v: (r) => esc(r.name) },
      { h: "Product", v: (r) => esc((byId(state.cache.products)[r.product_id] || {}).name || "—") },
      { h: "Plans", num: true, v: (r) => state.cache.plans.filter((p) => p.variant_id === r.id).length },
      { h: "Active", v: (r) => yesNo(r.is_active) },
      { h: "Created", v: (r) => esc(dateOnly(r.created_at)) },
    ],
    create: { label: "+ New variant", roles: ["admin"], run: async () => {
      const products = await data("products");
      formModal({
        heading: "New variant",
        fields: [
          { name: "product_id", label: "Product", type: "select", req: true, options: products.map((p) => [p.id, p.name]) },
          { name: "sku", label: "SKU", req: true },
          { name: "name", label: "Name", req: true },
          { name: "description", label: "Description", type: "textarea" },
        ],
        onSubmit: (v) => mutate(api("/variants", { method: "POST", body: v }), "Variant created"),
      });
    } },
    detail: (v) => openModal({
      heading: v.name,
      body: kv(v),
      actions: isAdmin() ? [
        { label: v.is_active ? "Deactivate" : "Activate", run: () => mutate(api(`/variants/${v.id}`, { method: "PATCH", body: { is_active: !v.is_active } }), "Variant updated").then(closeModal) },
        { label: "Delete", kind: "danger", run: () => deleteBtn(`/variants/${v.id}`, "variant", closeModal) },
      ] : [],
    }),
  });

  const plansView = listView({
    heading: "Plans",
    blurb: "Recurring prices. A plan belongs to one variant.",
    rows: async () => { await catalog(); return data("plans"); },
    columns: [
      { h: "Plan", v: (r) => esc(r.name) },
      { h: "Product / Variant", v: (r) => { const v = byId(state.cache.variants)[r.variant_id]; return esc(v ? variantLabel(v, byId(state.cache.products)) : "—"); } },
      { h: "Billing", v: (r) => esc(intervalText(r)) },
      { h: "Price", num: true, v: (r) => inr(r.price_inr) },
      { h: "Trial", num: true, v: (r) => r.trial_days + " d" },
      { h: "Active", v: (r) => yesNo(r.is_active) },
    ],
    create: { label: "+ New plan", roles: ["admin"], run: async () => {
      const c = await catalog();
      formModal({
        heading: "New plan",
        fields: [
          { name: "variant_id", label: "Variant", type: "select", req: true, options: c.variants.map((v) => [v.id, variantLabel(v, c.P)]) },
          { name: "name", label: "Name", req: true },
          { name: "billing_interval", label: "Billing interval", type: "select", req: true, value: "month", options: ["day", "week", "month", "year"].map((x) => [x, x]) },
          { name: "interval_count", label: "Every N intervals", type: "number", req: true, value: 1, min: 1 },
          { name: "price_inr", label: "Price (₹, whole rupees)", type: "number", req: true, min: 0 },
          { name: "trial_days", label: "Trial days", type: "number", value: 0, min: 0 },
        ],
        onSubmit: (v) => mutate(api("/plans", { method: "POST", body: v }), "Plan created"),
      });
    } },
    detail: (pl) => openModal({
      heading: pl.name,
      body: kv(pl),
      actions: isAdmin() ? [
        { label: pl.is_active ? "Deactivate" : "Activate", run: () => mutate(api(`/plans/${pl.id}`, { method: "PATCH", body: { is_active: !pl.is_active } }), "Plan updated").then(closeModal) },
        { label: "Delete", kind: "danger", run: () => deleteBtn(`/plans/${pl.id}`, "plan", closeModal) },
      ] : [],
    }),
  });

  /* ---- Taxes / Discounts ---- */
  const taxesView = listView({
    heading: "Taxes",
    blurb: "Tax rates that can be attached to subscription lines.",
    rows: () => data("taxes"),
    columns: [
      { h: "Name", v: (r) => esc(r.name) },
      { h: "Rate", num: true, v: (r) => esc(r.rate) + " %" },
      { h: "Active", v: (r) => yesNo(r.is_active) },
      { h: "Created", v: (r) => esc(dateOnly(r.created_at)) },
    ],
    create: { label: "+ New tax", roles: ["admin"], run: () => formModal({
      heading: "New tax",
      fields: [
        { name: "name", label: "Name", req: true, value: "GST 18%" },
        { name: "rate", label: "Rate (%)", type: "number", step: "0.01", req: true, value: 18, min: 0 },
        { name: "is_active", label: "Active", type: "checkbox", value: true },
      ],
      onSubmit: (v) => mutate(api("/taxes", { method: "POST", body: v }), "Tax created"),
    }) },
    detail: (t) => openModal({ heading: t.name, body: kv(t) }),
  });

  const discountsView = listView({
    heading: "Discounts",
    blurb: "Promo codes and rules applied to subscriptions at billing time.",
    rows: () => data("discounts"),
    columns: [
      { h: "Code", v: (r) => `<span class="mono">${esc(r.code)}</span>` },
      { h: "Description", v: (r) => esc(r.description || "—") },
      { h: "Value", num: true, v: (r) => (r.discount_type === "percentage" ? esc(r.discount_value) + " %" : inr(r.discount_value)) },
      { h: "Min purchase", num: true, v: (r) => inr(r.min_purchase_amount) },
      { h: "Used", num: true, v: (r) => `${r.used_count}${r.max_uses ? " / " + r.max_uses : ""}` },
      { h: "Valid", v: (r) => `${esc(dateOnly(r.start_date))} → ${esc(dateOnly(r.end_date))}` },
      { h: "Active", v: (r) => yesNo(r.is_active) },
    ],
    create: { label: "+ New discount", roles: ["admin"], run: () => formModal({
      heading: "New discount",
      fields: [
        { name: "code", label: "Code", req: true, hint: "e.g. STARTUP20" },
        { name: "description", label: "Description" },
        { name: "discount_type", label: "Type", type: "select", req: true, value: "percentage", options: [["percentage", "Percentage"], ["fixed", "Fixed amount (₹)"]] },
        { name: "discount_value", label: "Value", type: "number", step: "0.01", req: true, min: 0 },
        { name: "min_purchase_amount", label: "Minimum purchase (₹)", type: "number", value: 0, min: 0 },
        { name: "min_quantity", label: "Minimum quantity", type: "number", value: 0, min: 0 },
        { name: "start_date", label: "Valid from", type: "date" },
        { name: "end_date", label: "Valid until", type: "date" },
        { name: "max_uses", label: "Max uses", type: "number", min: 1 },
        { name: "is_active", label: "Active", type: "checkbox", value: true },
      ],
      onSubmit: (v) => mutate(api("/discounts", { method: "POST", body: v }), "Discount created"),
    }) },
    detail: (d) => openModal({ heading: d.code, body: kv(d) }),
  });

  /* ---- Quotation templates ---- */
  const templatesView = listView({
    heading: "Quotation Templates",
    blurb: "Pre-built quotes. Generate a draft subscription from a template in one click.",
    rows: async () => { await catalog(); return data("templates"); },
    columns: [
      { h: "Name", v: (r) => esc(r.name) },
      { h: "Description", v: (r) => esc(r.description || "—") },
      { h: "Plan", v: (r) => { const p = byId(state.cache.plans)[r.plan_id]; return esc(p ? p.name : "—"); } },
      { h: "Valid days", num: true, v: (r) => r.valid_days },
      { h: "Lines", num: true, v: (r) => (r.lines || []).length },
      { h: "Active", v: (r) => yesNo(r.is_active) },
    ],
    detail: async (t) => {
      const c = await catalog();
      const taxes = byId(await data("taxes"));
      const lines = tableHtml([
        { h: "Product", v: (l) => esc((c.P[l.product_id] || {}).name || l.product_name || "—") },
        { h: "Variant", v: (l) => esc((c.V[l.variant_id] || {}).name || l.variant_name || "—") },
        { h: "Qty", num: true, v: (l) => l.quantity },
        { h: "Unit price", num: true, v: (l) => inr(l.unit_price) },
        { h: "Tax", v: (l) => esc((taxes[l.tax_id] || {}).name || "—") },
      ], t.lines || [], { empty: "This template has no lines." });
      const plan = c.L[t.plan_id];
      openModal({
        heading: t.name,
        body: kv(t, ["plan_id"]) + `<dl class="kv"><div><dt>Plan</dt><dd>${esc(plan ? planLabel(plan, c) : "—")}</dd></div></dl>` +
          `<h3 class="section-title">Lines</h3><div class="inner-table">${lines}</div>`,
        actions: [{ label: "Create quote from this template", kind: "primary", run: () => createQuote(t) }],
      });
    },
  });
  async function createQuote(t) {
    if (!isStaff()) {
      const sub = await mutate(api(`/quotation-templates/${t.id}/create-quote`, { method: "POST" }), "Quote created");
      closeModal(); state.view = "subscriptions"; await render(); return sub;
    }
    const customers = await customerOptions();
    formModal({
      heading: `Quote from "${t.name}"`,
      submitLabel: "Create quote",
      fields: [{ name: "customer_id", label: "Customer", type: "select", req: true, options: customers }],
      onSubmit: async (v) => {
        await mutate(api(`/quotation-templates/${t.id}/create-quote`, { method: "POST", params: { customer_id: v.customer_id } }), "Quote created");
        state.view = "subscriptions"; await render();
      },
    });
  }

  /* ---- Subscriptions ---- */
  const subscriptionsView = listView({
    heading: "Subscriptions",
    blurb: "Customers' recurring agreements and where each one is in its lifecycle.",
    rows: async () => { await catalog(); return data("subscriptions"); },
    columns: [
      { h: "Number", v: (r) => `<span class="mono">${esc(r.subscription_number)}</span>` },
      { h: "Customer", v: (r) => esc(r.customer_name || r.customer_id) },
      { h: "Plan", v: (r) => esc(r.plan_name || (byId(state.cache.plans)[r.plan_id] || {}).name || "—") },
      { h: "Status", v: (r) => badge(r.status) },
      { h: "Start", v: (r) => esc(dateOnly(r.start_date)) },
      { h: "Next billing", v: (r) => esc(dateOnly(r.next_billing_date)) },
      { h: "Expires", v: (r) => esc(dateOnly(r.expiry_date)) },
      { h: "Terms", v: (r) => esc(r.payment_terms) },
      { h: "Recurring", num: true, v: (r) => inr(r.total_recurring_amount) },
    ],
    create: { label: "+ New subscription", roles: ALL, run: newSubscription },
    detail: (s) => subscriptionDetail(s),
  });

  async function newSubscription() {
    const [c, customers, discounts, taxes] = await Promise.all([
      catalog(), customerOptions(), isStaff() ? data("discounts") : Promise.resolve([]), data("taxes"),
    ]);
    formModal({
      heading: "New subscription",
      fields: [
        { name: "customer_id", label: "Customer", type: "select", req: true, options: customers, value: isStaff() ? "" : state.user.id },
        { name: "plan_id", label: "Plan", type: "select", req: true, options: c.plans.filter((p) => p.is_active).map((p) => [p.id, `${planLabel(p, c)} (${inr(p.price_inr)} ${intervalText(p)})`]) },
        { name: "start_date", label: "Start date", type: "date", req: true, value: today() },
        { name: "expiry_date", label: "Expiry date", type: "date" },
        { name: "payment_terms", label: "Payment terms", type: "select", req: true, value: "immediate", options: [["immediate", "Immediate"], ["net15", "Net 15"], ["net30", "Net 30"], ["net60", "Net 60"]] },
        ...(isStaff() ? [{ name: "discount_id", label: "Discount", type: "select", options: discounts.map((d) => [d.id, d.code]) }] : []),
        // Pricing is staff-only. A customer's request is billed at the plan price.
        ...(isStaff() ? [
          { name: "variant_id", label: "Line item (optional): variant", type: "select", options: c.variants.map((v) => [v.id, variantLabel(v, c.P)]), hint: "Leave empty to bill the plan price." },
          { name: "quantity", label: "Quantity", type: "number", value: 1, min: 1 },
          { name: "unit_price", label: "Unit price (₹)", type: "number", min: 0 },
          { name: "tax_id", label: "Tax", type: "select", options: taxes.map((t) => [t.id, `${t.name} (${t.rate}%)`]) },
        ] : []),
        { name: "auto_close", label: "Auto-close at expiry", type: "checkbox" },
        { name: "notes", label: "Notes", type: "textarea" },
      ],
      onSubmit: async (v) => {
        const { variant_id, quantity, unit_price, tax_id, ...rest } = v;
        const body = { ...rest, lines: [] };
        if (variant_id) {
          if (unit_price === undefined) throw new Error("Enter a unit price for the line item.");
          const variant = c.V[variant_id];
          body.lines.push({ product_id: variant.product_id, variant_id, quantity: quantity || 1, unit_price, ...(tax_id ? { tax_id } : {}) });
        }
        await mutate(api("/subscriptions", { method: "POST", body }), isStaff() ? "Subscription created" : "Request sent. Our team will review it.");
      },
    });
  }

  const SUB_ACTIONS = {
    draft: [["to-quotation", "Convert to quotation"]],
    quotation: [["confirm", "Confirm"]],
    confirmed: [["activate", "Activate", "staff"]],
    active: [["pause", "Pause"], ["renew", "Renew…"], ["close", "Close", "danger"]],
    paused: [["resume", "Resume"], ["close", "Close", "danger"]],
    closed: [["renew", "Renew…"]],
  };

  async function subscriptionDetail(s) {
    s = await api(`/subscriptions/${s.id}`);
    const invs = (await data("invoices")).filter((i) => i.subscription_id === s.id);
    const lines = tableHtml([
      { h: "Product", v: (l) => esc(l.product_name || "—") },
      { h: "Variant", v: (l) => esc(l.variant_name || "—") },
      { h: "Qty", num: true, v: (l) => l.quantity },
      { h: "Unit price", num: true, v: (l) => inr(l.unit_price) },
      { h: "Tax", num: true, v: (l) => l.tax_rate + " %" },
      { h: "Amount", num: true, v: (l) => inr(l.amount) },
    ], s.lines || [], { empty: "No line items. Billing uses the plan price." });
    const invTable = tableHtml([
      { h: "Invoice", v: (i) => `<span class="mono">${esc(i.invoice_number)}</span>` },
      { h: "Period", v: (i) => `${esc(dateOnly(i.billing_period_start))} → ${esc(dateOnly(i.billing_period_end))}` },
      { h: "Status", v: (i) => badge(i.status) },
      { h: "Total", num: true, v: (i) => inr(i.total_amount) },
    ], invs, { empty: "Not billed yet." });
    const actions = (SUB_ACTIONS[s.status] || [])
      .filter(([, , flag]) => flag !== "staff" || isStaff())
      .map(([act, label, flag]) => ({
        label, kind: flag === "danger" ? "danger" : "",
        run: async () => {
          let params;
          if (act === "renew") {
            const m = prompt("Renew for how many additional months?", "12");
            if (!m) return;
            params = { additional_months: Number(m) };
          }
          await mutate(api(`/subscriptions/${s.id}/${act}`, { method: "POST", params }), `Subscription ${act.replace("-", " ")} done`);
          closeModal();
        },
      }));
    openModal({
      heading: `${s.subscription_number} · ${s.customer_name || ""}`,
      body: kv(s, ["lines"]) + `<h3 class="section-title">Line items</h3><div class="inner-table">${lines}</div>` +
        `<h3 class="section-title">Invoices</h3><div class="inner-table">${invTable}</div>`,
      actions,
    });
  }

  /* ---- Invoices ---- */
  const invoiceStatusBadge = (i) => badge(i.status) + (i.is_overdue ? " " + badge("overdue") : "");

  const invoicesView = listView({
    heading: "Invoices",
    blurb: "Everything billed, what has been paid and what is still due.",
    rows: () => data("invoices"),
    columns: [
      { h: "Number", v: (r) => `<span class="mono">${esc(r.invoice_number)}</span>` },
      { h: "Customer", v: (r) => esc(r.customer_name || r.customer_id) },
      { h: "Subscription", v: (r) => `<span class="mono">${esc(r.subscription_number || "—")}</span>` },
      { h: "Status", v: invoiceStatusBadge },
      { h: "Issued", v: (r) => esc(dateOnly(r.issue_date)) },
      { h: "Due", v: (r) => esc(dateOnly(r.due_date)) },
      { h: "Total", num: true, v: (r) => inr(r.total_amount) },
      { h: "Paid", num: true, v: (r) => inr(r.amount_paid) },
      { h: "Balance", num: true, v: (r) => inr(r.balance_due) },
    ],
    detail: (i) => invoiceDetail(i),
  });

  async function invoiceDetail(i) {
    i = await api(`/invoices/${i.id}`);
    const pays = (await data("payments")).filter((p) => p.invoice_id === i.id);
    const lines = tableHtml([
      { h: "Description", v: (l) => esc(l.description) },
      { h: "Qty", num: true, v: (l) => l.quantity },
      { h: "Unit price", num: true, v: (l) => inr(l.unit_price) },
      { h: "Tax", num: true, v: (l) => `${l.tax_rate}% (${inr(l.tax_amount)})` },
      { h: "Discount", num: true, v: (l) => inr(l.discount_amount) },
      { h: "Total", num: true, v: (l) => inr(l.total_amount) },
    ], i.lines || [], { empty: "No lines." });
    const payTable = tableHtml([
      { h: "Payment", v: (p) => `<span class="mono">${esc(p.payment_number)}</span>` },
      { h: "Date", v: (p) => esc(dateOnly(p.payment_date)) },
      { h: "Method", v: (p) => esc(title(p.payment_method)) },
      { h: "Amount", num: true, v: (p) => inr(p.amount) },
    ], pays, { empty: "No payments recorded." });
    const act = (label, path, msg, kind = "") => ({
      label, kind, run: async () => { await mutate(api(path, { method: "POST" }), msg); closeModal(); },
    });
    const actions = [{ label: "Print / PDF", run: () => printInvoice(i.id) }];
    if (isStaff() && i.status === "draft") actions.push(act("Confirm", `/invoices/${i.id}/confirm`, "Invoice confirmed"));
    if (isStaff() && i.status !== "cancelled") actions.push(act("Mark as sent", `/invoices/${i.id}/send`, "Invoice marked as sent"));
    if (isStaff() && i.status !== "cancelled" && i.status !== "paid") actions.push(act("Cancel", `/invoices/${i.id}/cancel`, "Invoice cancelled", "danger"));
    if (i.status !== "cancelled" && i.status !== "paid" && i.balance_due > 0)
      actions.push({ label: "Record payment", kind: "primary", run: () => payInvoice(i) });
    openModal({
      heading: `${i.invoice_number} · ${i.customer_name || ""}`,
      body: `<div style="margin-bottom:12px">${invoiceStatusBadge(i)}</div>` + kv(i, ["lines", "status", "is_overdue"]) +
        `<h3 class="section-title">Lines</h3><div class="inner-table">${lines}</div>` +
        `<h3 class="section-title">Payments</h3><div class="inner-table">${payTable}</div>`,
      actions,
    });
  }

  async function printInvoice(id) {
    const html = await api(`/invoices/${id}/print`, { raw: true });
    const w = window.open("", "_blank");
    if (!w) throw new Error("Pop-up blocked. Allow pop-ups to print the invoice.");
    w.document.open(); w.document.write(html); w.document.close();
  }

  function payInvoice(i) {
    formModal({
      heading: `Pay ${i.invoice_number}`,
      submitLabel: "Record payment",
      fields: [
        { name: "amount", label: `Amount (₹) — balance ${inr(i.balance_due)}`, type: "number", req: true, min: 1, value: i.balance_due },
        { name: "payment_method", label: "Method", type: "select", req: true, value: isStaff() ? "bank_transfer" : "portal_online",
          options: ["bank_transfer", "credit_card", "upi", "cash", "cheque", "portal_online"].map((m) => [m, title(m)]) },
        { name: "payment_date", label: "Payment date", type: "date", req: true, value: today() },
        { name: "note", label: "Note" },
      ],
      onSubmit: async (v) => {
        await mutate(api("/payments", { method: "POST", body: { ...v, invoice_id: i.id } }), "Payment recorded");
        closeModal();
      },
    });
  }

  /* ---- Payments ---- */
  const paymentsView = listView({
    heading: "Payments",
    blurb: "Money received against invoices.",
    rows: () => data("payments"),
    columns: [
      { h: "Number", v: (r) => `<span class="mono">${esc(r.payment_number)}</span>` },
      { h: "Invoice", v: (r) => `<span class="mono">${esc(r.invoice_number || r.invoice_id)}</span>` },
      { h: "Customer", v: (r) => esc(r.customer_name || "—") },
      { h: "Method", v: (r) => esc(title(r.payment_method)) },
      { h: "Date", v: (r) => esc(dateOnly(r.payment_date)) },
      { h: "Note", v: (r) => esc(r.note || "—") },
      { h: "Amount", num: true, v: (r) => inr(r.amount) },
    ],
    detail: (p) => openModal({ heading: p.payment_number, body: kv(p) }),
  });

  /* ---- Billing run ---- */
  async function billingView(root) {
    root.innerHTML = `
      <div class="page-head"><div><h1>Billing Run</h1>
        <p>Create invoices for every active subscription that is due. Running it twice never double-bills the same period.</p></div></div>
      <div class="panel"><div class="panel-body">
        <div class="toolbar">
          <label class="field" style="margin:0"><span>Billing date</span><input type="date" id="bdate" value="${today()}" /></label>
          <button class="btn" id="bprev">Preview (dry run)</button>
          <button class="btn primary" id="brun">Run billing</button>
        </div>
      </div></div>
      <div id="bresult"></div>`;
    const go = async (dry) => {
      const res = await api("/billing/run", { method: "POST", body: { billing_date: $("#bdate").value, dry_run: dry } });
      if (!dry) state.cache = {};
      $("#bresult").innerHTML = `
        <div class="cards">
          <div class="card"><div class="label">Subscriptions checked</div><div class="value">${res.processed_count}</div></div>
          <div class="card"><div class="label">${dry ? "Invoices to create" : "Invoices created"}</div><div class="value">${res.invoices_created}</div></div>
          <div class="card"><div class="label">Skipped (not due)</div><div class="value">${res.skipped_count}</div></div>
          <div class="card"><div class="label">${dry ? "Would bill" : "Total billed"}</div><div class="value">${inr(res.total_billed)}</div></div>
        </div>` +
        (res.invoices.length
          ? `<div class="panel">${tableHtml([
              { h: "Number", v: (r) => `<span class="mono">${esc(r.invoice_number)}</span>` },
              { h: "Customer", v: (r) => esc(r.customer_name || "—") },
              { h: "Period", v: (r) => `${esc(dateOnly(r.billing_period_start))} → ${esc(dateOnly(r.billing_period_end))}` },
              { h: "Due", v: (r) => esc(dateOnly(r.due_date)) },
              { h: "Total", num: true, v: (r) => inr(r.total_amount) },
            ], res.invoices)}</div>`
          : "");
      toast(dry ? "Preview ready (nothing was saved)" : `${res.invoices_created} invoice(s) created`);
    };
    $("#bprev").addEventListener("click", (e) => run(e.target, () => go(true)));
    $("#brun").addEventListener("click", (e) => {
      if (confirm(`Create invoices for all subscriptions due on ${$("#bdate").value}?`)) run(e.target, () => go(false));
    });
  }
  async function run(btn, fn) {
    btn.disabled = true;
    try { await fn(); } catch (e) { toast(e.message, true); } finally { btn.disabled = false; }
  }

  /* ---- Dashboard ---- */
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  function lastMonths(n) {
    const now = new Date();
    return Array.from({ length: n }, (_, k) => {
      const d = new Date(now.getFullYear(), now.getMonth() - (n - 1 - k), 1);
      return { key: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`, label: MONTHS[d.getMonth()] };
    });
  }
  const sumByMonth = (rows, dateKey, valueKey, months) =>
    months.map((m) => rows.filter((r) => String(r[dateKey] || "").slice(0, 7) === m.key).reduce((a, r) => a + Number(r[valueKey] || 0), 0));

  function greeting() {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  }
  function daysFromNow(dateStr) {
    const t = new Date(); t.setHours(0, 0, 0, 0);
    return Math.round((new Date(String(dateStr).slice(0, 10) + "T00:00:00") - t) / 864e5);
  }
  function relDays(n) {
    if (n === 0) return "Today";
    if (n === 1) return "Tomorrow";
    if (n === -1) return "Yesterday";
    return n < 0 ? `${-n} days ago` : `In ${n} days`;
  }
  function timeAgo(iso) {
    const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (mins < 60) return `${mins || 1}m ago`;
    if (mins < 1440) return `${Math.round(mins / 60)}h ago`;
    return `${Math.round(mins / 1440)}d ago`;
  }
  async function fetchHealth() {
    try {
      const r = await fetch(API.replace(/\/api\/v1$/, "") + "/health");
      return r.ok ? await r.json() : null;
    } catch { return null; }
  }

  function dashSkeleton() {
    const t = (cls, lines = 3) => `<div class="sk-tile ${cls}"><div class="sk line" style="width:40%"></div>${Array.from({ length: lines }, (_, i) => `<div class="sk line" style="width:${90 - i * 18}%;height:${i ? 14 : 30}px"></div>`).join("")}</div>`;
    return `<div class="page-head"><div class="sk line" style="width:260px;height:34px"></div></div>
      <div class="bento">${t("s-8", 3)}${t("s-4", 3)}${t("s-8", 5)}${t("s-4", 5)}${t("s-3", 2)}${t("s-3", 2)}${t("s-3", 2)}${t("s-3", 2)}</div>`;
  }
  function tableSkeleton() {
    return `<div class="page-head"><div class="sk line" style="width:220px;height:34px"></div></div>
      <div class="panel" style="padding:24px;display:grid;gap:16px">${Array.from({ length: 6 }, () => '<div class="sk line" style="height:18px"></div>').join("")}</div>`;
  }

  /* ---- dashboards: one per role, all built from real API data ---- */

  const stat = (go, ic, label, value, foot, warn) =>
    `<button class="tile stat s-3" data-go="${go}"><div class="top"><span class="label">${esc(label)}</span><span class="ico ${warn ? "warn" : ""}">${icon(ic)}</span></div><div class="num">${esc(value)}</div><div class="foot">${esc(foot)}</div></button>`;
  const quick = (attrs, ic, label, hint, primary) =>
    `<button ${attrs} class="${primary ? "primary" : ""}"><span class="qi">${icon(ic)}</span><span><strong>${esc(label)}</strong><small>${esc(hint)}</small></span></button>`;
  const tile = (cls, heading, body, opts = {}) =>
    `<section class="tile ${cls} flat"><div class="tile-head"><h2>${esc(heading)}</h2>${opts.go ? `<button class="btn link" data-go="${opts.go}">${esc(opts.label || "View all")}</button>` : opts.sub ? `<span class="sub">${esc(opts.sub)}</span>` : ""}</div>${body}</section>`;
  const listRows = (items, empty) => items.length
    ? `<ul class="rows">${items.map((it) => `<li ${it.go ? `class="link" data-go="${it.go}"` : ""}><span class="ri ${it.hot ? "hot2" : ""}">${icon(it.ic)}</span><div class="grow"><b>${esc(it.title)}</b><small>${esc(it.sub)}</small></div>${it.end !== undefined ? `<div class="end"><b>${esc(it.end)}</b><small>${esc(it.endSub || "")}</small></div>` : ""}${it.act ? `<span class="act">${it.act}</span>` : ""}</li>`).join("")}</ul>`
    : `<div class="empty">${esc(empty)}</div>`;
  const hotTile = (label, big, note) =>
    `<section class="tile hot s-4"><div><div class="label">${esc(label)}</div><div class="big">${esc(big)}</div><div class="note2">${esc(note)}</div></div>
      <div><div id="spark"></div><div class="note2" style="font-size:12.5px;margin-top:8px">Last 6 months</div></div></section>`;
  const heroTile = (first, blurb, actions) =>
    `<section class="tile hero s-8"><div><h1>${esc(greeting())}, ${esc(first)}</h1><p>${esc(blurb)}</p></div><div class="quick">${actions}</div></section>`;

  /** Numbers every role needs, derived from the API responses. */
  function derive(raw) {
    const subs = raw.subscriptions, invs = raw.invoices, pays = raw.payments;
    const live = invs.filter((i) => i.status !== "cancelled");
    const open = invs.filter((i) => i.status !== "paid" && i.status !== "cancelled");
    const overdue = invs.filter((i) => i.is_overdue);
    const months = lastMonths(6);
    const totalBilled = live.reduce((n, i) => n + i.total_amount, 0);
    const totalPaid = pays.reduce((n, p) => n + p.amount, 0);
    const activeSubs = subs.filter((s) => s.status === "active");
    return {
      subs, invs, pays, live, open, overdue, months, activeSubs, totalPaid, totalBilled,
      dueAmt: open.reduce((n, i) => n + (i.balance_due || 0), 0),
      overdueAmt: overdue.reduce((n, i) => n + (i.balance_due || 0), 0),
      rate: totalBilled ? Math.min(100, Math.round((totalPaid * 100) / totalBilled)) : null,
      collected: sumByMonth(pays, "payment_date", "amount", months),
      billed: sumByMonth(live, "issue_date", "total_amount", months),
      billSoon: activeSubs.filter((s) => s.next_billing_date && daysFromNow(s.next_billing_date) <= 7),
    };
  }

  const recentActivity = (X, n = 6) => [
    ...X.invs.map((i) => ({ at: i.created_at, ic: "invoices", hot: i.is_overdue, title: `Invoice ${i.invoice_number}`, sub: `${i.customer_name || "Customer"} · ${i.is_overdue ? "overdue" : i.status}`, end: inr(i.total_amount), endSub: timeAgo(i.created_at), go: "invoices" })),
    ...X.pays.map((p) => ({ at: p.created_at, ic: "payments", hot: false, title: `Payment ${p.payment_number}`, sub: `${p.customer_name || "Customer"} · ${title(p.payment_method)}`, end: inr(p.amount), endSub: timeAgo(p.created_at), go: "payments" })),
  ].sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, n);

  function invoiceDonut(host, X) {
    Charts.donut(host, {
      centerValue: X.invs.length, centerLabel: "invoices",
      segments: [
        { label: "Paid", value: X.invs.filter((i) => i.status === "paid").length, color: "#1877f2" },
        { label: "Open", value: X.open.filter((i) => !i.is_overdue).length, color: "#b0b8c4" },
        { label: "Overdue", value: X.overdue.length, color: "#d93025" },
        { label: "Cancelled", value: X.invs.filter((i) => i.status === "cancelled").length, color: "#e4e6eb" },
      ],
    });
  }
  const monthLabels = (X) => X.months.map((m) => m.label);
  const lateDays = (i) => -daysFromNow(i.due_date);

  function wireDashboard(root, X) {
    root.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", () => go(b.dataset.go)));
    root.querySelectorAll("[data-act=new]").forEach((b) => b.addEventListener("click", () => newSubscription().catch((e) => toast(e.message, true))));
    const stop = (fn) => (e) => { e.stopPropagation(); fn(e); };
    const invById = byId(X.invs), subById = byId(X.subs), tplById = byId(X.templates || []);
    root.querySelectorAll("[data-pay]").forEach((b) => b.addEventListener("click", stop(() => payInvoice(invById[b.dataset.pay]))));
    root.querySelectorAll("[data-sub]").forEach((b) => b.addEventListener("click", () => subscriptionDetail(subById[b.dataset.sub])));
    root.querySelectorAll("[data-quote]").forEach((b) => b.addEventListener("click", stop(() => createQuote(tplById[b.dataset.quote]).catch((e) => toast(e.message, true)))));
  }

  async function dashboardView(root) {
    root.innerHTML = dashSkeleton();
    const role = state.user.role;
    const keys = ["subscriptions", "invoices", "payments", "templates"];
    if (role === "admin") keys.push("users", "products", "variants", "plans", "discounts", "taxes");
    const [loaded, dash, health] = await Promise.all([
      Promise.all(keys.map((k) => data(k))),
      role === "admin" ? data("dashboard") : null,
      role === "admin" ? fetchHealth() : null,
    ]);
    const X = derive(Object.fromEntries(keys.map((k, i) => [k, loaded[i]])));
    X.templates = loaded[keys.indexOf("templates")];
    const first = String(state.user.name || "").split(/\s+/)[0] || "there";
    const render = { admin: adminDashboard, staff: staffDashboard, customer: customerDashboard }[role] || customerDashboard;
    render(root, X, { first, dash, health, raw: Object.fromEntries(keys.map((k, i) => [k, loaded[i]])) });
    wireDashboard(root, X);
  }

  /* ---------------- admin: the whole platform ---------------- */
  function adminDashboard(root, X, { first, dash, health, raw }) {
    const { users, products, variants, plans, discounts, taxes } = raw;
    const activeUsers = users.filter((u) => u.is_active).length;
    const blurb = `${plural(users.length, "account")}, ${plural(X.activeSubs.length, "active subscription")} and ${inr(dash.total_outstanding)} outstanding.` +
      (X.overdue.length ? ` ${plural(X.overdue.length, "invoice")} overdue.` : "");

    const byCustomer = {};
    X.live.forEach((i) => { const k = i.customer_name || "Customer"; byCustomer[k] = (byCustomer[k] || 0) + i.total_amount; });
    const topCustomers = Object.entries(byCustomer).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([label, value]) => ({ label, value, text: inr(value) }));

    const usage = discounts.slice().sort((a, b) => (b.used_count || 0) - (a.used_count || 0)).slice(0, 5)
      .map((d) => ({ label: d.code + (d.is_active ? "" : " (off)"), value: d.used_count || 0, text: `${d.used_count || 0}${d.max_uses ? " / " + d.max_uses : ""} used` }));
    const anyUsage = usage.some((u) => u.value > 0);

    const recentUsers = users.slice().sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).slice(0, 5)
      .map((u) => ({ ic: "users", title: u.name, sub: u.email, act: badge(u.is_active ? u.role : "closed").replace(">closed<", ">deactivated<") }));

    const inactive = (rows) => rows.filter((r) => !r.is_active).length;
    const catRow = (label, rows, go) => `<div class="status-row"><span>${esc(label)}</span><span><b>${rows.length}</b>${inactive(rows) ? `<span class="muted">${inactive(rows)} inactive</span>` : ""}</span></div>`;
    const catalog = `<div class="kv-rows">${catRow("Products", products)}${catRow("Variants", variants)}${catRow("Plans", plans)}${catRow("Taxes", taxes)}${catRow("Discount codes", discounts)}</div>`;

    const dot = (st, text) => `<span class="live ${st}"><i></i>${text}</span>`;
    const system = `<div class="status-row"><span>API</span>${health ? dot("", "Online") : dot("off", "Unreachable")}</div>
      <div class="status-row"><span>Database</span>${health ? dot(health.supabase_configured ? "" : "off", health.supabase_configured ? "Connected" : "Not configured") : dot("wait", "Unknown")}</div>
      <div class="status-row"><span>Authentication</span>${health ? dot(health.auth_configured ? "" : "off", health.auth_configured ? "Ready" : "Not configured") : dot("wait", "Unknown")}</div>`;

    root.innerHTML = `<div class="bento enter">
      ${heroTile(first, blurb,
        quick('data-act="new"', "plus", "New subscription", "Start a quote or plan", true) +
        quick('data-go="users"', "users", "Manage users", `${activeUsers} active`) +
        quick('data-go="products"', "products", "Catalog", `${plural(plans.length, "plan")}`) +
        quick('data-go="billing"', "billing", "Run billing", "Invoice what is due"))}
      ${hotTile("Monthly recurring revenue", inr(dash.monthly_recurring_revenue), `${inr(dash.annual_run_rate)} annual run rate`)}

      ${tile("s-8", "Collected revenue", '<div id="c-rev"></div>' + (X.collected.every((v) => !v) ? '<div class="chart-note">No payments recorded in the last 6 months.</div>' : ""), { sub: X.rate === null ? "Last 6 months" : `Collection rate ${X.rate}%` })}
      ${tile("s-4", "People by role", '<div id="c-roles"></div>', { go: "users", label: "Manage" })}

      ${stat("subscriptions", "subscriptions", "Active subscriptions", X.activeSubs.length, `${X.subs.length} in total`)}
      ${stat("payments", "payments", "Revenue collected", inr(dash.total_revenue_collected), plural(X.pays.length, "payment"))}
      ${stat("invoices", "taxes", "Overdue", X.overdue.length, X.overdue.length ? `${inr(X.overdueAmt)} to collect` : "Nothing overdue", X.overdue.length > 0)}
      ${stat("users", "users", "Active users", activeUsers, `${users.length} accounts`)}

      ${tile("s-4", "Billed and collected", '<div id="c-bars"></div>', { sub: "Last 6 months" })}
      ${tile("s-4", "Top customers", topCustomers.length ? '<div id="c-top"></div>' : '<div class="empty">Billed customers appear here.</div>', { sub: "By amount billed" })}
      ${tile("s-4", "Catalog and tax setup", catalog, { go: "products", label: "Open" })}

      ${tile("s-4", "Discount usage", usage.length ? (anyUsage ? '<div id="c-disc"></div>' : '<div class="empty">No discount code has been redeemed yet.</div>') : '<div class="empty">No discount codes yet.</div>', { go: "discounts", label: "Manage" })}
      ${tile("s-4", "Newest accounts", listRows(recentUsers, "No accounts yet."), { go: "users" })}
      ${tile("s-4", "System status", system)}

      ${tile("s-12", "Recent activity", listRows(recentActivity(X, 6), "Invoices and payments will show up here."), { go: "invoices" })}
    </div>`;

    Charts.spark($("#spark", root), X.billed);
    Charts.line($("#c-rev", root), { labels: monthLabels(X), values: X.collected });
    const count = (r) => users.filter((u) => u.role === r).length;
    Charts.donut($("#c-roles", root), {
      centerValue: users.length, centerLabel: "accounts",
      segments: [{ label: "Admins", value: count("admin"), color: "#1877f2" }, { label: "Staff", value: count("staff"), color: "#8ab4f8" }, { label: "Customers", value: count("customer"), color: "#c9ccd1" }],
    });
    Charts.bars($("#c-bars", root), { labels: monthLabels(X), series: [{ name: "Billed", color: "#c9ccd1", values: X.billed }, { name: "Collected", color: "#1877f2", values: X.collected }] });
    if (topCustomers.length) Charts.hbars($("#c-top", root), topCustomers);
    if (usage.length && anyUsage) Charts.hbars($("#c-disc", root), usage);
  }

  /* ---------------- staff: today's work queue ---------------- */
  function staffDashboard(root, X, { first, dash }) {
    const monthIdx = X.months.length - 1;
    const thisMonth = X.months[monthIdx].key;
    const paidThisMonth = X.pays.filter((p) => String(p.payment_date).slice(0, 7) === thisMonth);
    const toSend = X.invs.filter((i) => !i.sent_at && (i.status === "draft" || i.status === "confirmed"));
    const toProgress = X.subs.filter((s) => ["draft", "quotation", "confirmed"].includes(s.status))
      .sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
    const nextStep = { draft: "Send as quotation", quotation: "Waiting to confirm", confirmed: "Ready to activate" };

    const chase = X.overdue.slice().sort((a, b) => String(a.due_date).localeCompare(String(b.due_date))).slice(0, 5)
      .map((i) => ({ ic: "invoices", hot: true, title: i.customer_name || i.invoice_number, sub: `${i.invoice_number} · ${plural(lateDays(i), "day")} late`, end: inr(i.balance_due), go: "invoices" }));
    const quotes = toProgress.slice(0, 5)
      .map((s) => ({ ic: "subscriptions", title: s.customer_name || s.subscription_number, sub: `${s.subscription_number} · ${nextStep[s.status]}`, act: badge(s.status), go: "subscriptions" }));
    const dueNow = X.billSoon.slice().sort((a, b) => String(a.next_billing_date).localeCompare(String(b.next_billing_date))).slice(0, 5)
      .map((s) => ({ ic: "billing", title: s.customer_name || s.subscription_number, sub: s.plan_name || "", end: inr(s.total_recurring_amount), endSub: relDays(daysFromNow(s.next_billing_date)), go: "billing" }));

    const blurb = `${X.overdue.length ? plural(X.overdue.length, "overdue invoice") + " to chase" : "No overdue invoices"}, ${plural(toProgress.length, "quote")} to move forward, and ${X.billSoon.length ? plural(X.billSoon.length, "subscription") + " billing this week" : "nothing due to bill this week"}.`;

    const aging = [0, 0, 0, 0];
    X.open.forEach((i) => { const late = lateDays(i), v = i.balance_due || 0; if (late <= 0) aging[0] += v; else if (late <= 30) aging[1] += v; else if (late <= 60) aging[2] += v; else aging[3] += v; });
    const statuses = ["draft", "quotation", "confirmed", "active", "paused", "closed"];
    const pipeline = statuses.map((st) => ({ label: title(st), value: X.subs.filter((s) => s.status === st).length, text: String(X.subs.filter((s) => s.status === st).length) }));

    root.innerHTML = `<div class="bento enter">
      ${heroTile(first, blurb,
        quick('data-act="new"', "plus", "New subscription", "Start a quote or plan", true) +
        quick('data-go="billing"', "billing", "Run billing", X.billSoon.length ? plural(X.billSoon.length, "due this week") : "Nothing due yet") +
        quick('data-go="invoices"', "invoices", "Record a payment", plural(X.open.length, "open invoice")))}
      ${hotTile("Left to collect", inr(X.dueAmt), `${plural(X.open.length, "open invoice")} · ${inr(X.overdueAmt)} overdue`)}

      ${tile("s-4", "Overdue invoices", listRows(chase, "Nothing overdue. Nice."), { go: "invoices", label: "All" })}
      ${tile("s-4", "Quotes and new subscriptions", listRows(quotes, "No quotes are waiting."), { go: "subscriptions", label: "All" })}
      ${tile("s-4", "Billing this week", listRows(dueNow, "No subscriptions are due to bill this week."), { go: "billing", label: "Run" })}

      ${stat("subscriptions", "subscriptions", "Active subscriptions", X.activeSubs.length, `${X.subs.length} in total`)}
      ${stat("invoices", "invoices", "Open invoices", X.open.length, `${inr(X.dueAmt)} to collect`)}
      ${stat("payments", "payments", "Collected this month", inr(X.collected[monthIdx]), plural(paidThisMonth.length, "payment"))}
      ${stat("invoices", "templates", "Not yet sent", toSend.length, toSend.length ? "Invoices waiting to be sent" : "All invoices sent", toSend.length > 0)}

      ${tile("s-8", "Collected revenue", '<div id="c-rev"></div>' + (X.collected.every((v) => !v) ? '<div class="chart-note">No payments recorded in the last 6 months.</div>' : ""), { sub: X.rate === null ? "Last 6 months" : `Collection rate ${X.rate}%` })}
      ${tile("s-4", "Invoices by status", '<div id="c-status"></div>')}

      ${tile("s-6", "Receivables by age", X.open.length ? '<div id="c-aging"></div>' : '<div class="empty">No open invoices to age.</div>', { sub: "What customers still owe" })}
      ${tile("s-6", "Subscription pipeline", '<div id="c-pipe"></div>', { go: "subscriptions", label: "Open" })}

      ${tile("s-12", "Recent activity", listRows(recentActivity(X, 6), "Invoices and payments will show up here."), { go: "payments", label: "Payments" })}
    </div>`;

    Charts.spark($("#spark", root), X.collected);
    Charts.line($("#c-rev", root), { labels: monthLabels(X), values: X.collected });
    invoiceDonut($("#c-status", root), X);
    if (X.open.length) Charts.bars($("#c-aging", root), {
      labels: ["Not due", "1–30 days", "31–60 days", "60+ days"],
      series: [{ name: "Outstanding", color: "#1877f2", colors: ["#1877f2", "#f0a35e", "#e5683c", "#d93025"], values: aging }],
    });
    Charts.hbars($("#c-pipe", root), pipeline);
  }

  /* ---------------- customer: my account ---------------- */
  function customerDashboard(root, X, { first }) {
    const openByDue = X.open.slice().sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)));
    const oldest = openByDue[0];
    const blurb = X.open.length
      ? `${plural(X.open.length, "open invoice")} totalling ${inr(X.dueAmt)}${X.overdue.length ? `, ${X.overdue.length} overdue` : ""}.`
      : "You are all paid up. Nothing is due.";

    const subCards = X.subs.length
      ? `<div class="sub-grid">${X.subs.map((s) => `<button class="sub-card" data-sub="${s.id}"><div class="row1"><b>${esc(s.plan_name || s.subscription_number)}</b>${badge(s.status)}</div><div class="amt">${inr(s.total_recurring_amount)}</div><small>${s.status === "active" && s.next_billing_date ? "Next bill " + esc(relDays(daysFromNow(s.next_billing_date)).toLowerCase()) : esc(s.subscription_number)}</small></button>`).join("")}</div>`
      : '<div class="empty">You have no subscriptions yet. Request a plan below.</div>';

    const toPay = openByDue.slice(0, 4).map((i) => ({
      ic: "invoices", hot: i.is_overdue, title: i.invoice_number,
      sub: `Due ${dateOnly(i.due_date)}${i.is_overdue ? " · overdue" : ""}`, end: inr(i.balance_due),
      act: `<button class="btn primary sm" data-pay="${i.id}">Pay</button>`,
    }));
    const offers = (X.templates || []).filter((t) => t.is_active).slice(0, 4).map((t) => ({
      ic: "templates", title: t.name, sub: t.description || `${(t.lines || []).length} item(s), valid ${t.valid_days} days`,
      act: `<button class="btn sm" data-quote="${t.id}">Request quote</button>`,
    }));
    const history = X.pays.slice(0, 5).map((p) => ({ ic: "payments", title: p.payment_number, sub: `${p.invoice_number || "Invoice"} · ${title(p.payment_method)}`, end: inr(p.amount), endSub: dateOnly(p.payment_date), go: "payments" }));
    const nextDue = oldest ? `Next due ${dateOnly(oldest.due_date)}` : "Nothing due";

    root.innerHTML = `<div class="bento enter">
      ${heroTile(first, blurb,
        (oldest
          ? quick(`data-pay="${oldest.id}"`, "payments", "Pay an invoice", `${inr(oldest.balance_due)} · ${oldest.invoice_number}`, true)
          : quick('data-act="new"', "plus", "New subscription", "Request a plan", true)) +
        quick('data-go="invoices"', "invoices", "My invoices", plural(X.invs.length, "invoice")) +
        quick('data-go="subscriptions"', "subscriptions", "My subscriptions", `${X.activeSubs.length} active`))}
      ${hotTile("Amount due", inr(X.dueAmt), nextDue)}

      ${tile("s-8", "My subscriptions", subCards, { go: "subscriptions", label: "All" })}
      ${tile("s-4", "Invoices to pay", listRows(toPay, "No invoices to pay."), { go: "invoices", label: "All" })}

      ${stat("subscriptions", "subscriptions", "Active subscriptions", X.activeSubs.length, `${X.subs.length} in total`)}
      ${stat("invoices", "invoices", "Amount due", inr(X.dueAmt), plural(X.open.length, "open invoice"))}
      ${stat("invoices", "taxes", "Overdue", X.overdue.length, X.overdue.length ? `${inr(X.overdueAmt)} past due` : "Nothing overdue", X.overdue.length > 0)}
      ${stat("payments", "payments", "Total paid", inr(X.totalPaid), plural(X.pays.length, "payment"))}

      ${tile("s-8", "What you have paid", '<div id="c-rev"></div>' + (X.collected.every((v) => !v) ? '<div class="chart-note">No payments in the last 6 months.</div>' : ""), { sub: "Last 6 months" })}
      ${tile("s-4", "Invoices by status", '<div id="c-status"></div>')}

      ${tile("s-6", "Request a plan", listRows(offers, "No plans are available to request right now."), { go: "templates", label: "All" })}
      ${tile("s-6", "Payment history", listRows(history, "Your payments will show up here."), { go: "payments", label: "All" })}
    </div>`;

    Charts.spark($("#spark", root), X.collected);
    Charts.line($("#c-rev", root), { labels: monthLabels(X), values: X.collected });
    invoiceDonut($("#c-status", root), X);
  }

  const VIEWS = {
    dashboard: dashboardView, users: usersView, products: productsView, variants: variantsView, plans: plansView,
    taxes: taxesView, discounts: discountsView, templates: templatesView, subscriptions: subscriptionsView,
    invoices: invoicesView, payments: paymentsView, billing: billingView,
  };

  /* ------------------------------------------------------------------ *
   * Shell: sidebar, routing, rendering
   * ------------------------------------------------------------------ */
  function go(view) {
    state.view = view;
    state.search = "";
    location.hash = view;
    render();
  }

  const initials = (name) => String(name || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");

  const PRIMARY = ["dashboard", "subscriptions", "invoices", "payments"];
  const POPS = ["morepop", "bellpop", "umenu", "mpop"];
  const closePops = () => POPS.forEach((id) => { const n = $("#" + id); if (n) n.classList.add("hidden"); });
  function togglePop(id) {
    const n = $("#" + id);
    const wasHidden = n.classList.contains("hidden");
    closePops();
    if (wasHidden) n.classList.remove("hidden");
    return wasHidden;
  }

  function renderShell() {
    const allowed = navItems();
    const primary = PRIMARY.map((id) => allowed.find((i) => i.id === id)).filter(Boolean);
    const rest = allowed.filter((i) => !PRIMARY.includes(i.id));
    const row = (i) => `<button class="pop-item ${state.view === i.id ? "active" : ""}" data-nav="${i.id}">${icon(i.id)}<span class="grow">${esc(i.label)}</span></button>`;
    const grouped = NAV.map((g) => {
      const items = g.items.filter((i) => i.roles.includes(state.user.role));
      return items.length ? `<div class="pop-title">${esc(g.group)}</div>${items.map(row).join("")}` : "";
    }).join("");
    const ini = esc(initials(state.user.name));

    $("#app").innerHTML = `
      <div class="app"><div class="workspace">
        <header class="topbar">
          <div class="tb-brand"><span class="brand-mark">B</span>Brightloop</div>
          <nav class="nav-pills" aria-label="Main">
            ${primary.map((i) => `<button class="pill ${state.view === i.id ? "active" : ""}" data-nav="${i.id}"><span class="dot"></span>${esc(i.label)}</button>`).join("")}
            <span class="more-wrap">
              <button class="pill ${rest.some((i) => i.id === state.view) ? "active" : ""}" id="more" aria-haspopup="true">More ${icon("chevron")}</button>
              <div class="pop left hidden" id="morepop">${rest.map(row).join("")}</div>
            </span>
          </nav>
          <div class="tb-actions">
            <button class="icon-btn menu-btn" id="menu" aria-label="Menu" aria-haspopup="true">${icon("menu")}</button>
            <button class="icon-btn" id="bell" aria-label="Notifications" aria-haspopup="true">${icon("bell")}<span class="ping hidden" id="ping"></span></button>
            <button class="avatar" id="avatar" aria-label="Account menu" aria-haspopup="true">${ini}</button>
            <div class="pop wide hidden" id="bellpop"></div>
            <div class="pop hidden" id="mpop">${grouped}</div>
            <div class="pop hidden" id="umenu">
              <div class="pop-head"><span class="avatar sm">${ini}</span><div><b>${esc(state.user.name)}</b><div class="muted" style="font-size:13px">${esc(state.user.email)}</div></div></div>
              <div class="pop-title">Signed in as ${esc(state.user.role)}</div>
              <button class="pop-item" id="logout">${icon("logout")}<span class="grow">Sign out</span></button>
            </div>
          </div>
        </header>
        <main class="content" id="view"></main>
      </div></div>`;

    document.querySelectorAll("[data-nav]").forEach((b) => b.addEventListener("click", () => { closePops(); go(b.dataset.nav); }));
    $("#logout").addEventListener("click", logout);
    const opener = (btn, pop, after) => $(btn).addEventListener("click", (e) => { e.stopPropagation(); if (togglePop(pop) && after) after(); });
    opener("#more", "morepop");
    opener("#menu", "mpop");
    opener("#avatar", "umenu");
    opener("#bell", "bellpop", fillBell);
  }
  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest(".pop")) return;
    closePops();
  });

  async function fillBell() {
    const pop = $("#bellpop");
    pop.innerHTML = '<div class="pop-empty">Loading…</div>';
    try {
      const [invs, subs] = await Promise.all([data("invoices"), data("subscriptions")]);
      const items = [
        ...invs.filter((i) => i.is_overdue).map((i) => ({ go: "invoices", ic: "invoices", hot: true, t: `Invoice ${i.invoice_number} is overdue`, s: `${i.customer_name || "Customer"} · ${inr(i.balance_due)} due ${dateOnly(i.due_date)}` })),
        ...(isStaff() ? subs.filter((x) => x.status === "active" && x.next_billing_date && daysFromNow(x.next_billing_date) <= 3)
          .map((x) => ({ go: "billing", ic: "billing", hot: false, t: `${x.subscription_number} bills ${relDays(daysFromNow(x.next_billing_date)).toLowerCase()}`, s: x.customer_name || "" })) : []),
      ];
      pop.innerHTML = `<div class="pop-title">Notifications</div>` + (items.length
        ? items.map((n) => `<button class="pop-item" data-bell="${n.go}"><span class="ri ${n.hot ? "hot2" : ""}" style="width:34px;height:34px;border-radius:50%;display:grid;place-items:center;flex:none;background:${n.hot ? "var(--accent-soft)" : "var(--tile)"};color:${n.hot ? "var(--accent)" : "var(--ink-2)"}">${icon(n.ic)}</span><span class="grow">${esc(n.t)}<small>${esc(n.s)}</small></span></button>`).join("")
        : '<div class="pop-empty">You are all caught up.</div>');
      pop.querySelectorAll("[data-bell]").forEach((b) => b.addEventListener("click", () => { closePops(); go(b.dataset.bell); }));
    } catch (e) { pop.innerHTML = `<div class="pop-empty">${esc(e.message)}</div>`; }
  }

  async function updatePing() {
    try {
      const invs = await data("invoices");
      const ping = $("#ping");
      if (ping) ping.classList.toggle("hidden", !invs.some((i) => i.is_overdue));
    } catch { /* the bell simply stays quiet */ }
  }

  let renderToken = 0;
  async function render() {
    if (!state.user) return renderAuth();
    if (!navItems().some((i) => i.id === state.view)) state.view = "dashboard";
    const token = ++renderToken;
    renderShell();
    const root = $("#view");
    try {
      await VIEWS[state.view](root);
      if (token !== renderToken) return;
      updatePing();
    } catch (e) {
      if (token !== renderToken) return;
      root.innerHTML = `<div class="err">${esc(e.message)}</div><button class="btn" id="retry">Retry</button>`;
      $("#retry").addEventListener("click", () => { state.cache = {}; render(); });
    }
  }

  /* ------------------------------------------------------------------ *
   * Auth screens
   * ------------------------------------------------------------------ */
  function logout() {
    state.token = null; state.user = null; state.cache = {};
    store.del("bl_token");
    renderAuth();
  }

  function renderAuth(mode = "login", notice = "") {
    $("#app").innerHTML = `
      <div class="auth">
        <aside class="auth-aside">
          <div class="brand"><span class="brand-mark">B</span> Brightloop</div>
          <div>
            <h2>Recurring billing, without the spreadsheets.</h2>
            <p>Plans, subscriptions, invoices and payments in one place, with a billing run that never bills the same period twice.</p>
            <ul><li>Role-based access for admins, staff and customers</li><li>Automatic taxes, discounts and due dates</li><li>Live revenue and overdue reporting</li></ul>
          </div>
          <span style="opacity:.6;font-size:12.5px">Brightloop Software</span>
        </aside>
        <main class="auth-main"><div class="auth-card">
        <h1>${{ login: "Welcome back", register: "Create your account", forgot: "Reset your password" }[mode]}</h1>
        <p class="sub">${{ login: "Sign in to manage your subscriptions.", register: "Customer accounts get a self-service portal.", forgot: "We will issue a reset token for your account." }[mode]}</p>
        <div class="segmented">
          ${[["login", "Sign in"], ["register", "Sign up"], ["forgot", "Forgot password"]]
            .map(([m, l]) => `<button class="seg ${m === mode ? "active" : ""}" data-mode="${m}">${l}</button>`).join("")}
        </div>
        <div class="err hidden" id="autherr"></div>
        ${notice ? `<div class="note">${notice}</div>` : ""}
        <form id="authform"></form>
        ${mode === "login" ? demoBox() : ""}
      </div></main></div>`;
    document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => renderAuth(b.dataset.mode)));
    const form = $("#authform");
    const field = (n, l, t = "text", extra = "") => `<label class="field"><span>${l}</span><input name="${n}" type="${t}" required ${extra}/></label>`;
    const showErr = (m) => { const e = $("#autherr"); e.textContent = m; e.classList.remove("hidden"); };
    const submit = (label) => `<button class="btn primary" style="width:100%" type="submit">${label}</button>`;

    if (mode === "login") {
      form.innerHTML = field("email", "Email", "email", 'autocomplete="username"') + field("password", "Password", "password", 'autocomplete="current-password"') + submit("Sign in");
      form.addEventListener("submit", (e) => { e.preventDefault(); doLogin(form.email.value, form.password.value, showErr); });
      $("#seed")?.addEventListener("click", seedDemo);
      document.querySelectorAll("[data-fill]").forEach((b) => b.addEventListener("click", () => {
        const [em, pw] = b.dataset.fill.split("|"); form.email.value = em; form.password.value = pw;
      }));
    } else if (mode === "register") {
      form.innerHTML = field("name", "Full name") + field("email", "Email", "email") + field("password", "Password", "password", 'autocomplete="new-password"') +
        '<small class="muted" style="display:block;margin:-6px 0 12px">9+ characters with upper and lower case letters and a special character.</small>' + submit("Create customer account");
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await api("/users/register", { method: "POST", body: { name: form.name.value, email: form.email.value, password: form.password.value } });
          await doLogin(form.email.value, form.password.value, showErr);
        } catch (err) { showErr(err.message); }
      });
    } else {
      form.innerHTML = field("email", "Account email", "email") + submit("Send reset link");
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const r = await api("/auth/forgot-password", { method: "POST", body: { email: form.email.value } });
          if (r.reset_token) renderReset(r.reset_token, r.message);
          else renderAuth("login", esc(r.message));
        } catch (err) { showErr(err.message); }
      });
    }
  }

  function renderReset(token, msg) {
    renderAuth("forgot", `${esc(msg)}<br/>Demo mode shows the token here instead of emailing it.`);
    const form = $("#authform");
    form.innerHTML = `<label class="field"><span>Reset token</span><input name="token" value="${esc(token)}" required /></label>
      <label class="field"><span>New password</span><input name="pw" type="password" required autocomplete="new-password" /></label>
      <button class="btn primary" style="width:100%" type="submit">Reset password</button>`;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await api("/auth/reset-password", { method: "POST", body: { token: form.token.value, new_password: form.pw.value } });
        renderAuth("login", "Password updated. Please sign in.");
      } catch (err) { const b = $("#autherr"); b.textContent = err.message; b.classList.remove("hidden"); }
    });
  }

  function demoBox() {
    const accts = [["Admin", "arjun@brightloop.in|Admin@2026"], ["Staff", "priya@brightloop.in|Staff@2026"], ["Customer", "contact@technova.io|Customer@2026"]];
    return `<div class="demo-box"><strong>Demo data</strong><div class="muted">Fill a demo login, or load sample data (needs the bootstrap token).</div>
      <div class="row">${accts.map(([l, v]) => `<button class="btn sm" type="button" data-fill="${esc(v)}">${l}</button>`).join("")}
      <button class="btn sm danger" type="button" id="seed">Load demo data…</button></div></div>`;
  }

  async function seedDemo() {
    if (!confirm("This REPLACES the existing products, plans, subscriptions, invoices and payments with demo data. Continue?")) return;
    const token = prompt("Enter the BOOTSTRAP_TOKEN from backend/.env to confirm:");
    if (!token) return;
    try {
      await api("/demo/seed", { method: "POST", headers: { "X-Bootstrap-Token": token } });
      toast("Demo data loaded. Use a demo login above.");
    } catch (e) { toast(e.message, true); }
  }

  async function doLogin(email, password, showErr) {
    try {
      const r = await api("/auth/login", { method: "POST", body: { email, password } });
      state.token = r.access_token; state.user = r.user; state.cache = {};
      store.set("bl_token", r.access_token);
      state.view = (location.hash || "").slice(1) || "dashboard";
      await render();
    } catch (e) { showErr(e.message); }
  }

  /* ------------------------------------------------------------------ *
   * Boot
   * ------------------------------------------------------------------ */
  window.addEventListener("hashchange", () => {
    const v = location.hash.slice(1);
    if (state.user && v && v !== state.view && VIEWS[v]) { state.view = v; state.search = ""; render(); }
  });

  (async function boot() {
    if (state.token) {
      try {
        state.user = await api("/users/me");
        state.view = (location.hash || "").slice(1) || "dashboard";
      } catch { state.token = null; store.del("bl_token"); }
    }
    render();
  })();
})();
