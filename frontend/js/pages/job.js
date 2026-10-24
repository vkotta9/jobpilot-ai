import { api } from "../api.js";
import { h, mount, loading, scoreRing, recBadge, simBadge, statusBadge, money, fmtDate, ago, busy, toast, confirmDialog } from "../ui.js";

export async function render(root, id) {
  mount(root, loading());
  const j = await api.get(`/api/jobs/${id}`);
  const m = j.match;
  const sal = money(j.salary_min, j.salary_max, j.salary_currency, j.salary_interval);

  const act = (label, fn, primary = false) => {
    const b = h("button", { class: primary ? "btn-primary" : "" }, label);
    b.addEventListener("click", busy(b, fn));
    return b;
  };
  const tailor = act("✎ Tailor resume", async () => {
    const d = await api.post(`/api/jobs/${id}/resume/tailor`);
    location.hash = `#/documents/${d.id}`;
  }, true);
  const letter = act("✉ Draft cover letter", async () => {
    const d = await api.post(`/api/jobs/${id}/cover-letter`);
    location.hash = `#/documents/${d.id}`;
  });
  const shortlist = act("☆ Shortlist", async () => {
    const r = await api.post(`/api/jobs/${id}/shortlist`);
    toast("Added to your tracker.");
    location.hash = `#/applications/${r.application_id}`;
  });
  const rescore = act("Recalculate", async () => { await api.post(`/api/jobs/${id}/rescore`); render(root, id); });

  mount(root,
    h("div", { class: "faint", style: { marginBottom: "8px" } }, h("a", { href: "#/discover" }, "← Discover")),
    j.is_simulated && h("div", { class: "alert sim", style: { marginBottom: "12px" } }, "SIMULATED listing from the demo source. It is not a real job — use it only to try the workflow."),
    j.listing_status === "closed" && h("div", { class: "alert bad", style: { marginBottom: "12px" } }, `This listing no longer appears on its source board (checked ${ago(j.last_checked_at)}).`),
    h("div", { class: "page-head" },
      h("div", { class: "row", style: { alignItems: "flex-start", gap: "16px" } }, scoreRing(m ? m.score : null, true),
        h("div", {}, h("h1", {}, j.title),
          h("div", { class: "sub" }, h("strong", {}, j.company), j.location ? ` · ${j.location}` : "", j.department ? ` · ${j.department}` : ""),
          h("div", { class: "row", style: { marginTop: "8px" } },
            j.remote_type !== "unknown" && h("span", { class: "badge" }, j.remote_type), j.employment_type && h("span", { class: "badge" }, j.employment_type),
            sal && h("span", { class: "badge good" }, sal), m && recBadge(m.recommendation), j.application && statusBadge(j.application.status), j.is_simulated && simBadge()))),
      h("div", { class: "row" },
        (j.apply_url || j.url) && h("a", { class: "btn", href: j.url || j.apply_url, target: "_blank", rel: "noopener noreferrer" }, "Open official posting ↗"),
        j.application ? h("a", { class: "btn", href: `#/applications/${j.application.id}` }, "Application →") : shortlist,
        letter, tailor)),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        m ? h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "Match analysis"), h("div", { class: "row" }, h("span", { class: "faint" }, `scored ${ago(m.created_at)}`), rescore)),
          h("p", {}, m.explanation),
          (m.flags || []).map((f) => h("div", { class: `alert ${f.startsWith("SIMULATED") ? "sim" : "warn"}`, style: { margin: "6px 0" } }, f)),
          h("hr"),
          Object.entries(m.breakdown).map(([k, b]) => [
            h("div", { class: "breakdown-row" }, h("span", { style: { textTransform: "capitalize", fontWeight: 600 } }, k),
              h("div", { class: "bar", role: "img", "aria-label": `${k} ${Math.round(b.score * 100)}%` }, h("i", { style: { width: `${Math.round(b.score * 100)}%` } })),
              h("span", { class: "small muted" }, `${b.points} / ${Math.round(100 * b.weight / Object.values(m.breakdown).reduce((a, x) => a + x.weight, 0))}`)),
            h("p", { class: "breakdown-note" }, b.note)]),
          h("p", { class: "faint" }, "Score = weighted sum of the components above (points earned / points possible). Change weights in your profile. Protected characteristics are never used.")
        ) : h("div", { class: "alert" }, "Complete your profile to see a match score for this job."),
        m && h("div", { class: "card" }, h("div", { class: "grid cols-2" },
          h("div", {}, h("h3", {}, `Evidenced skills (${m.matched_skills.length})`), m.matched_skills.map((s) => h("span", { class: "chip good" }, s)), !m.matched_skills.length && h("p", { class: "muted small" }, "None found.")),
          h("div", {}, h("h3", {}, `Missing or not evidenced (${m.missing_skills.length})`), m.missing_skills.map((s) => h("span", { class: "chip bad" }, s)),
            h("p", { class: "faint", style: { marginTop: "6px" } }, "If you genuinely have one of these, add it to your profile with evidence — JobPilot won't add it for you.")))),
        (j.relevant_experience || []).length > 0 && h("div", { class: "card" }, h("h2", {}, "Your most relevant experience"),
          j.relevant_experience.map((r) => h("div", { class: "list-item" }, h("div", {}, h("div", { class: "small muted" }, `${r.title} · ${r.company}`), h("div", {}, r.bullet)),
            h("div", {}, r.skills.map((s) => h("span", { class: "chip" }, s)))))),
        h("div", { class: "card" }, h("h2", {}, "Job description"),
          h("p", { class: "faint" }, "Shown as plain text exactly as published. It is treated as untrusted data by the AI features."),
          h("div", { class: "desc" }, j.description_text || "No description provided."))),
      h("div", { class: "stack" },
        h("div", { class: "card" }, h("h2", {}, "Materials for this job"),
          j.documents.length ? j.documents.map((d) => h("a", { class: "list-item", href: `#/documents/${d.id}`, style: { color: "inherit" } },
            h("div", {}, h("strong", {}, d.kind === "resume" ? "Resume" : "Cover letter"), ` v${d.version}`, h("div", { class: "faint" }, `${d.generator} · ${fmtDate(d.created_at)}`)),
            h("span", { class: `badge ${d.status === "approved" ? "good" : "warn"}` }, d.status)))
            : h("p", { class: "muted small" }, "No tailored materials yet. Your master resume is never changed.")),
        h("div", { class: "card" }, h("h2", {}, "Listing details"),
          kv("Source", j.source_kind + (j.source ? ` · ${j.source.display_name || j.source.identifier}` : "")),
          kv("External ID", j.external_id), kv("Posted", fmtDate(j.posted_at)), kv("Discovered", fmtDate(j.discovered_at, true)),
          kv("Last checked", fmtDate(j.last_checked_at, true)),
          kv("Application URL", j.apply_url ? h("a", { href: j.apply_url, target: "_blank", rel: "noopener noreferrer" }, "official form ↗") : "—"),
          kv("Versions", `${j.history.length} snapshot(s) of this listing`),
          j.duplicates.length > 0 && kv("Also listed on", j.duplicates.map((d) => d.source_kind).join(", ")),
          h("hr"),
          h("div", { class: "row" },
            h("a", { class: "btn btn-sm", href: `#/networking?job=${j.id}` }, "Find people to contact"),
            h("button", { class: "btn-sm btn-danger", onclick: async () => {
              if (await confirmDialog("Delete this job?", "Removes the job, its scores and materials from JobPilot.", "Delete", true)) { await api.del(`/api/jobs/${id}`); location.hash = "#/discover"; }
            } }, "Delete"))))));
}

const kv = (k, v) => h("div", { class: "list-item small" }, h("span", { class: "muted" }, k), h("span", { style: { textAlign: "right" } }, v || "—"));
