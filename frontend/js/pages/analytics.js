import { api } from "../api.js";
import { h, mount, loading, statusLabel } from "../ui.js";

let includeSim = false;
const NS = "http://www.w3.org/2000/svg";
const s = (tag, attrs = {}, ...kids) => { const el = document.createElementNS(NS, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); kids.forEach((k) => el.appendChild(typeof k === "string" ? document.createTextNode(k) : k)); return el; };

export async function render(root) {
  mount(root, loading());
  const a = await api.get(`/api/analytics?include_simulated=${includeSim}`);
  const c = a.counts;
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  const toggle = h("input", { type: "checkbox", checked: includeSim, onchange: () => { includeSim = toggle.checked; render(root); } });

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Analytics"), h("div", { class: "sub" }, a.notes)),
      h("label", { class: "check" }, toggle, "Include simulated demo data")),
    includeSim && h("div", { class: "alert sim", style: { marginBottom: "12px" } }, "Simulated listings are included — these numbers are not real-world results."),
    h("div", { class: "grid cols-4", style: { marginBottom: "16px" } },
      tile(c.jobs_discovered, "Jobs discovered", `${c.active_listings} still active`),
      tile(c.high_match_jobs, "High-match jobs", `score ≥ ${a.high_match_threshold}`),
      tile(c.applications_prepared, "Applications prepared", "with approved materials"),
      tile(c.applications_submitted, "Submitted", `${c.submissions_verified} verified · ${c.submissions_user_reported} self-reported`),
      tile(c.interviews, "Interviews", "reached interview stage"),
      tile(c.offers, "Offers", ""),
      tile(pct(a.rates.response_rate), "Response rate", "any reply ÷ submitted"),
      tile(pct(a.rates.interview_rate), "Interview rate", "interviews ÷ submitted")),
    h("div", { class: "grid cols-2" },
      h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Activity (last 12 weeks)"),
        h("div", { class: "legend" }, h("span", {}, h("i", { style: { background: "var(--accent)" } }), "discovered"), h("span", {}, h("i", { style: { background: "var(--good)" } }), "applied"))),
        h("div", { class: "chart" }, activityChart(a.activity))),
      h("div", { class: "card" }, h("h2", {}, "Pipeline"),
        Object.entries(a.status_counts).map(([k, v]) => {
          const max = Math.max(1, ...Object.values(a.status_counts));
          return h("div", { class: "breakdown-row" }, h("span", { class: "small" }, statusLabel(k)),
            h("div", { class: "bar" }, h("i", { style: { width: `${(v / max) * 100}%` } })), h("span", { class: "small" }, String(v)));
        }))),
    h("div", { class: "grid cols-3", style: { marginTop: "16px" } },
      perf("By source", a.by_source), perf("By company", a.by_company), perf("By role", a.by_role)));
}

const tile = (v, l, hnt) => h("div", { class: "card stat" }, h("div", { class: "v" }, String(v)), h("div", { class: "l" }, l), hnt && h("div", { class: "h" }, hnt));

function perf(title, rows) {
  return h("div", { class: "card" }, h("h2", {}, title),
    rows.length ? h("table", {}, h("thead", {}, h("tr", {}, ["", "Applied", "Replies", "Interviews"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map((r) => h("tr", {}, h("td", { class: "small" }, r.key), h("td", {}, String(r.applied)), h("td", {}, String(r.responses)), h("td", {}, String(r.interviews))))))
      : h("p", { class: "muted small" }, "No submitted applications yet."));
}

function activityChart(weeks) {
  const W = 560, H = 200, P = 24, bw = (W - P * 2) / weeks.length;
  const max = Math.max(1, ...weeks.map((w) => Math.max(w.discovered, w.applied)));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Weekly jobs discovered and applications submitted" });
  for (let i = 0; i <= 4; i++) {
    const y = P + ((H - P * 2) * i) / 4;
    svg.appendChild(s("line", { x1: P, x2: W - P, y1: y, y2: y, stroke: "var(--border)" }));
    svg.appendChild(s("text", { x: 2, y: y + 3 }, String(Math.round(max * (1 - i / 4)))));
  }
  weeks.forEach((w, i) => {
    const x = P + i * bw + 4, inner = (bw - 8) / 2, sc = (v) => ((H - P * 2) * v) / max;
    const r1 = s("rect", { x, y: H - P - sc(w.discovered), width: inner, height: sc(w.discovered), rx: 2, fill: "var(--accent)" });
    r1.appendChild(s("title", {}, `${w.week}: ${w.discovered} discovered`));
    const r2 = s("rect", { x: x + inner, y: H - P - sc(w.applied), width: inner, height: sc(w.applied), rx: 2, fill: "var(--good)" });
    r2.appendChild(s("title", {}, `${w.week}: ${w.applied} applied`));
    svg.append(r1, r2);
    if (i % 2 === 0) svg.appendChild(s("text", { x, y: H - 6 }, w.week.slice(5)));
  });
  return svg;
}
