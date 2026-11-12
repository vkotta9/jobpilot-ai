import { api } from "../api.js";
import { h, mount, loading, scoreRing, recBadge, simBadge, statusBadge, money, fmtDate, ago, busy, toast, confirmDialog, modal, sourceCredit } from "../ui.js";

export async function render(root, id) {
  mount(root, loading());
  const [j, trk] = await Promise.all([api.get(`/api/jobs/${id}`), api.get("/api/tracks")]);
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
  });
  const letter = act("✉ Draft cover letter", async () => {
    const d = await api.post(`/api/jobs/${id}/cover-letter`);
    location.hash = `#/documents/${d.id}`;
  });
  const shortlist = act("☆ Shortlist", async () => {
    const r = await api.post(`/api/jobs/${id}/shortlist`);
    toast("Added to your tracker.");
    location.hash = `#/applications/${r.application_id}`;
  });
  const applyNow = act("⚡ Apply with JobPilot", async () => {
    const appId = j.application ? j.application.id : (await api.post(`/api/jobs/${id}/shortlist`)).application_id;
    sessionStorage.setItem("jp_autoapply", String(appId));
    location.hash = `#/applications/${appId}`;
  }, true);
  const triage = (action, msg) => act(action === "skip" ? "✕ Skip" : action === "later" ? "⏸ Later" : "↩ Back to New", async () => {
    await api.post(`/api/jobs/${id}/triage`, { action });
    toast(msg);
    if (action === "restore") render(root, id); else location.hash = "#/discover";
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
            sal && h("span", { class: "badge good" }, sal), m && recBadge(m.recommendation), j.application && statusBadge(j.application.status), j.is_simulated && simBadge(),
            !j.application && j.triage === "skipped" && h("span", { class: "badge" }, "Skipped"), !j.application && j.triage === "later" && h("span", { class: "badge warn" }, "Saved for later")))),
      h("div", { class: "row" },
        (j.apply_url || j.url) && h("a", { class: "btn", href: j.url || j.apply_url, target: "_blank", rel: "noopener noreferrer" }, "Open official posting ↗"),
        j.application ? h("a", { class: "btn", href: `#/applications/${j.application.id}` }, "Application →") : shortlist,
        !j.application && (j.triage === "skipped" || j.triage === "later" ? triage("restore", "Moved back to New.")
          : [triage("skip", "Skipped — it's in Discover → Skipped if you change your mind."), triage("later", "Saved in Discover → Later.")]),
        letter, tailor, !(j.application && ["applied", "assessment", "interview", "offer", "rejected"].includes(j.application.status)) && applyNow)),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        m ? atsCard(m, rescore) : h("div", { class: "alert" }, "Upload your resume (or fill in your profile) to see an ATS match score for this job."),
        m && preferredCard(m),
        m && keywordCard(m),
        (j.relevant_experience || []).length > 0 && h("div", { class: "card" }, h("h2", {}, "Your most relevant experience"),
          j.relevant_experience.map((r) => h("div", { class: "list-item" }, h("div", {}, h("div", { class: "small muted" }, `${r.title} · ${r.company}`), h("div", {}, r.bullet)),
            h("div", {}, r.skills.map((s) => h("span", { class: "chip" }, s)))))),
        h("div", { class: "card" }, h("div", { class: "card-head" }, h("h2", {}, "Job description"), pasteBtn(j, root, id)),
          (j.description_text || "").length < 200 && h("div", { class: "alert warn", style: { marginBottom: "8px" } },
            "JobPilot couldn't fetch this job's full description from the company's site just now — it will try again on the next search. You can also paste it here."),
          h("p", { class: "faint" }, "Shown as plain text exactly as published. It is treated as untrusted data by the AI features."),
          h("div", { class: "desc" }, j.description_text || "No description provided."))),
      h("div", { class: "stack" },
        trackCard(j, trk.tracks, root, id),
        h("div", { class: "card" }, h("h2", {}, "Materials for this job"),
          j.documents.length ? j.documents.map((d) => h("a", { class: "list-item", href: `#/documents/${d.id}`, style: { color: "inherit" } },
            h("div", {}, h("strong", {}, d.kind === "resume" ? "Resume" : "Cover letter"), ` v${d.version}`, h("div", { class: "faint" }, `${d.generator} · ${fmtDate(d.created_at)}`)),
            h("span", { class: `badge ${d.status === "approved" ? "good" : "warn"}` }, d.status)))
            : h("p", { class: "muted small" }, "No tailored materials yet. Your master resume is never changed.")),
        h("div", { class: "card" }, h("h2", {}, "Listing details"),
          kv("Source", sourceCredit(j.source_kind) || (j.source_kind + (j.source ? ` · ${j.source.display_name || j.source.identifier}` : ""))),
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

const LABELS = { keywords: "Skills & keywords", title: "Job title", experience: "Experience", education: "Education", soft_skills: "Soft skills" };

function atsCard(m, rescore) {
  const comps = Object.entries(m.breakdown).filter(([k]) => !k.startsWith("_"));
  const total = comps.reduce((a, [, x]) => a + x.weight, 0) || 1;
  const prefs = m.breakdown._preferences || {};
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "ATS match"), h("div", { class: "row" }, h("span", { class: "faint" }, `scored ${ago(m.created_at)} against your ${m.breakdown._resume_source || "resume"}`), rescore)),
    m.breakdown._fit && h("div", { class: `alert ${m.fit === "good" ? "good" : m.fit === "poor" ? "bad" : "warn"}`, style: { margin: "6px 0" } },
      h("strong", {}, { good: "Good fit. ", stretch: "Stretch role. ", poor: "Poor fit. " }[m.fit] || ""),
      (m.breakdown._fit.reasons || []).filter((r) => !r.startsWith("Good fit")).join(" ") || (m.breakdown._fit.reasons || [])[0]?.replace(/^Good fit: /, "") || ""),
    h("p", {}, m.explanation),
    (m.flags || []).map((f) => h("div", { class: `alert ${f.startsWith("SIMULATED") ? "sim" : "warn"}`, style: { margin: "6px 0" } }, f)),
    h("hr"),
    comps.map(([k, b]) => [
      h("div", { class: "breakdown-row" }, h("span", { style: { fontWeight: 600 } }, LABELS[k] || k),
        h("div", { class: "bar", role: "img", "aria-label": `${k} ${Math.round(b.score * 100)}%` }, h("i", { style: { width: `${Math.round(b.score * 100)}%` } })),
        h("span", { class: "small muted" }, `${b.points} / ${Math.round(100 * b.weight / total)}`)),
      h("p", { class: "breakdown-note" }, b.note)]),
    Object.keys(prefs).length > 0 && h("div", { style: { marginTop: "8px" } }, h("h3", {}, "Your preferences (not part of the ATS score)"),
      Object.entries(prefs).map(([k, v]) => h("div", { class: "small", style: { margin: "3px 0" } },
        h("span", { class: `badge ${v.score >= 0.75 ? "good" : v.score >= 0.4 ? "" : "warn"}`, style: { marginRight: "6px", textTransform: "capitalize" } }, k), v.note))),
    h("p", { class: "faint", style: { marginTop: "8px" } }, "An estimate of how applicant tracking systems rank resumes: keyword overlap with the posting, job title, years, education and soft skills — measured against the preferred qualifications too, since companies shortlist from that bar. Change the weights in your profile. Protected characteristics are never used."));
}

