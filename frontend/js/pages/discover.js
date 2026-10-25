import { api, qs } from "../api.js";
import { h, mount, loading, empty, scoreRing, simBadge, statusBadge, money, ago, field, toast, busy, modal, confirmDialog, sourceCredit } from "../ui.js";

const filters = { q: "", location: "", company: "", remote: "", seniority: "", min_score: "", max_score: "", posted_within: "", qualified_only: true,
  sort: "score", status: "active", include_simulated: true };

export async function render(root) {
  mount(root, loading());
  const [allSources, catalog, saved, auto, following, popular, top] = await Promise.all([api.get("/api/sources"), api.get("/api/sources/catalog"),
    api.get("/api/saved-searches"), api.get("/api/discovery/auto"), api.get("/api/companies"), api.get("/api/companies/popular"),
    api.get("/api/companies/top-tech")]);
  const sources = allSources.filter((s) => s.kind === "mock");
  const results = h("div", { class: "card", style: { padding: 0 } }, loading());

  const load = async () => {
    mount(results, loading());
    const r = await api.get("/api/jobs" + qs(filters));
    mount(results,
      h("div", { class: "row between", style: { padding: "12px 16px", borderBottom: "1px solid var(--border)" } },
        h("div", {}, h("strong", {}, `${r.total} job${r.total === 1 ? "" : "s"}`),
          r.hidden_higher_degree ? h("span", { class: "faint small" }, ` · ${r.hidden_higher_degree} hidden because they require a higher degree`) : null),
        h("span", { class: "faint" }, "Duplicates across sources are merged. Closed listings are hidden unless you filter for them.")),
      r.items.length ? r.items.map(jobRow) : empty("⌕", "No jobs match", sources.length ? "Try widening the filters or run a search." : "Add a job source above, then run a search."));
  };

  // ---- filter bar
  const inp = (k, ph, attrs = {}) => {
    const el = h("input", { value: filters[k], placeholder: ph, "aria-label": ph, ...attrs });
    el.addEventListener("change", () => { filters[k] = el.value; load(); });
    return el;
  };
  const sel = (k, opts, label) => {
    const el = h("select", { "aria-label": label }, opts.map(([v, l]) => h("option", { value: v, selected: filters[k] === v }, l)));
    el.addEventListener("change", () => { filters[k] = el.value; load(); });
    return el;
  };
  function scoreRange() {
    const presets = [["", "", "Any ATS score"], ["90", "", "90+"], ["80", "", "80+"], ["70", "", "70+"], ["60", "", "60+"], ["50", "", "50+"],
      ["70", "89", "70–89"], ["50", "69", "50–69"], ["custom", "", "Custom range…"]];
    const cur = presets.find(([a, b]) => a === String(filters.min_score || "") && b === String(filters.max_score || ""));
    const s = h("select", { "aria-label": "ATS score range" }, presets.map(([a, b, l]) =>
      h("option", { value: `${a}|${b}`, selected: cur ? cur[0] === a && cur[1] === b : a === "custom" }, l)));
    const lo = h("input", { type: "number", min: 0, max: 100, placeholder: "min", value: filters.min_score, style: { width: "70px" }, "aria-label": "Minimum score" });
    const hi = h("input", { type: "number", min: 0, max: 100, placeholder: "max", value: filters.max_score, style: { width: "70px" }, "aria-label": "Maximum score" });
    const custom = h("div", { class: "row", style: { gap: "4px", display: cur ? "none" : "flex" } }, lo, "–", hi);
    const apply = () => { filters.min_score = lo.value; filters.max_score = hi.value; load(); };
    lo.addEventListener("change", apply); hi.addEventListener("change", apply);
    s.addEventListener("change", () => {
      const [a, b] = s.value.split("|");
      if (a === "custom") { custom.style.display = "flex"; lo.focus(); return; }
      custom.style.display = "none"; filters.min_score = a; filters.max_score = b; lo.value = a; hi.value = b; load();
    });
    return h("div", { class: "stack", style: { gap: "4px" } }, s, custom);
  }
  const qual = h("input", { type: "checkbox", checked: filters.qualified_only });
  qual.addEventListener("change", () => { filters.qualified_only = qual.checked; load(); });
  const sim = h("input", { type: "checkbox", checked: filters.include_simulated });
  sim.addEventListener("change", () => { filters.include_simulated = sim.checked; load(); });

  const saveSearch = h("button", { class: "btn-sm", onclick: async () => {
    const name = h("input", { placeholder: "e.g. Remote backend 80+" });
    const r = await modal("Save this search", field("Name", name), [{ label: "Cancel", value: () => null }, { label: "Save", primary: true, value: () => name.value || false }]);
    if (r) { await api.post("/api/saved-searches", { name: r, filters }); render(root); }
  } }, "Save search");

  const runAll = h("button", { class: "btn-primary" }, "↻ Search all sources");
  runAll.addEventListener("click", busy(runAll, async () => {
    const r = await api.post("/api/discovery/run");
    if (r.started || r.running) { toast(`Checking ${r.sources} sources in the background — new jobs will appear here in a minute or two.`); setTimeout(() => render(root), 45000); return; }
    summarize(r.results);
    render(root);
  }));

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Discover jobs"), h("div", { class: "sub" }, "New postings matching your target roles, scored against your resume like an ATS would.")),
      h("div", { class: "row" }, h("button", { onclick: () => manualJob(root) }, "+ Add a job I found"), runAll)),
    h("div", { class: "card", style: { margin: "16px 0" } },
      h("div", { class: "grid cols-4" },
        inp("q", "Keywords (title, description)"), inp("location", "Location"), inp("company", "Company"),
        sel("remote", [["", "Any workplace"], ["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"], ["remote,hybrid", "Remote or hybrid"]], "Workplace"),
        sel("seniority", [["", "Any seniority"], ["junior", "Junior"], ["mid", "Mid"], ["senior", "Senior"], ["staff,lead", "Staff / lead"], ["manager,director", "Manager+"]], "Seniority"),
        scoreRange(),
        sel("posted_within", [["", "Posted: any time"], ["24", "Last 24 hours"], ["48", "Last 2 days"], ["72", "Last 3 days"], ["168", "Last week"], ["336", "Last 2 weeks"], ["720", "Last month"]], "Posted within"),
        sel("sort", [["score", "Sort: best ATS match"], ["posted", "Sort: newest posted"], ["discovered", "Sort: recently found"], ["score_asc", "Sort: lowest match first"], ["salary", "Sort: highest salary"], ["company", "Sort: company A–Z"]], "Sort"),
        sel("status", [["active", "Active listings"], ["closed", "Closed listings"], ["all", "All listings"]], "Listing status")),
      h("div", { class: "row between", style: { marginTop: "10px" } },
        h("div", { class: "row", style: { gap: "16px" } },
          h("label", { class: "check", title: "Hides roles whose required degree is higher than yours (e.g. PhD-only roles if you have a master's). Roles that accept your degree or higher are kept." }, qual, "Only jobs my degree qualifies for"),
          h("label", { class: "check" }, sim, "Include simulated demo listings")),
        h("div", { class: "row" },
          saved.map((s) => h("span", { class: "row", style: { gap: "2px" } },
            h("button", { class: "btn-sm", onclick: () => { Object.assign(filters, s.filters); render(root); } }, "★ " + s.name),
            h("button", { class: "btn-sm btn-ghost", "aria-label": `Delete saved search ${s.name}`, onclick: async () => { await api.del(`/api/saved-searches/${s.id}`); render(root); } }, "✕"))),
          saveSearch))),
    results,
    h("h2", { style: { margin: "28px 0 0" } }, "Where JobPilot looks for jobs"),
    autoCard(auto, root),
    topTechCard(top, root),
    companiesCard(following, popular, root),
    catalog.some((c) => c.kind === "mock") && h("details", { class: "card", style: { marginTop: "16px" } },
      h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, "Demo data (simulated listings for trying the app)"),
      h("div", { style: { marginTop: "12px" } }, sourcesCard(sources, catalog.filter((c) => c.kind === "mock"), root))));
  load();
}

