// Role tracks: up to three resumes, each focused on one kind of role. Every job is scored against the track it
// belongs to (an ML posting against your ML resume), and tailoring / applying uses that track's resume.
import { api } from "../api.js";
import { h, mount, loading, empty, field, busy, toast, confirmDialog, scoreRing, list } from "../ui.js";

export async function render(root) {
  mount(root, loading());
  const [data, families] = await Promise.all([api.get("/api/tracks"), api.get("/api/roles")]);
  const { tracks, resumes } = data;
  const head = h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Role tracks"),
    h("div", { class: "sub" }, `Most companies shortlist focused candidates, so keep one resume per kind of role (up to ${data.max}). `,
      "JobPilot scores every job against the resume of its role — an ML posting against your ML resume, an SDE posting against your SDE one — ",
      "and tailors and applies with that resume.")));
  if (!resumes.length) {
    return mount(root, head, empty("▣", "Upload your resumes first", "Add one resume per kind of role you're targeting (e.g. one for SDE roles, one for ML roles).",
      h("a", { class: "btn btn-primary", href: "#/resumes" }, "Go to Resume library")));
  }
  const jobLists = await Promise.all(tracks.map((t) => api.get(`/api/tracks/${t.id}/jobs?limit=5`)));
  mount(root, head,
    resumesCard(resumes, tracks, data.max, root),
    tracks.length ? h("div", { class: "grid", style: { gridTemplateColumns: `repeat(${Math.min(tracks.length, 3)}, minmax(0, 1fr))`, gap: "16px", marginTop: "16px" } },
      tracks.map((t, i) => trackCard(t, resumes, jobLists[i], root))) : null,
    data.unassigned_jobs && tracks.length ? h("p", { class: "small muted", style: { marginTop: "10px" } },
      `${data.unassigned_jobs} job${data.unassigned_jobs === 1 ? " hasn't" : "s haven't"} been scored against your tracks yet — they will be on the next search.`) : null,
    tracks.length < data.max ? addCard(families, resumes, tracks, root) : null);
}

function strengthChip(s) {
  const cls = s.strength >= 60 ? "good" : s.strength >= 35 ? "warn" : "";
  return h("span", { class: `badge ${cls}`, title: `Evidence: ${s.evidence.join(", ")}` }, `${s.name} · ${s.strength}%`);
}

function resumesCard(resumes, tracks, max, root) {
  return h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Your resumes and the roles they fit"), h("a", { href: "#/resumes", class: "small" }, "Manage resumes")),
    h("p", { class: "small muted" }, "Read from each resume's job titles and skills. Hover a role to see why."),
    h("div", { class: "stack", style: { gap: "10px" } }, resumes.map((r) => {
      const top = r.suggested_roles[0];
      const canAdd = top && !r.used_by && tracks.length < max && !tracks.some((t) => t.family === top.key);
      const b = canAdd ? h("button", { class: "btn-sm" }, `Create “${top.name}” track`) : null;
      if (b) b.addEventListener("click", busy(b, async () => {
        await api.post("/api/tracks", { family: top.key, resume_id: r.id });
        toast(`Track created. Re-scoring your jobs against it…`);
        render(root);
      }));
      return h("div", { class: "row between", style: { alignItems: "center", gap: "10px" } },
        h("div", {}, h("strong", {}, r.filename), r.is_primary && h("span", { class: "badge", style: { marginLeft: "6px" } }, "primary"),
          r.used_by && h("span", { class: "badge good", style: { marginLeft: "6px" } }, `used by ${r.used_by}`),
          h("div", { class: "row", style: { gap: "6px", marginTop: "4px" } },
            r.suggested_roles.length ? r.suggested_roles.map(strengthChip) : h("span", { class: "faint small" }, "No clear role focus found in this resume."))),
        b);
    })));
}

function resumeSelect(resumes, current) {
  return h("select", { "aria-label": "Resume for this track" },
    h("option", { value: "" }, "Primary resume"),
    resumes.map((r) => h("option", { value: r.id, selected: r.id === current }, r.filename)));
}

const MAX_TITLES = 30;
function titleCounter(ta) {
  const c = h("span", { class: "small muted" });
  const upd = () => { const n = list(ta.value).length; c.textContent = `${n}/${MAX_TITLES} titles`; c.style.color = n > MAX_TITLES ? "var(--bad, #c0392b)" : ""; };
  ta.addEventListener("input", upd); upd();
  return { el: c, upd, tooMany: () => list(ta.value).length > MAX_TITLES };
}