function keywordCard(m) {
  const kws = m.breakdown._keywords || [];
  const hard = kws.filter((k) => k.kind === "hard");
  const req = hard.filter((k) => k.required);
  const pref = hard.filter((k) => !k.required && k.section === "pref");
  const other = hard.filter((k) => !k.required && k.section !== "pref");
  const soft = kws.filter((k) => k.kind === "soft");
  const chips = (list) => list.map((k) => h("span", { class: `chip ${k.found ? "good" : "bad"}`,
    title: (k.found ? "in your resume" : "not in your resume") + (k.any_of ? " · one of a list — any of them counts" : "") }, k.term + (k.any_of ? " ∗" : "")));
  return h("div", { class: "card" }, h("h2", {}, "Keywords from the posting"),
    req.length > 0 && h("div", {}, h("h3", {}, "Required"), chips(req)),
    pref.length > 0 && h("div", { style: { marginTop: "8px" } }, h("h3", {}, "Preferred"), chips(pref)),
    other.length > 0 && h("div", { style: { marginTop: "8px" } }, h("h3", {}, "Also mentioned"), chips(other)),
    soft.length > 0 && h("div", { style: { marginTop: "8px" } }, h("h3", {}, "Soft skills"), chips(soft)),
    !kws.length && h("p", { class: "muted small" }, "No keywords found — paste the full description."),
    h("p", { class: "faint", style: { marginTop: "6px" } }, "Green = found in your resume, red = missing. ∗ = one of an “A, B, or C” list: any of them meets it. ",
      "“Tailor resume” can add the ones you truly have to your skills section."));
}

