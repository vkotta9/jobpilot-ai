import { api, qs } from "../api.js";
import { h, mount, loading, empty, scoreRing, simBadge, statusBadge, money, ago, field, toast, busy, modal, confirmDialog, sourceCredit } from "../ui.js";

const filters = { q: "", location: "", company: "", remote: "", seniority: "", min_score: "", sort: "score", status: "active", include_simulated: true };

export async function render(root) {
  mount(root, loading());
  const [allSources, catalog, saved, auto] = await Promise.all([api.get("/api/sources"), api.get("/api/sources/catalog"),
    api.get("/api/saved-searches"), api.get("/api/discovery/auto")]);
  const sources = allSources.filter((s) => !["adzuna", "remotive", "muse"].includes(s.kind));
  const results = h("div", { class: "card", style: { padding: 0 } }, loading());

  const load = async () => {
    mount(results, loading());
    const r = await api.get("/api/jobs" + qs(filters));
    mount(results,
      h("div", { class: "row between", style: { padding: "12px 16px", borderBottom: "1px solid var(--border)" } },
        h("strong", {}, `${r.total} job${r.total === 1 ? "" : "s"}`),
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
    summarize(r.results);
    render(root);
  }));

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Discover jobs"), h("div", { class: "sub" }, "New postings matching your target roles, scored against your resume like an ATS would.")),
      h("div", { class: "row" }, h("button", { onclick: () => manualJob(root) }, "+ Add a job I found"), runAll)),
    autoCard(auto, root),
    h("details", { class: "card", style: { marginTop: "16px" } },
      h("summary", { style: { cursor: "pointer", fontWeight: 600 } }, `Advanced: follow specific companies' career boards (${sources.length})`),
      h("div", { style: { marginTop: "12px" } }, sourcesCard(sources, catalog, root))),
    h("div", { class: "card", style: { margin: "16px 0" } },
      h("div", { class: "grid cols-4" },
        inp("q", "Keywords (title, description)"), inp("location", "Location"), inp("company", "Company"),
        sel("remote", [["", "Any workplace"], ["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"], ["remote,hybrid", "Remote or hybrid"]], "Workplace"),
        sel("seniority", [["", "Any seniority"], ["junior", "Junior"], ["mid", "Mid"], ["senior", "Senior"], ["staff,lead", "Staff / lead"], ["manager,director", "Manager+"]], "Seniority"),
        sel("min_score", [["", "Any match score"], ["50", "50+"], ["70", "70+"], ["85", "85+"]], "Minimum score"),
        sel("sort", [["score", "Sort: best match"], ["posted", "Sort: newest posted"], ["discovered", "Sort: recently found"], ["salary", "Sort: salary"], ["company", "Sort: company"]], "Sort"),
        sel("status", [["active", "Active listings"], ["closed", "Closed listings"], ["all", "All listings"]], "Listing status")),
      h("div", { class: "row between", style: { marginTop: "10px" } },
        h("label", { class: "check" }, sim, "Include simulated demo listings"),
        h("div", { class: "row" },
          saved.map((s) => h("span", { class: "row", style: { gap: "2px" } },
            h("button", { class: "btn-sm", onclick: () => { Object.assign(filters, s.filters); render(root); } }, "★ " + s.name),
            h("button", { class: "btn-sm btn-ghost", "aria-label": `Delete saved search ${s.name}`, onclick: async () => { await api.del(`/api/saved-searches/${s.id}`); render(root); } }, "✕"))),
          saveSearch))),
    results);
  load();
}

function autoCard(auto, root) {
  const boxes = auto.sources.map((s) => {
    const cb = h("input", { type: "checkbox", checked: s.source ? s.source.enabled : s.key_ok, value: s.kind });
    return h("label", { class: "check small" }, cb, s.label,
      !s.key_ok && h("a", { href: "#/settings", class: "small" }, " — connect free key"),
      s.source && h("span", { class: "faint" }, ` · last run ${s.source.last_run_at ? new Date(s.source.last_run_at).toLocaleString() : "never"}${s.source.last_status === "error" ? " · error" : ""}`));
  });
  const go = h("button", { class: "btn-primary" }, "🔎 Find new jobs for me");
  go.addEventListener("click", busy(go, async () => {
    const kinds = boxes.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value);
    const r = await api.post("/api/discovery/auto", { kinds });
    const n = r.results.reduce((a, x) => a + (x.new || 0), 0);
    const errs = r.results.filter((x) => x.error).map((x) => `${x.kind}: ${x.error}`);
    const skipped = r.results.filter((x) => x.skipped).map((x) => x.skipped);
    toast(`${n} new matching job${n === 1 ? "" : "s"} found.` + (errs.length ? " " + errs.join(" ") : "") + (skipped.length ? " " + skipped.join(" ") : ""), errs.length ? "bad" : "");
    render(root);
  }));
  const errors = auto.sources.filter((s) => s.source && s.source.last_status === "error").map((s) => h("div", { class: "small", style: { color: "var(--bad)" } }, `${s.label}: ${s.source.last_error}`));
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Find jobs for me"), h("span", { class: "faint" }, "Runs automatically on your schedule too (Settings)")),
    auto.queries.length ? h("p", { class: "small" }, "Searching for ", auto.queries.map((q) => h("span", { class: "chip" }, q)),
      auto.locations.length ? [" in ", auto.locations.map((l) => h("span", { class: "chip" }, l))] : " (any location)",
      " · ", h("a", { href: "#/profile" }, auto.titles_from_profile ? "change" : "set your target titles"))
      : h("div", { class: "alert warn" }, "Tell JobPilot what roles you want: ", h("a", { href: "#/profile" }, "Profile → Job preferences → Target job titles"), "."),
    h("div", { class: "row", style: { gap: "18px", margin: "8px 0" } }, boxes),
    errors,
    h("div", { class: "row between", style: { marginTop: "8px" } },
      h("span", { class: "faint" }, "Adzuna covers most US job boards (free key). Remotive = remote jobs. The Muse = curated companies."), go));
}

function summarize(results) {
  const n = results.reduce((a, x) => a + x.new, 0), u = results.reduce((a, x) => a + x.updated, 0), c = results.reduce((a, x) => a + x.closed, 0);
  const errs = results.filter((x) => x.error);
  toast(`${n} new · ${u} updated · ${c} closed${errs.length ? ` · ${errs.length} failed` : ""}`, errs.length ? "bad" : "");
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
        m && (m.flags || []).some((f) => f.startsWith("Work authorization")) && h("span", { class: "badge warn" }, "Sponsorship conflict")),
      h("div", { class: "faint row", style: { marginTop: "3px", gap: "6px" } }, sourceCredit(j.source_kind) || j.source_kind, `checked ${ago(j.last_checked_at)}`, j.posted_at ? ` · posted ${ago(j.posted_at)}` : "")),
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