function trackCard(t, resumes, jobs, root) {
  const res = resumeSelect(resumes, t.resume?.id);
  const titles = h("textarea", { rows: 3, "aria-label": "Job titles for this track" }, t.target_titles.join(", "));
  const count = titleCounter(titles);
  const addTitle = (x) => { const cur = list(titles.value); if (!cur.includes(x)) titles.value = [...cur, x].join(", "); count.upd(); };
  const save = h("button", { class: "btn-sm btn-primary" }, "Save");
  save.addEventListener("click", busy(save, async () => {
    if (count.tooMany()) return toast(`A track can have up to ${MAX_TITLES} job titles.`, "bad");
    await api.put(`/api/tracks/${t.id}`, { family: t.family, name: t.name, target_titles: list(titles.value), resume_id: res.value ? Number(res.value) : null });
    toast("Saved. Re-scoring your jobs…");
    render(root);
  }));
  const del = h("button", { class: "btn-sm btn-danger" }, "Remove");
  del.addEventListener("click", async () => {
    if (await confirmDialog(`Remove “${t.name}”?`, "Its jobs are re-assigned to your other tracks. Your resume file is kept.", "Remove", true)) {
      await api.del(`/api/tracks/${t.id}`);
      render(root);
    }
  });
  const seeAll = h("a", { href: "#/discover", onclick: () => { try { sessionStorage.setItem("jp_track", String(t.id)); } catch { /* */ } } }, `All ${t.stats.jobs} in Discover →`);
  return h("div", { class: "card", style: { marginTop: 0 } },
    h("div", { class: "card-head" }, h("h2", {}, t.name), t.family_name !== t.name ? h("span", { class: "faint small" }, t.family_name) : null),
    h("div", { class: "row", style: { gap: "14px", margin: "4px 0 10px" } },
      stat(t.stats.jobs, "jobs"), stat(t.stats.strong, "≥ 70 ATS"), stat(t.stats.average ?? "–", "avg ATS")),
    field("Resume", res),
    field("Job titles", titles, `Up to ${MAX_TITLES}, comma-separated. JobPilot searches for these and keeps matching roles from the companies you follow.`),
    count.el,
    t.suggested_titles.length ? h("div", { class: "row", style: { gap: "4px", margin: "-4px 0 8px" } },
      h("span", { class: "faint small" }, "Related:"),
      t.suggested_titles.map((x) => h("button", { class: "btn-ghost btn-sm", onclick: () => addTitle(x), title: "Add this title" }, "+ " + x))) : null,
    h("div", { class: "row", style: { justifyContent: "flex-end", gap: "6px" } }, del, save),
    h("hr"),
    h("h3", {}, "Best matches for this resume"),
    jobs.items.length ? h("div", { class: "stack", style: { gap: "6px" } }, jobs.items.map((j) =>
      h("a", { href: `#/jobs/${j.id}`, class: "row", style: { gap: "10px", alignItems: "center", textDecoration: "none", color: "inherit" } },
        scoreRing(j.match ? j.match.score : null),
        h("div", {}, h("div", { style: { fontWeight: 600 } }, j.title), h("div", { class: "faint small" }, j.company + (j.location ? " · " + j.location : "")))))) :
      h("p", { class: "small muted" }, "No jobs for this track yet. Run a search on Discover — it now looks for this track's titles too."),
    jobs.total > jobs.items.length ? h("div", { class: "small", style: { marginTop: "8px" } }, seeAll) : null);
}

const stat = (v, label) => h("div", {}, h("div", { style: { fontSize: "20px", fontWeight: 700 } }, String(v)), h("div", { class: "faint small" }, label));

function addCard(families, resumes, tracks, root) {
  const used = new Set(tracks.map((t) => t.family));
  const suggested = new Map();
  resumes.forEach((r) => r.suggested_roles.forEach((s) => { if (s.strength >= 35 && !suggested.has(s.key)) suggested.set(s.key, r.filename); }));
  const fam = h("select", { "aria-label": "Role" },
    families.filter((f) => !used.has(f.key)).map((f) => h("option", { value: f.key }, f.name + (suggested.has(f.key) ? `  ★ fits ${suggested.get(f.key)}` : ""))),
    h("option", { value: "custom" }, "Something else (custom)…"));
  const best = [...suggested.keys()].find((k) => !used.has(k));
  if (best) fam.value = best;
  const name = h("input", { placeholder: "Track name (optional)" });
  const res = resumeSelect(resumes, resumes.find((r) => r.suggested_roles[0]?.key === fam.value && !r.used_by)?.id);
  const titles = h("textarea", { rows: 3, placeholder: "Job titles, comma-separated (up to 30)" });
  const count = titleCounter(titles);
  const fill = () => {
    const f = families.find((x) => x.key === fam.value);
    titles.value = f ? f.titles.slice(0, 4).join(", ") : "";
    count.upd();
    name.placeholder = f ? `Track name (default: ${f.name})` : "Track name, e.g. Solutions Architect";
    const r = resumes.find((x) => x.suggested_roles[0]?.key === fam.value && !x.used_by);
    if (r) res.value = String(r.id);
  };
  fam.addEventListener("change", fill);
  fill();
  const add = h("button", { class: "btn-primary" }, "Add track");
  add.addEventListener("click", busy(add, async () => {
    if (fam.value === "custom" && !name.value.trim()) return toast("Give your custom track a name.", "bad");
    if (count.tooMany()) return toast(`A track can have up to ${MAX_TITLES} job titles.`, "bad");
    await api.post("/api/tracks", { family: fam.value, name: name.value.trim(), target_titles: list(titles.value), resume_id: res.value ? Number(res.value) : null });
    toast("Track added. Re-scoring your jobs against it…");
    render(root);
  }));
  return h("div", { class: "card", style: { marginTop: "16px" } },
    h("h2", {}, tracks.length ? "Add another track" : "Create your first track"),
    h("div", { class: "form-grid" }, field("Role", fam), field("Resume", res), field("Name", name),
      h("div", { class: "full" }, field("Job titles", titles, "Pre-filled with the usual titles for this role; edit freely — up to 30."), count.el)),
    h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "10px" } }, add));
}
