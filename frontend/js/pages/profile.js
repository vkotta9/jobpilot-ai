import { api } from "../api.js";
import { h, mount, loading, field, list, toast, busy } from "../ui.js";

const SENIORITY = ["intern", "junior", "mid", "senior", "staff", "principal", "lead", "manager", "director"];
const WORKPLACE = ["remote", "hybrid", "onsite"];

export async function render(root) {
  mount(root, loading());
  const p = await api.get("/api/profile");
  const prefs = p.preferences || {};
  const auth = p.work_authorization || {};
  const w = Object.assign({ skills: 40, title: 20, seniority: 15, location: 15, compensation: 10 }, p.match_weights || {});

  const inp = (v, attrs = {}) => h("input", { value: v ?? "", ...attrs });
  const f = {
    full_name: inp(p.full_name, { autocomplete: "name" }), email: inp(p.email, { type: "email" }), phone: inp(p.phone),
    location: inp(p.location), headline: inp(p.headline, { placeholder: "e.g. Backend engineer focused on data platforms" }),
    summary: h("textarea", { rows: 4, value: p.summary }), links: h("textarea", { rows: 2, value: (p.links || []).join("\n") }),
    skills: h("textarea", { rows: 3, value: (p.skills || []).join(", ") }),
    certifications: h("textarea", { rows: 2, value: (p.certifications || []).join("\n") }),
    titles: inp((prefs.target_titles || []).join(", "), { placeholder: "Backend Engineer, Platform Engineer" }),
    industries: inp((prefs.industries || []).join(", ")), companies: inp((prefs.preferred_companies || []).join(", ")),
    locations: inp((prefs.locations || []).join(", "), { placeholder: "New York, Remote US" }),
    salary_min: inp(prefs.salary_min ?? "", { type: "number", min: 0, step: 1000 }),
    salary_max: inp(prefs.salary_max ?? "", { type: "number", min: 0, step: 1000 }),
    currency: inp(prefs.salary_currency || "USD", { maxlength: 5 }),
    emp: inp((prefs.employment_types || []).join(", "), { placeholder: "Full-time, Contract" }),
    exclude: inp((prefs.exclude_keywords || []).join(", "), { placeholder: "e.g. clearance, unpaid" }),
    countries: inp((auth.authorized_countries || []).join(", "), { placeholder: "United States" }),
    sponsor: h("select", {}, [["", "Not specified"], ["no", "No, I don't need sponsorship"], ["yes", "Yes, I need sponsorship"]].map(([v, l]) =>
      h("option", { value: v, selected: (auth.requires_sponsorship === true && v === "yes") || (auth.requires_sponsorship === false && v === "no") || (auth.requires_sponsorship == null && v === "") }, l))),
    confirm: h("input", { type: "checkbox", id: "confirm" }),
  };
  const sen = SENIORITY.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", value: s, checked: (prefs.seniority || []).includes(s) }), s));
  const wp = WORKPLACE.map((s) => h("label", { class: "check" }, h("input", { type: "checkbox", value: s, checked: (prefs.workplace || []).includes(s) }), s));
  const weights = Object.keys(w).map((k) => {
    const out = h("strong", {}, String(w[k]));
    const r = h("input", { type: "range", min: 0, max: 100, step: 5, value: w[k], "aria-label": `${k} weight`, oninput: () => (out.textContent = r.value) });
    r.dataset.key = k;
    return h("div", { class: "breakdown-row" }, h("span", { style: { textTransform: "capitalize" } }, k), r, out);
  });

  const exp = h("div", { class: "stack" });
  const addExp = (e = {}) => exp.appendChild(expCard(e));
  (p.experience || []).forEach(addExp);
  const edu = h("div", { class: "stack" });
  const addEdu = (e = {}) => edu.appendChild(eduCard(e));
  (p.education || []).forEach(addEdu);
  const projects = h("textarea", { rows: 3, value: (p.projects || []).map((x) => [x.name, x.description].filter(Boolean).join(" — ")).join("\n"),
    placeholder: "One per line: Name — description" });

  const save = h("button", { class: "btn-primary" }, "Save profile");
  const save2 = h("button", { class: "btn-primary" }, "Save profile");
  const doSave = async () => {
    const body = {
      full_name: f.full_name.value, email: f.email.value, phone: f.phone.value, location: f.location.value,
      headline: f.headline.value, summary: f.summary.value, links: list(f.links.value), skills: list(f.skills.value),
      certifications: list(f.certifications.value),
      projects: projects.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [n, ...d] = l.split(" — "); return { name: n, description: d.join(" — "), link: "" }; }),
      experience: [...exp.children].map(readExp).filter((e) => e.company || e.title),
      education: [...edu.children].map(readEdu).filter((e) => e.institution || e.degree),
      preferences: {
        target_titles: list(f.titles.value), industries: list(f.industries.value), preferred_companies: list(f.companies.value),
        seniority: sen.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value),
        workplace: wp.map((l) => l.querySelector("input")).filter((i) => i.checked).map((i) => i.value),
        locations: list(f.locations.value), salary_min: f.salary_min.value ? Number(f.salary_min.value) : null,
        salary_max: f.salary_max.value ? Number(f.salary_max.value) : null, salary_currency: f.currency.value || "USD",
        employment_types: list(f.emp.value), exclude_keywords: list(f.exclude.value),
      },
      work_authorization: { authorized_countries: list(f.countries.value), requires_sponsorship: f.sponsor.value === "" ? null : f.sponsor.value === "yes", notes: "" },
      match_weights: Object.fromEntries(weights.map((r) => { const i = r.querySelector("input"); return [i.dataset.key, Number(i.value)]; })),
      confirm: f.confirm.checked,
    };
    await api.put("/api/profile", body);
    toast("Profile saved. Match scores were recalculated.");
    render(root);
  };
  save.addEventListener("click", busy(save, doSave));
  save2.addEventListener("click", busy(save2, doSave));

  const section = (title, sub, ...kids) => h("div", { class: "card" }, h("h2", {}, title), sub && h("p", { class: "small muted" }, sub), ...kids);

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Profile & preferences"),
        h("div", { class: "sub" }, "This verified profile is the only source of facts for every resume, letter and answer JobPilot drafts.",
          p.confirmed_at ? ` Last confirmed ${new Date(p.confirmed_at).toLocaleDateString()}.` : " Not yet confirmed.")),
      h("div", { class: "row" }, h("a", { class: "btn", href: "#/resumes" }, "Import from resume"), save)),
    h("div", { class: "stack" },
      section("Basics", null, h("div", { class: "form-grid" },
        field("Full name", f.full_name), field("Email", f.email), field("Phone", f.phone), field("Location", f.location),
        h("div", { class: "full" }, field("Headline", f.headline)),
        h("div", { class: "full" }, field("Summary", f.summary)),
        h("div", { class: "full" }, field("Links", f.links, "One per line (LinkedIn, GitHub, portfolio)")))),
      section("Skills", "Comma-separated. Only list skills you can demonstrate — matching and tailoring rely on them.", f.skills),
      section("Experience", "Most recent first. Employers, titles and dates are locked in tailored resumes.",
        exp, h("button", { onclick: () => addExp({}) }, "+ Add role")),
      section("Education", null, edu, h("button", { onclick: () => addEdu({}) }, "+ Add education")),
      section("Certifications & projects", null, h("div", { class: "form-grid" },
        field("Certifications", f.certifications, "One per line"), field("Projects", projects))),
      section("Job preferences", "Used by discovery and the match score.", h("div", { class: "form-grid" },
        field("Target job titles", f.titles), field("Preferred locations", f.locations),
        field("Industries", f.industries), field("Preferred companies", f.companies),
        field("Minimum salary (annual)", f.salary_min), field("Maximum salary (annual)", f.salary_max),
        field("Currency", f.currency), field("Employment types", f.emp),
        h("div", { class: "full" }, h("label", {}, "Seniority", h("div", { class: "row" }, sen))),
        h("div", { class: "full" }, h("label", {}, "Workplace", h("div", { class: "row" }, wp))),
        h("div", { class: "full" }, field("Exclude jobs mentioning", f.exclude)))),
      section("Work authorization", "Used only to check eligibility statements in postings and to pre-fill matching screening questions. Never guessed.",
        h("div", { class: "form-grid" }, field("Authorized to work in", f.countries, "Comma-separated countries"), field("Visa sponsorship", f.sponsor))),
      section("Match score weights", "How much each factor counts toward the 0–100 match score. Weights are normalized.", weights),
      h("div", { class: "card row between" },
        h("label", { class: "check", for: "confirm" }, f.confirm, "I confirm this profile is accurate and may be used to generate my materials."),
        save2)));
}