function autoCard(auto, root) {
  const boxes = auto.sources.map((s) => {
    const on = s.source ? s.source.enabled : (s.default_on && s.key_ok);
    const cb = h("input", { type: "checkbox", checked: on, value: s.kind, disabled: !s.key_ok });
    return h("label", { class: "check small", style: { alignItems: "flex-start", opacity: s.key_ok ? 1 : 0.75 } }, cb,
      h("span", {}, h("strong", {}, s.label.split(" (")[0]), h("span", { class: "faint" }, ` — ${s.note}`),
        !s.key_ok && [" · ", h("a", { href: "#/settings" }, "add key")],
        s.source && s.source.last_status === "error" && h("div", { class: "small", style: { color: "var(--bad)" } }, s.source.last_error)));
  });
  const go = h("button", { class: "btn-primary" }, "🔎 Find new jobs for me");
  go.addEventListener("click", busy(go, async () => {
    const kinds = boxes.map((l) => l.querySelector("input")).filter((i) => i.checked && !i.disabled).map((i) => i.value);
    const r = await api.post("/api/discovery/auto", { kinds });
    const n = r.results.reduce((a, x) => a + (x.new || 0), 0);
    const errs = r.results.filter((x) => x.error).map((x) => `${x.kind}: ${x.error}`);
    toast(`${n} new matching job${n === 1 ? "" : "s"} found.` + (errs.length ? " " + errs.join(" ") : ""), errs.length ? "bad" : "");
    render(root);
  }));
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Find jobs for me"), h("span", { class: "faint" }, "Also runs automatically every day (Settings)")),
    auto.queries.length ? h("p", { class: "small" }, "Searching for ", auto.queries.map((q) => h("span", { class: "chip" }, q)),
      auto.locations.length ? [" in ", auto.locations.map((l) => h("span", { class: "chip" }, l))] : " (any location)",
      " · ", h("a", { href: "#/profile" }, auto.titles_from_profile ? "change" : "set your target titles"))
      : h("div", { class: "alert warn" }, "Tell JobPilot what roles you want: ", h("a", { href: "#/profile" }, "Profile → Job preferences → Target job titles"), "."),
    h("div", { class: "grid cols-2", style: { gap: "6px 20px", margin: "8px 0" } }, boxes),
    h("div", { class: "row", style: { justifyContent: "flex-end" } }, go));
}

