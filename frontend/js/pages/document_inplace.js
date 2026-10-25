// Review page for format-preserving tailoring: the user's own resume with
// line-by-line suggestions and skill additions, plus a live preview.
import { api } from "../api.js";
import { h, mount, busy, toast, fmtDate, modal } from "../ui.js";

const plain = (s) => (s || "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();

function atsBadge(label, a, prev) {
  if (!a) return null;
  const c = a.score >= 70 ? "var(--good)" : a.score >= 50 ? "var(--warn)" : "var(--bad)";
  const delta = prev ? a.score - prev.score : null;
  return h("div", { class: "stat", style: { textAlign: "center" } },
    h("div", { class: "v", style: { color: c } }, String(a.score), delta ? h("span", { class: "small", style: { marginLeft: "6px", color: delta > 0 ? "var(--good)" : "var(--bad)" } }, `${delta > 0 ? "+" : ""}${delta}`) : null),
    h("div", { class: "l" }, label));
}

export async function renderInplace(root, d) {
  const c = d.content;
  const id = d.id;
  const pdf = c.file_kind === "pdf";
  let page = 0;
  let showAll = false;
  const state = JSON.parse(JSON.stringify({ units: c.units, skills: c.skills, skill_removals: c.skill_removals || [] }));

  const img = h("img", { alt: "Preview of your tailored resume", style: { width: "100%", border: "1px solid var(--border)", borderRadius: "8px", background: "#fff" } });
  const refreshPreview = () => { if (pdf) img.src = `/api/documents/${id}/preview.png?page=${page}&t=${Date.now()}`; };
  img.addEventListener("error", () => toast("Preview couldn't be rendered — a change is probably too long for its line.", "bad"));

  const save = async () => {
    const r = await api.put(`/api/documents/${id}`, { content: state });
    toast("Saved. Preview updated.");
    return r;
  };

  const changed = (u) => u.accepted && plain(u.final) !== plain(u.original);
  const nChanges = () => state.units.filter(changed).length + state.skills.filter((s) => s.selected && s.placed !== "summary").length
    + state.skill_removals.filter((r) => r.remove).length;

  const unitRow = (u) => {
    const ta = h("textarea", { rows: Math.max(3, Math.ceil(plain(u.final).length / 45)), value: u.final, "aria-label": "Tailored text" });
    const cb = h("input", { type: "checkbox", checked: u.accepted });
    const count = h("span", { class: "faint" });
    let typed = false;  // JobPilot's own suggestions are already checked to fit; warn only about the user's edits
    const updCount = () => {
      const n = plain(ta.value).length, o = plain(u.original).length;
      const warn = typed && n > o * 1.06;
      count.textContent = `${n} / ${o} chars` + (warn ? " — may not fit" : "");
      count.style.color = warn ? "var(--warn)" : "";
    };
    ta.addEventListener("input", () => { typed = true; u.final = ta.value; u.accepted = true; cb.checked = true; updCount(); });
    cb.addEventListener("change", () => { u.accepted = cb.checked; });
    updCount();
    const status = { suggested: ["good", "AI suggestion"], rules: ["good", "matched to the job"], edited: ["accent", "your edit"], rejected_guard: ["warn", "needs your check"], too_long: ["warn", "too long"], unchanged: ["", "unchanged"] }[u.status] || ["", u.status];
    return h("div", { style: { padding: "12px 0", borderBottom: "1px solid var(--border)" } },
      h("div", { class: "row between" }, h("span", { class: "faint" }, `${u.heading || u.section}${u.kind === "paragraph" ? " · paragraph" : ""}`),
        h("span", { class: `badge ${status[0]}` }, status[1])),
      h("div", { class: "diff", style: { marginTop: "6px" } },
        h("div", { class: "orig" }, h("div", { class: "faint" }, "Your original"), plain(u.original)),
        h("div", {}, ta, h("div", { class: "row between" }, h("label", { class: "check small" }, cb, "Use this version"), count))),
      u.note && h("div", { class: "small", style: { color: "var(--warn)" } }, u.note),
      u.status === "rejected_guard" && u.proposed && h("button", { class: "btn-sm", onclick: () => { ta.value = u.proposed; u.final = u.proposed; u.accepted = true; cb.checked = true; updCount(); } }, "Load the suggestion (only if it's true)"));
  };

  const unitsBox = h("div");
  const drawUnits = () => {
    const list = state.units.filter((u) => u.kind !== "skill_line" && (showAll || u.status !== "unchanged" || changed(u)));
    mount(unitsBox, list.length ? list.map(unitRow) : h("p", { class: "muted small" }, c.units.some((u) => u.kind !== "skill_line") ?
      "No sentence suggestions for this job. Use “Edit any line” to adjust lines yourself." : "No editable lines were found."));
  };

  const skillRow = (s) => {
    const cb = h("input", { type: "checkbox", checked: s.selected, disabled: !s.fits && !s.selected });
    cb.addEventListener("change", () => { s.selected = cb.checked; });
    if (s.placed === "summary") {
      return h("div", { class: "small", style: { margin: "4px 0" } }, "✓ ", h("strong", {}, s.display),
        h("span", { class: "faint" }, " → added to your summary (no room left on the skills line)"));
    }
    return h("label", { class: "check small", style: { margin: "4px 0" } }, cb, h("strong", {}, s.display),
      h("span", { class: "faint" }, ` → ${s.label || "skills line"}`),
      !s.fits && h("span", { class: "badge warn", title: "Even after removing skills this job doesn't mention, the line is full" }, "no room on that line"));
  };
  const removalRow = (r) => {
    const cb = h("input", { type: "checkbox", checked: r.remove });
    cb.addEventListener("change", () => { r.remove = cb.checked; });
    return h("label", { class: "check small", style: { margin: "4px 0" } }, cb, "Remove ", h("strong", {}, r.display),
      h("span", { class: "faint" }, ` from ${r.label || "skills line"}`));
  };
  const ev = state.skills.filter((s) => s.evidenced), unev = state.skills.filter((s) => !s.evidenced);

  const saveBtn = h("button", {}, "Save & refresh preview");
  saveBtn.addEventListener("click", busy(saveBtn, async () => { await save(); render(); }));
  const approve = h("button", { class: "btn-primary" }, "✓ Approve");
  approve.addEventListener("click", busy(approve, async () => {
    const ok = await modal("Approve this resume?", h("p", {}, "I checked every change and the skills I added — they're true for me."),
      [{ label: "Cancel", value: () => null }, { label: "I confirm — approve", primary: true, value: () => true }]);
    if (!ok) return;
    await save();
    await api.post(`/api/documents/${id}/approve`, { confirm: true });
    toast("Approved.");
    render();
  }));
  const dl = h("button", { onclick: () => api.file(`/api/documents/${id}/download?format=${c.file_kind}`, `resume.${c.file_kind}`) }, `⬇ Download ${c.file_kind.toUpperCase()}`);

  async function render() {
    const fresh = await api.get(`/api/documents/${id}`);
    Object.assign(c, fresh.content);
    d = fresh;
    drawAll();
  }

  function drawAll() {
    const kwBefore = new Set(c.ats_before?.matched || []);
    const after = c.ats_after || c.ats_before;
    mount(root,
      h("div", { class: "faint", style: { marginBottom: "8px" } }, h("a", { href: `#/jobs/${c.target?.job_id}` }, `← ${c.target?.title} @ ${c.target?.company}`)),
      h("div", { class: "page-head" },
        h("div", {}, h("h1", {}, `Tailored resume · v${d.version}`),
          h("div", { class: "sub" }, `Your file “${c.resume_filename}” with ${nChanges()} change(s) — same layout, fonts and contact details. Generated ${fmtDate(d.created_at, true)} · `,
            h("span", { class: `badge ${d.status === "approved" ? "good" : "warn"}` }, d.status === "approved" ? `approved ${fmtDate(d.approved_at)}` : "draft — needs your approval"))),
        h("div", { class: "row" }, dl, saveBtn, approve)),
      (d.flags || []).map((f) => h("div", { class: "alert warn", style: { marginBottom: "8px" } }, f.message)),
      (c.warnings && Object.values(c.warnings).flat().length) ? h("div", { class: "alert", style: { marginBottom: "8px" } }, Object.values(c.warnings).flat().join(" ")) : null,
      h("div", { class: "grid", style: { gridTemplateColumns: "minmax(0,1.1fr) minmax(0,1fr)", alignItems: "start" } },
        h("div", { class: "stack" },
          h("div", { class: "card" },
            h("div", { class: "card-head" }, h("h2", {}, "ATS match for this job"), h("span", { class: "faint" }, "estimate — keyword, title, experience, education")),
            h("div", { class: "row", style: { gap: "28px" } }, atsBadge("Original", c.ats_before), h("span", { class: "faint" }, "→"), atsBadge("Tailored", after, c.ats_before)),
            h("div", { style: { marginTop: "10px" } },
              (after?.matched || []).map((k) => h("span", { class: "chip good", title: kwBefore.has(k) ? "already matched" : "newly matched" }, (kwBefore.has(k) ? "" : "＋ ") + k)),
              (after?.missing || []).map((k) => h("span", { class: "chip bad", title: (after.missing_required || []).includes(k) ? "required in the posting" : "mentioned in the posting" }, k + ((after.missing_required || []).includes(k) ? " *" : "")))),
            h("p", { class: "faint", style: { marginTop: "6px" } }, "Red = not in your resume (* = listed as required). JobPilot never adds a skill you don't tick.")),
          h("div", { class: "card" },
            h("div", { class: "card-head" }, h("h2", {}, "Sentence changes"),
              h("button", { class: "btn-sm", onclick: () => { showAll = !showAll; drawUnits(); } }, showAll ? "Show only changes" : "Edit any line")),
            h("p", { class: "faint" }, "Words between **double asterisks** stay bold, like in your original. Keep each line about the same length so your layout doesn't move."),
            unitsBox),
          h("div", { class: "card" }, h("h2", {}, "Skills"),
            !state.skills.length && h("p", { class: "muted small" }, "Your skills section already covers the posting's skills."),
            ev.length > 0 && h("div", {}, h("h3", {}, "Shown elsewhere in your resume (recommended)"), ev.map(skillRow)),
            unev.length > 0 && h("div", { style: { marginTop: "10px" } }, h("h3", {}, "Not in your resume — tick only if you really have it"), unev.map(skillRow)),
            state.skill_removals.length > 0 && h("div", { style: { marginTop: "10px" } },
              h("h3", {}, "Removed to make room"),
              h("p", { class: "faint" }, "These skills aren't mentioned in this job, so they were taken off this version to fit the job's skills at your normal font size. The job's skills are also listed first. Untick to keep one (the line may then need a slightly smaller font). Your master resume isn't changed."),
              state.skill_removals.map(removalRow)))),
        h("div", { class: "card", style: { position: "sticky", top: "12px" } },
          h("div", { class: "card-head" }, h("h2", {}, "Preview"),
            pdf && (fresh_pages() > 1) && h("div", { class: "row" },
              h("button", { class: "btn-sm", onclick: () => { page = Math.max(0, page - 1); refreshPreview(); } }, "‹"),
              h("button", { class: "btn-sm", onclick: () => { page = Math.min(fresh_pages() - 1, page + 1); refreshPreview(); } }, "›"))),
          pdf ? img : h("p", { class: "muted small" }, "Live preview is available for PDF resumes. Download the DOCX to see your formatted Word file."))));
    drawUnits();
    refreshPreview();
  }
  const fresh_pages = () => d.pages || 1;
  drawAll();
}
