import { api } from "../api.js";
import { h, mount, loading, empty, fmtDate, toast, busy, confirmDialog } from "../ui.js";

export async function render(root) {
  mount(root, loading());
  const resumes = await api.get("/api/resumes");
  const file = h("input", { type: "file", accept: ".pdf,.docx", "aria-label": "Choose resume file" });
  const up = h("button", { class: "btn-primary" }, "Upload");
  up.addEventListener("click", busy(up, async () => {
    if (!file.files[0]) return toast("Choose a PDF or DOCX file first.", "bad");
    const fd = new FormData();
    fd.append("file", file.files[0]);
    const r = await api.post("/api/resumes", fd);
    toast(r.duplicate ? "This exact file is already in your library." : "Resume uploaded and parsed. Review it below.");
    render(root);
  }));

  mount(root,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Resume library"),
      h("div", { class: "sub" }, "Master resumes are stored privately and never modified. Tailored versions live with each job."))),
    h("div", { class: "card", style: { marginBottom: "16px" } },
      h("h2", {}, "Upload a master resume"),
      h("p", { class: "small muted" }, "PDF or DOCX, up to 5 MB. Text-based files work best (scanned images can't be read)."),
      h("div", { class: "row" }, file, up)),
    resumes.length ? h("div", { class: "stack" }, resumes.map((r) => resumeCard(r, root)))
      : h("div", { class: "card" }, empty("▣", "No resumes yet", "Upload your resume to pre-fill your profile.")));
}

function resumeCard(r, root) {
  const p = r.parsed || {};
  const fill = h("button", {}, "Fill empty profile fields");
  fill.addEventListener("click", busy(fill, async () => {
    const res = await api.post(`/api/resumes/${r.id}/apply-to-profile`);
    toast(res.updated_fields.length ? `Updated: ${res.updated_fields.join(", ")}. Review your profile.` : "Nothing to fill — your profile already has these fields.");
  }));
  const over = h("button", { class: "btn-danger" }, "Replace profile with this");
  over.addEventListener("click", async () => {
    if (!(await confirmDialog("Replace profile data?", "Fields found in this resume will overwrite your profile. A revision snapshot is saved first, so this can be restored.", "Replace", true))) return;
    const res = await api.post(`/api/resumes/${r.id}/apply-to-profile?overwrite=true`);
    toast(`Replaced: ${res.updated_fields.join(", ")}`);
    location.hash = "#/profile";
  });
  return h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("div", {}, h("h2", {}, r.original_filename, " ", r.is_primary && h("span", { class: "badge accent" }, "Primary")),
        h("div", { class: "faint" }, `${r.mime_type.toUpperCase()} · ${(r.size_bytes / 1024).toFixed(0)} KB · uploaded ${fmtDate(r.created_at)}`)),
      h("div", { class: "row" },
        !r.is_primary && h("button", { class: "btn-sm", onclick: async () => { await api.post(`/api/resumes/${r.id}/primary`); render(root); } }, "Make primary"),
        h("button", { class: "btn-sm", onclick: () => api.file(`/api/resumes/${r.id}/file`, r.original_filename) }, "Download"),
        h("button", { class: "btn-sm btn-danger", onclick: async () => {
          if (await confirmDialog("Delete resume?", "The file is removed from storage. Your profile is not changed.", "Delete", true)) { await api.del(`/api/resumes/${r.id}`); render(root); }
        } }, "Delete"))),
    (p.warnings || []).map((w) => h("div", { class: "alert warn", style: { marginBottom: "8px" } }, w)),
    h("div", { class: "grid cols-2" },
      h("div", {}, h("h3", {}, "Extracted details"),
        kv("Name", p.full_name), kv("Email", p.email), kv("Phone", p.phone), kv("Headline", p.headline),
        kv("Sections found", (p.sections_found || []).join(", ")),
        h("h3", { style: { marginTop: "10px" } }, `Skills (${(p.skills || []).length})`),
        h("div", {}, (p.skills || []).slice(0, 40).map((s) => h("span", { class: "chip" }, s)))),
      h("div", {}, h("h3", {}, `Experience (${(p.experience || []).length} roles)`),
        (p.experience || []).map((e) => h("div", { style: { marginBottom: "8px" } },
          h("div", { style: { fontWeight: 600 } }, [e.title, e.company].filter(Boolean).join(" — ") || "(untitled role)"),
          h("div", { class: "faint" }, [e.start, e.end].filter(Boolean).join(" – "), ` · ${e.bullets.length} bullet(s)`))),
        h("h3", { style: { marginTop: "10px" } }, `Education (${(p.education || []).length})`),
        (p.education || []).map((e) => h("div", { class: "small" }, [e.degree, e.institution].filter(Boolean).join(", "))))),
    h("hr"),
    h("div", { class: "row between" }, h("span", { class: "small muted" }, "Parsing is automatic — always review the result in your profile before relying on it."),
      h("div", { class: "row" }, fill, over)));
}

const kv = (k, v) => h("div", { class: "small" }, h("span", { class: "muted" }, `${k}: `), v || "—");