const PLATFORM = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", smartrecruiters: "SmartRecruiters", workable: "Workable", recruitee: "Recruitee",
  workday: "Workday", amazon: "Amazon careers site", google: "Google careers site", microsoft: "Microsoft careers site", apple: "Apple careers site",
  eightfold: "Eightfold careers site", oraclehcm: "Oracle careers site", jsearch: "Google Jobs (JSearch)" };

function followToast(out) {
  if (out.background) return toast(`Following ${out.added} new compan${out.added === 1 ? "y" : "ies"} — their jobs are being searched in the background and will appear here in a few minutes.`);
  const n = out.results.reduce((a, x) => a + (x.new || 0), 0);
  toast(`Following ${out.added} new compan${out.added === 1 ? "y" : "ies"} · ${n} matching job${n === 1 ? "" : "s"} found.` + (out.pending ? ` ${out.pending} more will be checked on the next scheduled run.` : ""));
}

function topTechCard(top, root) {
  const all = top.companies;
  const direct = all.filter((c) => c.via === "direct");
  const followingN = all.filter((c) => c.following).length;
  const cats = {};
  all.forEach((c) => (cats[c.category] = cats[c.category] || []).push(c));
  const picks = [];
  const groups = Object.entries(cats).map(([cat, items]) => h("div", { style: { marginBottom: "10px" } },
    h("h3", {}, cat),
    h("div", { class: "row", style: { gap: "4px 12px" } }, items.map((c) => {
      const cb = h("input", { type: "checkbox", checked: c.following, disabled: c.following });
      cb._c = c;
      picks.push(cb);
      return h("label", { class: "check small", style: { minWidth: "190px" }, title: `${PLATFORM[c.kind] || c.kind}` }, cb, c.company,
        c.via === "google_jobs" ? h("span", { class: "faint" }, " · Google Jobs") : null);
    }))));
  const follow = async (items) => {
    if (!items.length) return toast("Nothing new to follow.", "bad");
    const out = await api.post("/api/companies/follow", { items: items.map((c) => ({ kind: c.kind, identifier: c.identifier, company: c.company })) });
    followToast(out);
    render(root);
    if (out.background) setTimeout(() => render(root), 90000);
  };
  const bDirect = h("button", {}, `Follow all ${direct.length} direct feeds`);
  bDirect.addEventListener("click", busy(bDirect, () => follow(direct.filter((c) => !c.following))));
  const bAll = h("button", { class: "btn-primary" }, `Follow all ${all.length}`);
  bAll.addEventListener("click", busy(bAll, () => follow(all.filter((c) => !c.following && (c.via === "direct" || top.jsearch_connected)))));
  const bSel = h("button", {}, "Follow selected");
  bSel.addEventListener("click", busy(bSel, () => follow(picks.filter((b) => b.checked && !b.disabled).map((b) => b._c))));
  return h("div", { class: "card", style: { marginTop: "16px" } },
    h("div", { class: "card-head" }, h("h2", {}, "Top 100 tech companies"), h("span", { class: "faint" }, `Following ${followingN} of ${all.length}`)),
    h("p", { class: "small muted" }, `${direct.length} are searched directly on the company's own careers site or job board (Amazon, Microsoft, Google, Apple, NVIDIA, Salesforce, OpenAI, Stripe…). `,
      `The other ${all.length - direct.length} (Meta, Tesla, Uber, Cisco…) don't offer a feed JobPilot may use, so they're followed through Google Jobs, which is checked weekly per company to stay within JSearch's free plan.`),
    top.jsearch_connected ? null : h("div", { class: "alert warn small" }, "Google Jobs companies need your free JSearch key — ", h("a", { href: "#/settings" }, "Settings → Connections"),
      ". Until then, “Follow all” follows the direct feeds only."),
    h("div", { class: "row", style: { justifyContent: "flex-end", gap: "8px", margin: "8px 0" } }, bDirect, bAll),
    h("details", {}, h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, "Choose individual companies"),
      h("div", { style: { marginTop: "10px" } }, groups, h("div", { class: "row", style: { justifyContent: "flex-end" } }, bSel))));
}

