import { api } from "../api.js";
import { h, mount, loading, scoreRing, simBadge, statusBadge, fmtDate, ago, empty, busy, toast } from "../ui.js";

export async function render(root) {
  mount(root, loading());
  const d = await api.get("/api/dashboard");
  const c = d.counts;
  const steps = [
    [d.has_profile, "Build your profile", "Experience, skills and preferences — the source of truth.", "#/profile"],
    [d.has_resume, "Upload your master resume", "PDF or DOCX. Never overwritten by tailored versions.", "#/resumes"],
    [d.has_sources, "Add a job source", "Greenhouse or Lever boards of companies you like.", "#/discover"],
  ];
  const runBtn = h("button", { class: "btn-primary" }, "↻ Run job search now");
  runBtn.addEventListener("click", busy(runBtn, async () => {
    const r = await api.post("/api/discovery/run");
    const n = r.results.reduce((a, x) => a + x.new, 0);
    const errs = r.results.filter((x) => x.error);
    toast(errs.length ? `${n} new jobs; ${errs.length} source(s) failed — see Discover.` : `${n} new jobs found.`, errs.length ? "bad" : "");
    render(root);
  }));

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Dashboard"),
        h("div", { class: "sub" }, d.automation_paused ? "Automation is paused." :
          `Scheduled search last ran ${ago(d.last_auto_search_at)}.`, d.llm_configured ? "" : " AI model not configured — using rule-based generation.", " Counts here include simulated demo data; Analytics excludes it by default.")),
      runBtn),
    steps.some((s) => !s[0]) && h("div", { class: "card", style: { marginBottom: "16px" } },
      h("h2", {}, "Get set up"),
      h("div", { class: "onboard" }, steps.map(([done, t, s, href]) =>
        h("a", { href, class: `step ${done ? "done" : ""}`, style: { color: "inherit", textDecoration: "none" } },
          h("strong", {}, (done ? "✓ " : "○ ") + t), h("div", { class: "small muted" }, s))))),
    h("div", { class: "grid cols-4", style: { marginBottom: "16px" } },
      stat(c.jobs_discovered, "Jobs discovered", "incl. simulated"),
      stat(c.high_match_jobs, "High-match jobs", "above your threshold"),
      stat(c.applications_submitted, "Applications submitted", `${c.submissions_verified} verified · ${c.submissions_user_reported} self-reported`),
      stat(c.interviews, "Interviews", `${c.offers} offer(s)`)),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "Needs your attention"), h("a", { href: "#/tracker" }, "Tracker →")),
          d.digest.attention.length ? d.digest.attention.map((a) =>
            h("div", { class: "list-item" },
              h("div", {}, h("div", { style: { fontWeight: 600 } }, a.title, a.company ? ` · ${a.company}` : ""),
                h("div", { class: "small muted" }, a.action)),
              h("div", { class: "row" }, a.overdue && h("span", { class: "badge bad" }, "Overdue"),
                a.status !== "task" && statusBadge(a.status),
                a.application_id && h("a", { class: "btn btn-sm", href: `#/applications/${a.application_id}` }, "Open"))))
            : empty("✓", "All caught up", "Nothing is waiting on you right now.")),
        h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "New high-match jobs (7 days)"), h("a", { href: "#/discover" }, "All jobs →")),
          d.digest.high_match.length ? d.digest.high_match.map((j) =>
            h("a", { class: "list-item", href: `#/jobs/${j.job_id}`, style: { color: "inherit" } },
              h("div", { class: "row" }, scoreRing(j.score), h("div", {}, h("div", { style: { fontWeight: 600 } }, j.title), h("div", { class: "small muted" }, j.company))),
              j.simulated && simBadge()))
            : empty("⌕", "No high-match jobs yet", "Add sources and complete your profile to get scored matches."))),
      h("div", { class: "stack" },
        h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "Upcoming follow-ups"), h("a", { href: "#/followups" }, "Calendar →")),
          d.digest.tasks_due.length ? d.digest.tasks_due.slice(0, 8).map((t) =>
            h("div", { class: "list-item" }, h("div", { class: "small" }, t.title),
              h("span", { class: `badge ${t.overdue ? "bad" : ""}` }, fmtDate(t.due_at))))
            : h("p", { class: "muted small" }, "No follow-ups due this week.")),
        h("div", { class: "card" }, h("h2", {}, "Pipeline"),
          Object.entries(d.status_counts).filter(([, n]) => n).map(([s, n]) =>
            h("div", { class: "list-item" }, statusBadge(s), h("strong", {}, String(n)))),
          !Object.values(d.status_counts).some(Boolean) && h("p", { class: "muted small" }, "Shortlist a job to start tracking it.")))));
}

const stat = (v, l, hint) => h("div", { class: "card stat" }, h("div", { class: "v" }, String(v)), h("div", { class: "l" }, l), hint && h("div", { class: "h" }, hint));