function preferredCard(m) {
  const p = m.breakdown._preferred;
  if (!p || !(p.skills_total || p.years || p.degree)) return null;
  const row = (ok, text) => h("div", { class: "small", style: { margin: "4px 0" } },
    h("span", { class: `badge ${ok ? "good" : "warn"}`, style: { marginRight: "6px" } }, ok ? "✓" : "gap"), text);
  return h("div", { class: "card" }, h("h2", {}, "Preferred qualifications"),
    h("p", { class: "small muted" }, "Companies shortlist from candidates who meet the preferred bar, not just the minimum — the ATS score counts these."),
    p.skills_total ? row(p.skills_found === p.skills_total, `You meet ${p.skills_found} of ${p.skills_total} preferred qualifications.`) : null,
    p.years ? row(p.meets_years, `${p.years}+ years preferred for your degree` + (p.meets_years ? " — you have it." : " — not yet.")) : null,
    p.degree ? row(p.meets_degree && (!p.degree_route_years || p.meets_years),
      `${{ 1: "A bachelor's", 2: "A master's", 3: "A PhD" }[p.degree] || "A degree"} preferred` +
      (p.degree_route_years ? ` — or your degree with ${p.degree_route_years}+ years` + (p.meets_years ? " (you have that)." : ".")
        : p.meets_degree ? " — you have it." : " — you have a lower degree.")) : null,
    (p.missing || []).length ? h("div", { style: { marginTop: "6px" } }, h("h3", {}, "Not in your resume yet"),
      h("ul", { class: "small", style: { margin: "4px 0 0 18px" } }, p.missing.map((x) => h("li", {}, x)))) : null,
    h("p", { class: "faint small", style: { marginTop: "6px" } }, "Only add what you've really done — tailoring never invents experience."));
}

function pasteBtn(j, root, id) {
  return h("button", { class: "btn-sm", onclick: async () => {
    const ta = h("textarea", { rows: 14, placeholder: "Paste the full job description from the official posting", value: (j.description_text || "").length >= 600 ? j.description_text : "" });
    const r = await modal("Paste the full job description", h("div", {}, ta), [{ label: "Cancel", value: () => null },
      { label: "Save & rescore", primary: true, value: async () => { if (ta.value.trim().length < 50) { toast("Paste the whole description.", "bad"); return false; }
        return api.put(`/api/jobs/${id}/description`, { description_text: ta.value }); } }]);
    if (r) { toast(`Rescored: ${r.score}/100`); render(root, id); }
  } }, "Paste full description");
}

const kv = (k, v) => h("div", { class: "list-item small" }, h("span", { class: "muted" }, k), h("span", { style: { textAlign: "right" } }, v || "—"));

const REASON = { role: "matches this job's role", closest: "closest fit — this title fits none of your tracks", chosen: "your choice" };

function trackCard(j, tracks, root, id) {
  if (!tracks.length) {
    return h("div", { class: "card" }, h("h2", {}, "Resume for this job"),
      h("p", { class: "small muted" }, "Targeting more than one kind of role (e.g. SDE and ML)? Keep a focused resume for each in ",
        h("a", { href: "#/roles" }, "Role tracks"), " and every job is scored and tailored with the right one."));
  }
  const info = (j.match && j.match.breakdown && j.match.breakdown._track) || null;
  const sel = h("select", { "aria-label": "Role track for this job" },
    h("option", { value: "" }, "Let JobPilot choose"),
    tracks.map((t) => h("option", { value: t.id, selected: j.resume_track && j.resume_track.chosen && j.resume_track.id === t.id }, t.name)));
  sel.addEventListener("change", async () => {
    const r = await api.post(`/api/jobs/${id}/track`, { track_id: sel.value ? Number(sel.value) : null });
    toast(`Now using “${r.track ? r.track.name : "best fit"}” — ATS ${r.score}.` + (j.documents.some((d) => d.kind === "resume") ? " Tailor again to use this resume." : ""));
    render(root, id);
  });
  return h("div", { class: "card" }, h("h2", {}, "Resume for this job"),
    j.resume_track ? h("p", {}, h("strong", {}, j.resume_track.name), ` · ${j.resume_track.resume || "primary resume"}`,
      info ? h("div", { class: "faint small" }, REASON[info.reason] || "") : null) : h("p", { class: "muted small" }, "Not scored against a track yet."),
    info && info.scores.length > 1 ? h("div", { class: "small", style: { margin: "6px 0" } }, "ATS by track: ",
      info.scores.map((s) => h("span", { class: `badge ${s.id === info.id ? "good" : ""}`, style: { marginRight: "4px" } }, `${s.name} ${s.score}`))) : null,
    h("div", { class: "row", style: { alignItems: "center", gap: "8px", marginTop: "6px" } }, h("span", { class: "small" }, "Use:"), sel),
    h("p", { class: "faint small", style: { marginTop: "6px" } }, "Tailoring, the cover letter and ⚡ Apply use this track's resume."));
}