function expCard(e) {
  const i = (k, ph) => h("input", { value: e[k] || "", placeholder: ph, "data-k": k });
  const bullets = h("textarea", { rows: 4, value: (e.bullets || []).join("\n"), "data-k": "bullets", placeholder: "One achievement per line" });
  const card = h("div", { class: "card tight" },
    h("div", { class: "form-grid" }, field("Title", i("title")), field("Company", i("company")), field("Start", i("start", "Jan 2021")),
      field("End", i("end", "Present")), h("div", { class: "full" }, field("Location", i("location"))),
      h("div", { class: "full" }, field("Achievements", bullets, "One per line. Keep real numbers; JobPilot never adds metrics."))),
    h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "8px" } }, h("button", { class: "btn-sm btn-danger", onclick: () => card.remove() }, "Remove role")));
  return card;
}
function readExp(card) {
  const o = {};
  card.querySelectorAll("[data-k]").forEach((el) => (o[el.dataset.k] = el.value.trim()));
  o.bullets = (o.bullets || "").split("\n").map((b) => b.replace(/^[•\-*]\s*/, "").trim()).filter(Boolean);
  return o;
}
function eduCard(e) {
  const i = (k, ph) => h("input", { value: e[k] || "", placeholder: ph || "", "data-k": k });
  const card = h("div", { class: "card tight" },
    h("div", { class: "form-grid" }, field("Institution", i("institution")), field("Degree", i("degree")), field("Field", i("field")),
      field("End / graduation", i("end", "2020"))),
    h("div", { class: "row", style: { justifyContent: "flex-end", marginTop: "8px" } }, h("button", { class: "btn-sm btn-danger", onclick: () => card.remove() }, "Remove")));
  return card;
}
function readEdu(card) {
  const o = { start: "", details: "" };
  card.querySelectorAll("[data-k]").forEach((el) => (o[el.dataset.k] = el.value.trim()));
  return o;
}