function companiesCard(following, popular, root) {
  const ta = h("textarea", { rows: 4, placeholder: "One per line — a careers page link or just the company name, e.g.\nhttps://stripe.com/jobs\nDatabricks\nhttps://jobs.lever.co/palantir" });
  const results = h("div");
  const find = h("button", { class: "btn-primary" }, "Find these companies");
  find.addEventListener("click", busy(find, async () => {
    const entries = ta.value.split("\n").map((x) => x.trim()).filter(Boolean);
    if (!entries.length) return toast("Paste at least one link or company name.", "bad");
    const res = await api.post("/api/companies/detect", { entries });
    const rows = res.map((r) => {
      const cb = r.status === "found" ? h("input", { type: "checkbox", checked: true }) : null;
      if (cb) cb._item = { kind: r.kind, identifier: r.identifier, company: r.company };
      return { r, cb };
    });
    const follow = h("button", { class: "btn-primary" }, "Follow selected");
    follow.addEventListener("click", busy(follow, async () => {
      const items = rows.filter((x) => x.cb && x.cb.checked).map((x) => x.cb._item);
      if (!items.length) return toast("Nothing selected.", "bad");
      const out = await api.post("/api/companies/follow", { items });
      followToast(out);
      render(root);
    }));
    mount(results, h("div", { class: "table-wrap", style: { marginTop: "10px" } }, h("table", {},
      h("thead", {}, h("tr", {}, ["", "You entered", "Result", "Open roles"].map((t) => h("th", {}, t)))),
      h("tbody", {}, rows.map(({ r, cb }) => h("tr", {},
        h("td", {}, cb || ""),
        h("td", { class: "small" }, r.input),
        h("td", { class: "small" }, r.status === "found" ? [h("strong", {}, r.company), ` · ${PLATFORM[r.kind] || r.kind} (${r.identifier})`, r.message ? h("div", { class: "faint" }, r.message) : null]
          : h("span", { style: { color: r.status === "unsupported" ? "var(--warn)" : "var(--bad)" } }, r.message)),
        h("td", {}, r.status === "found" ? String(r.jobs) : "—")))))),
      h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "8px" } }, follow));
  }));

  const list = following.length ? h("div", { class: "row", style: { gap: "6px" } }, following.map((s) => h("span", { class: "chip", title: `${PLATFORM[s.kind] || s.kind}: ${s.identifier} · last checked ${s.last_run_at ? new Date(s.last_run_at).toLocaleString() : "never"}${s.last_error ? " · " + s.last_error : ""}` },
    s.last_status === "error" ? "⚠ " : "", s.display_name || s.identifier, h("span", { class: "faint" }, ` · ${s.last_job_count}`),
    h("button", { class: "btn-ghost btn-sm", "aria-label": `Stop following ${s.display_name}`, style: { padding: "0 4px" }, onclick: async () => { await api.del(`/api/sources/${s.id}`); render(root); } }, "✕"))))
    : h("p", { class: "muted small" }, "You aren't following any companies yet.");

  // popular list grouped by category
  const cats = {};
  popular.forEach((c) => (cats[c.category] = cats[c.category] || []).push(c));
  const picks = [];
  const groups = Object.entries(cats).map(([cat, items]) => {
    const boxes = items.map((c) => {
      const cb = h("input", { type: "checkbox", checked: c.following, disabled: c.following });
      cb._item = { kind: c.kind, identifier: c.identifier, company: c.company };
      picks.push(cb);
      return h("label", { class: "check small", style: { minWidth: "170px" } }, cb, c.company);
    });
    return h("div", { style: { marginBottom: "10px" } },
      h("div", { class: "row between" }, h("h3", {}, cat),
        h("button", { class: "btn-sm btn-ghost", onclick: () => boxes.forEach((b) => { const i = b.querySelector("input"); if (!i.disabled) i.checked = true; }) }, "Select all")),
      h("div", { class: "row", style: { gap: "4px 12px" } }, boxes));
  });
  const followPopular = h("button", { class: "btn-primary" }, "Follow selected companies");
  followPopular.addEventListener("click", busy(followPopular, async () => {
    const items = picks.filter((b) => b.checked && !b.disabled).map((b) => b._item);
    if (!items.length) return toast("Tick some companies first.", "bad");
    const out = await api.post("/api/companies/follow", { items });
    followToast(out);
    render(root);
  }));

  return h("div", { class: "card", style: { marginTop: "16px" } },
    h("div", { class: "card-head" }, h("h2", {}, `Companies I follow (${following.length})`), h("span", { class: "faint" }, "Checked daily · only roles matching your target titles are added")),
    list,
    h("hr"),
    h("h3", {}, "Add companies"),
    h("p", { class: "small muted" }, "Paste careers-page links or company names. JobPilot finds the company's job board — Greenhouse, Lever, Ashby, SmartRecruiters, Workable, Recruitee, Workday, or its own careers site (Amazon, Microsoft, Google, Apple, Netflix, Oracle). Companies without a usable feed are followed through Google Jobs (needs your free JSearch key)."),
    ta, h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "8px" } }, find), results,
    h("details", { style: { marginTop: "12px" } },
      h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, `Popular companies (${popular.length}, verified to have open roles)`),
      h("div", { style: { marginTop: "10px" } }, groups, h("div", { class: "row", style: { justifyContent: "flex-end" } }, followPopular))));
}

