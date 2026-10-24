import { api } from "../api.js";
import { h, mount, loading, busy, toast, fmtDate, modal } from "../ui.js";

export async function render(root, id) {
  mount(root, loading());
  const d = await api.get(`/api/documents/${id}`);
  const c = d.content;
  const isResume = d.kind === "resume";
  const editors = [];

  const save = h("button", {}, "Save edits");
  const approve = h("button", { class: "btn-primary" }, "✓ Approve");
  const collect = () => {
    if (!isResume) return { body: editors[0].value };
    const out = JSON.parse(JSON.stringify(c));
    out.summary = editors.summary.value;
    out.skills = editors.skills.value.split(",").map((s) => s.trim()).filter(Boolean);
    out.experience.forEach((e, ei) => e.bullets.forEach((b, bi) => { b.text = editors[`e${ei}`][bi].value.trim(); }));
    out.experience.forEach((e) => (e.bullets = e.bullets.filter((b) => b.text)));
    return out;
  };
  save.addEventListener("click", busy(save, async () => {
    await api.put(`/api/documents/${id}`, { content: collect() });
    toast("Saved. Re-approve when you're happy with it.");
    render(root, id);
  }));
  approve.addEventListener("click", busy(approve, async () => {
    const ok = await modal("Approve this document?", h("p", {}, "I reviewed every line and confirm it accurately describes my real experience."),
      [{ label: "Cancel", value: () => null }, { label: "I confirm — approve", primary: true, value: () => true }]);
    if (!ok) return;
    if (JSON.stringify(collect()) !== JSON.stringify(isResume ? c : { body: c.body })) await api.put(`/api/documents/${id}`, { content: collect() });
    await api.post(`/api/documents/${id}/approve`, { confirm: true });
    toast("Approved.");
    render(root, id);
  }));
  const dl = (fmt) => h("button", { onclick: () => api.file(`/api/documents/${id}/download?format=${fmt}`, `${d.kind}.${fmt}`) }, `⬇ ${fmt.toUpperCase()}`);

  const flags = (d.flags || []).map((f) => h("div", { class: "alert warn", style: { marginBottom: "6px" } }, f.message,
    f.suggested && h("div", { class: "small", style: { marginTop: "4px" } }, "Suggested (rejected) text: ", h("em", {}, f.suggested))));

  let body;
  if (isResume) {
    editors.summary = h("textarea", { rows: 3, value: c.summary, "aria-label": "Summary" });
    editors.skills = h("textarea", { rows: 2, value: (c.skills || []).join(", "), "aria-label": "Skills order" });
    const kw = c.keywords || {};
    body = h("div", { class: "stack" },
      h("div", { class: "card" }, h("h2", {}, "Keyword coverage"),
        h("p", { class: "small muted" }, `${(kw.covered || []).length} of ${(kw.targeted || []).length} posting keywords are evidenced in your profile and emphasised.`),
        (kw.covered || []).map((k) => h("span", { class: "chip good" }, k)), (kw.missing || []).map((k) => h("span", { class: "chip bad", title: "Not in your profile — not added" }, k))),
      h("div", { class: "card" }, h("h2", {}, "Summary"), editors.summary,
        h("h2", { style: { marginTop: "14px" } }, "Skills (reordered for this job)"), editors.skills,
        h("p", { class: "faint" }, "You can reorder or remove skills. Adding a skill here doesn't add it to your profile.")),
      h("div", { class: "card" },
        h("div", { class: "card-head" }, h("h2", {}, "Experience"), h("span", { class: "faint" }, "Left: your original wording · Right: tailored version (editable)")),
        c.experience.map((e, ei) => {
          editors[`e${ei}`] = [];
          return h("div", { style: { marginBottom: "16px" } },
            h("div", { class: "row between" }, h("strong", {}, `${e.title} — ${e.company}`), h("span", { class: "faint" }, `${e.start} – ${e.end} · 🔒 locked to profile`)),
            e.bullets.map((b) => {
              const ta = h("textarea", { value: b.text, "aria-label": "Tailored bullet" });
              editors[`e${ei}`].push(ta);
              return h("div", { class: `diff ${b.changed ? "changed" : ""} ${b.flagged ? "flagged" : ""}`, style: { marginTop: "8px" } },
                h("div", { class: "orig" }, b.original, b.keywords?.length ? h("div", { class: "faint", style: { marginTop: "4px" } }, "matches: " + b.keywords.join(", ")) : null),
                h("div", {}, ta, b.note && h("div", { class: "small", style: { color: "var(--warn)" } }, b.note)));
            }));
        })));
  } else {
    const ta = h("textarea", { rows: 18, value: c.body, "aria-label": "Cover letter" });
    editors.push(ta);
    body = h("div", { class: "card" }, h("h2", {}, "Cover letter"),
      h("p", { class: "small muted" }, "Replace every [[ADD: …]] placeholder with your own words before approving."), ta);
  }

  mount(root,
    h("div", { class: "faint", style: { marginBottom: "8px" } }, h("a", { href: `#/jobs/${c.target?.job_id}` }, `← ${c.target?.title} @ ${c.target?.company}`)),
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, `${isResume ? "Tailored resume" : "Cover letter"} · v${d.version}`),
        h("div", { class: "sub" }, `Generated by ${d.generator} on ${fmtDate(d.created_at, true)} · `,
          h("span", { class: `badge ${d.status === "approved" ? "good" : "warn"}` }, d.status === "approved" ? `approved ${fmtDate(d.approved_at)}` : "draft — needs your approval"))),
      h("div", { class: "row" }, dl("pdf"), dl("docx"), save, approve)),
    d.placeholders.length > 0 && h("div", { class: "alert warn", style: { marginBottom: "10px" } }, `${d.placeholders.length} placeholder(s) to fill: ${d.placeholders.join(" ")}`),
    flags.length > 0 && h("div", { style: { marginBottom: "12px" } }, flags),
    body);
}
