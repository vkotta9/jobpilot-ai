import { api } from "../api.js";
import { h, mount, loading, empty, statusBadge, statusLabel, simBadge, fmtDate, STATUSES } from "../ui.js";

const view = { mode: "kanban", sort: "updated_at", dir: -1, q: "", status: "" };

export async function render(root) {
  mount(root, loading());
  const apps = await api.get("/api/applications");
  const body = h("div");

  const draw = () => {
    let rows = apps.filter((a) => (!view.q || `${a.job.title} ${a.job.company}`.toLowerCase().includes(view.q.toLowerCase())) && (!view.status || a.status === view.status));
    if (!apps.length) return mount(body, h("div", { class: "card" }, empty("▤", "Your tracker is empty", "Shortlist a job from Discover to start tracking it.", h("a", { class: "btn btn-primary", href: "#/discover" }, "Discover jobs"))));
    if (view.mode === "kanban") {
      const cols = STATUSES.filter((s) => s !== "discovered");
      mount(body, h("div", { class: "kanban" }, cols.map((s) => {
        const items = rows.filter((a) => a.status === s);
        return h("div", { class: "kcol", "aria-label": statusLabel(s) },
          h("h3", {}, statusLabel(s), h("span", {}, String(items.length))),
          items.map((a) => h("div", { class: "kcard", tabindex: 0, onclick: () => (location.hash = `#/applications/${a.id}`), onkeydown: (e) => e.key === "Enter" && (location.hash = `#/applications/${a.id}`) },
            h("div", { style: { fontWeight: 600, fontSize: "13px" } }, a.job.title),
            h("div", { class: "small muted" }, a.job.company),
            h("div", { class: "row", style: { marginTop: "6px", gap: "4px" } },
              a.match_score != null && h("span", { class: "badge accent" }, `${a.match_score}`), a.job.is_simulated && simBadge(),
              a.follow_up_at && h("span", { class: `badge ${new Date(a.follow_up_at) < new Date() ? "bad" : ""}` }, "↻ " + fmtDate(a.follow_up_at))))));
      })));
    } else {
      const key = { company: (a) => a.job.company.toLowerCase(), title: (a) => a.job.title.toLowerCase(), status: (a) => STATUSES.indexOf(a.status),
        match_score: (a) => a.match_score ?? -1, submitted_at: (a) => a.submitted_at || "", follow_up_at: (a) => a.follow_up_at || "~", updated_at: (a) => a.updated_at }[view.sort];
      rows = [...rows].sort((x, y) => (key(x) > key(y) ? 1 : key(x) < key(y) ? -1 : 0) * view.dir);
      const th = (k, l) => h("th", { onclick: () => { view.dir = view.sort === k ? -view.dir : 1; view.sort = k; draw(); }, "aria-sort": view.sort === k ? (view.dir > 0 ? "ascending" : "descending") : "none" },
        l, view.sort === k ? (view.dir > 0 ? " ▲" : " ▼") : "");
      mount(body, h("div", { class: "card", style: { padding: 0 } }, h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, th("company", "Company"), th("title", "Role"), th("status", "Status"), th("match_score", "Match"),
          th("submitted_at", "Applied"), th("follow_up_at", "Follow-up"), h("th", {}, "Next action"))),
        h("tbody", {}, rows.map((a) => h("tr", { style: { cursor: "pointer" }, onclick: () => (location.hash = `#/applications/${a.id}`) },
          h("td", {}, h("strong", {}, a.job.company), " ", a.job.is_simulated && simBadge()), h("td", {}, a.job.title), h("td", {}, statusBadge(a.status)),
          h("td", {}, a.match_score ?? "—"), h("td", {}, a.submitted_at ? [fmtDate(a.submitted_at), " ", h("span", { class: `badge ${a.submission_verified ? "good" : "warn"}` }, a.submission_verified ? "verified" : "self-reported")] : "—"),
          h("td", {}, fmtDate(a.follow_up_at)), h("td", { class: "small muted" }, a.next_action || a.next_best_action))))))));
    }
  };

  const search = h("input", { placeholder: "Search company or role", value: view.q, "aria-label": "Search tracker", oninput: () => { view.q = search.value; draw(); } });
  const statusSel = h("select", { "aria-label": "Filter by status", onchange: () => { view.status = statusSel.value; draw(); } },
    h("option", { value: "" }, "All statuses"), STATUSES.filter((s) => s !== "discovered").map((s) => h("option", { value: s, selected: view.status === s }, statusLabel(s))));
  const tabs = h("div", { class: "tabs", role: "tablist" }, [["kanban", "Board"], ["table", "Table"]].map(([m, l]) =>
    h("button", { class: view.mode === m ? "on" : "", role: "tab", "aria-selected": view.mode === m, onclick: () => { view.mode = m; render(root); } }, l)));

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Application tracker"), h("div", { class: "sub" }, `${apps.length} tracked application${apps.length === 1 ? "" : "s"}. Every status change is recorded in each application's history.`)),
      h("button", { onclick: () => api.file("/api/applications/export.csv", "jobpilot_tracker.csv") }, "⬇ Export CSV")),
    h("div", { class: "row between" }, tabs, h("div", { class: "row" }, search, statusSel)),
    body);
  draw();
}