function summarize(results) {
  const n = results.reduce((a, x) => a + x.new, 0), u = results.reduce((a, x) => a + x.updated, 0), c = results.reduce((a, x) => a + x.closed, 0);
  const errs = results.filter((x) => x.error);
  toast(`${n} new · ${u} updated · ${c} closed${errs.length ? ` · ${errs.length} failed` : ""}`, errs.length ? "bad" : "");
}

const EDU = {
  meets: ["good", "Degree matches", "You have the degree this role requires."],
  exceeds: ["good", "Degree exceeds", "Your degree is higher than this role requires."],
  equivalent: ["warn", "Degree or equivalent", "Role asks for a degree or equivalent experience."],
  below: ["bad", "Needs higher degree", "This role requires a higher degree than yours."],
};
function eduBadge(st) {
  const e = EDU[st];
  return e ? h("span", { class: `badge ${e[0]}`, title: e[2] }, e[1]) : null;
}

function jobRow(j) {
  const m = j.match;
  const sal = money(j.salary_min, j.salary_max, j.salary_currency, j.salary_interval);
  return h("div", { class: "job-card", tabindex: 0, role: "link", onclick: () => (location.hash = `#/jobs/${j.id}`),
    onkeydown: (e) => { if (e.key === "Enter") location.hash = `#/jobs/${j.id}`; } },
    scoreRing(m ? m.score : null),
    h("div", {},
      h("div", { class: "t" }, j.title),
      h("div", { class: "m" }, h("strong", {}, j.company), j.location && h("span", {}, "· " + j.location),
        j.remote_type !== "unknown" && h("span", { class: "badge" }, j.remote_type), sal && h("span", { class: "badge good" }, sal),
        j.is_simulated && simBadge(), j.listing_status === "closed" && h("span", { class: "badge bad" }, "Closed"),
        m && (m.flags || []).some((f) => f.startsWith("Work authorization")) && h("span", { class: "badge warn" }, "Sponsorship conflict"),
        m && eduBadge(m.edu_status)),
      h("div", { class: "faint row", style: { marginTop: "3px", gap: "6px" } }, sourceCredit(j.source_kind) || j.source_kind, `· checked ${ago(j.last_checked_at)}`, j.posted_at ? ` · posted ${ago(j.posted_at)}` : "")),
    h("div", { style: { textAlign: "right" } }, j.application ? statusBadge(j.application.status) : m && h("span", { class: `badge ${m.recommendation === "apply" ? "good" : m.recommendation === "review" ? "warn" : ""}` }, m.recommendation)));
}

