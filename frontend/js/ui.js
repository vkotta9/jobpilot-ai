// Small DOM toolkit. All text is set via textContent — untrusted data (job
// descriptions, parsed resumes) is never inserted as HTML.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else if (k === "selected") el.selected = !!v;
    else if (k === "disabled") el.disabled = !!v;
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function mount(target, ...children) {
  target.replaceChildren();
  append(target, children);
}

export function toast(msg, kind = "") {
  const t = h("div", { class: `toast ${kind}` }, msg);
  document.getElementById("toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "bad" ? 6500 : 3500);
}

export function modal(title, body, actions = []) {
  return new Promise((resolve) => {
    const close = (v) => { bg.remove(); document.removeEventListener("keydown", esc); resolve(v); };
    const esc = (e) => { if (e.key === "Escape") close(null); };
    const bg = h("div", { class: "modal-bg", onclick: (e) => { if (e.target === bg) close(null); } },
      h("div", { class: "card modal", role: "dialog", "aria-modal": "true", "aria-label": title },
        h("div", { class: "card-head" }, h("h2", {}, title),
          h("button", { class: "btn-ghost", "aria-label": "Close", onclick: () => close(null) }, "✕")),
        body,
        h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "16px" } },
          actions.map((a) => h("button", { class: a.primary ? "btn-primary" : a.danger ? "btn-danger" : "",
            onclick: async () => { const v = a.value ? await a.value() : a.label; if (v !== false) close(v); } }, a.label)))));
    document.body.appendChild(bg);
    document.addEventListener("keydown", esc);
    const first = bg.querySelector("input,textarea,select,button.btn-primary");
    first && first.focus();
  });
}

export async function confirmDialog(title, text, okLabel = "Confirm", danger = false) {
  const r = await modal(title, h("p", {}, text), [
    { label: "Cancel", value: () => null },
    { label: okLabel, primary: !danger, danger, value: () => true },
  ]);
  return r === true;
}

const STATUS_LABEL = {
  discovered: "Discovered", shortlisted: "Shortlisted", preparing: "Preparing", awaiting_approval: "Awaiting approval",
  applied: "Applied", assessment: "Assessment", interview: "Interview", offer: "Offer", rejected: "Rejected", withdrawn: "Withdrawn",
};
const STATUS_KIND = { applied: "info", assessment: "info", interview: "accent", offer: "good", rejected: "bad", withdrawn: "", awaiting_approval: "warn", preparing: "warn" };
export const STATUSES = Object.keys(STATUS_LABEL);
export const statusLabel = (s) => STATUS_LABEL[s] || s;
export const statusBadge = (s) => h("span", { class: `badge ${STATUS_KIND[s] || ""}` }, statusLabel(s));
export const simBadge = () => h("span", { class: "badge sim", title: "Demo data from the simulated source — not a real job" }, "SIMULATED");

export function scoreRing(score, lg = false) {
  if (score === null || score === undefined) return h("div", { class: `score ${lg ? "lg" : ""}`, title: "Not scored" }, h("span", {}, "–"));
  const c = score >= 70 ? "var(--good)" : score >= 50 ? "var(--warn)" : "var(--bad)";
  return h("div", { class: `score ${lg ? "lg" : ""}`, style: `--p:${score};--c:${c}`, title: `Match score ${score}/100`, role: "img", "aria-label": `Match score ${score} out of 100` },
    h("span", {}, String(score)));
}

export function recBadge(rec) {
  const k = { apply: "good", review: "warn", skip: "bad" }[rec] || "";
  return h("span", { class: `badge ${k}` }, { apply: "Apply", review: "Review", skip: "Skip" }[rec] || rec);
}

export function fmtDate(iso, withTime = false) {
  if (!iso) return "—";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  if (isNaN(d)) return "—";
  return withTime ? d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

export function ago(iso) {
  if (!iso) return "never";
  const d = new Date(iso.endsWith("Z") ? iso : iso + "Z");
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function money(min, max, cur = "", interval = "") {
  if (min == null && max == null) return null;
  const f = (n) => (n >= 1000 ? `${Math.round(n / 1000)}k` : String(n));
  const range = min != null && max != null ? `${f(min)}–${f(max)}` : f(min ?? max);
  const per = /hour/.test(interval) ? "/hr" : /month/.test(interval) ? "/mo" : "";
  return `${cur ? cur + " " : ""}${range}${per}`;
}

export const loading = () => h("div", {}, h("div", { class: "skeleton", style: "width:40%" }), h("div", { class: "skeleton" }), h("div", { class: "skeleton", style: "width:75%" }));

export function empty(icon, title, text, action) {
  return h("div", { class: "empty" }, h("div", { class: "big" }, icon), h("h3", {}, title), text && h("p", {}, text), action);
}

export function field(label, input, hint) {
  return h("label", {}, label, input, hint && h("span", { class: "hint" }, hint));
}

export const list = (s) => (s || "").split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

export function busy(btn, fn) {
  return async (...args) => {
    const old = btn.textContent;
    btn.disabled = true;
    btn.replaceChildren(h("span", { class: "spinner" }), " ", old);
    try { return await fn(...args); } finally { btn.disabled = false; btn.textContent = old; }
  };
}

export function download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