function sourcesCard(sources, catalog, root) {
  const kind = h("select", { "aria-label": "Source type" }, catalog.map((c) => h("option", { value: c.kind }, c.kind === "mock" ? "Simulated demo source" : c.kind[0].toUpperCase() + c.kind.slice(1))));
  const ident = h("input", { placeholder: "Board token / site name", "aria-label": "Board identifier" });
  const help = h("div", { class: "faint" }, catalog[0]?.identifier_help || "");
  kind.addEventListener("change", () => (help.textContent = catalog.find((c) => c.kind === kind.value)?.identifier_help || ""));
  const add = h("button", { class: "btn-primary" }, "Add source");
  add.addEventListener("click", busy(add, async () => {
    if (!ident.value.trim()) return toast("Enter the board identifier.", "bad");
    const s = await api.post("/api/sources", { kind: kind.value, identifier: ident.value.trim() });
    const r = await api.post(`/api/sources/${s.id}/run`);
    summarize([r]);
    render(root);
  }));
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Job sources"), h("span", { class: "faint" }, "Public Greenhouse and Lever job-board APIs need no credentials.")),
    sources.length ? h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ["Source", "Board", "Status", "Last run", "Jobs", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, sources.map((s) => h("tr", {},
        h("td", {}, s.kind, " ", s.is_simulated && simBadge()),
        h("td", {}, h("strong", {}, s.display_name || s.identifier), h("div", { class: "faint mono" }, s.identifier)),
        h("td", {}, s.last_status === "ok" ? h("span", { class: "badge good" }, "OK") : s.last_status === "error" ? h("span", { class: "badge bad", title: s.last_error }, "Error") : h("span", { class: "badge" }, "Not run"),
          s.last_error && h("div", { class: "small", style: { color: "var(--bad)", maxWidth: "320px" } }, s.last_error)),
        h("td", {}, ago(s.last_run_at)), h("td", {}, String(s.last_job_count)),
        h("td", {}, h("div", { class: "row" },
          runBtn(s, root),
          h("button", { class: "btn-sm", onclick: async () => { await api.patch(`/api/sources/${s.id}?enabled=${!s.enabled}`); render(root); } }, s.enabled ? "Disable" : "Enable"),
          h("button", { class: "btn-sm btn-danger", onclick: async () => { if (await confirmDialog("Remove source?", "Jobs already found are kept with their history.", "Remove", true)) { await api.del(`/api/sources/${s.id}`); render(root); } } }, "Remove")))))))) : h("p", { class: "muted small" }, "No sources yet. Add a company's Greenhouse or Lever board below."),
    h("hr"),
    h("div", { class: "row" }, kind, h("div", { style: { flex: "1", minWidth: "200px" } }, ident), add), help);
}

function runBtn(s, root) {
  const b = h("button", { class: "btn-sm" }, "Run");
  b.addEventListener("click", busy(b, async () => { summarize([await api.post(`/api/sources/${s.id}/run`)]); render(root); }));
  return b;
}

async function manualJob(root) {
  const f = { title: h("input"), company: h("input"), location: h("input"), url: h("input", { type: "url", placeholder: "https://…" }),
    remote_type: h("select", {}, ["unknown", "remote", "hybrid", "onsite"].map((v) => h("option", { value: v }, v))),
    description_text: h("textarea", { rows: 8, placeholder: "Paste the job description" }) };
  const r = await modal("Add a job manually", h("div", { class: "form-grid" },
    field("Title", f.title), field("Company", f.company), field("Location", f.location), field("Workplace", f.remote_type),
    h("div", { class: "full" }, field("Official job URL", f.url)), h("div", { class: "full" }, field("Description", f.description_text))),
    [{ label: "Cancel", value: () => null }, { label: "Add job", primary: true, value: async () => {
      if (!f.title.value || !f.company.value) { toast("Title and company are required.", "bad"); return false; }
      return api.post("/api/jobs/manual", Object.fromEntries(Object.entries(f).map(([k, el]) => [k, el.value])));
    } }]);
  if (r && r.job) location.hash = `#/jobs/${r.job.id}`;
}
