import { api } from "../api.js";
import { h, mount, loading, empty, field, busy, toast, fmtDate, confirmDialog, modal } from "../ui.js";

export async function render(root) {
  mount(root, loading());
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const jobId = params.get("job");
  const [apps, contacts] = await Promise.all([api.get("/api/applications"), api.get("/api/contacts" + (jobId ? `?job_id=${jobId}` : ""))]);
  const plan = jobId ? await api.get(`/api/jobs/${jobId}/research-plan`) : null;

  const jobSel = h("select", { "aria-label": "Choose job", onchange: () => (location.hash = jobSel.value ? `#/networking?job=${jobSel.value}` : "#/networking") },
    h("option", { value: "" }, "All contacts — pick a job for research"),
    apps.map((a) => h("option", { value: a.job.id, selected: String(a.job.id) === jobId }, `${a.job.title} · ${a.job.company}`)));

  mount(root,
    h("div", { class: "page-head" },
      h("div", {}, h("h1", {}, "Networking"), h("div", { class: "sub" }, "Find the right people yourself with targeted searches, record who you verified, and send approved, personal messages.")),
      h("div", { class: "row" }, jobSel, h("button", { class: "btn-primary", onclick: () => addContact(jobId, root) }, "+ Add contact"))),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        contacts.length ? contacts.map((c) => contactCard(c, root))
          : h("div", { class: "card" }, empty("☍", "No contacts yet", "Run the searches on the right, then add people you find with their profile URL."))),
      h("div", { class: "stack" },
        plan ? [
          plan.from_posting.length ? h("div", { class: "card tight" },
            h("h3", {}, "Named in this job posting ", h("span", { class: "badge good" }, "published by the company")),
            h("p", { class: "small muted" }, "The company listed these for applicants — the best first people to contact."),
            plan.from_posting.map((pc) => h("div", { style: { margin: "8px 0", paddingTop: "8px", borderTop: "1px solid var(--border)" } },
              h("strong", {}, pc.name || pc.email), pc.name && pc.email ? h("span", { class: "small" }, " · ", pc.email) : null,
              h("div", { class: "small muted" }, pc.role), h("div", { class: "faint small" }, "“…", pc.snippet, "…”"),
              (() => { const b = h("button", { class: "btn-sm", style: { marginTop: "4px" } }, "Add as contact");
                b.addEventListener("click", busy(b, async () => {
                  await api.post("/api/contacts", { job_id: Number(jobId), name: pc.name || pc.email.split("@")[0], role: pc.role,
                    company: "", email: pc.email, source_url: plan.job_url, verified: !!plan.job_url,
                    contact_type: /hiring manager/i.test(pc.role) ? "hiring_manager" : /recruit|talent/i.test(pc.role) ? "recruiter" : "other",
                    relevance: "Named in the job posting." }).then(() => render(root)).catch(() => {});
                })); return b; })()))) : null,
          h("div", { class: "alert" }, plan.note),
          plan.plan.map((p) => h("div", { class: "card tight" },
            h("h3", {}, p.label, " ", h("span", { class: "badge" }, "suggested search")),
            h("p", { class: "small muted" }, p.why),
            p.queries.map((q) => h("div", { style: { margin: "6px 0" } }, h("div", { class: "mono" }, q.query),
              h("div", { class: "row small" },
                h("a", { href: q.linkedin_search_url, target: "_blank", rel: "noopener noreferrer" }, "LinkedIn search ↗"),
                h("a", { href: q.web_search_url, target: "_blank", rel: "noopener noreferrer" }, "Web search ↗")))))),
          h("div", { class: "card tight" }, h("h3", {}, "Recommended sequence"), h("ol", { class: "small", style: { paddingLeft: "18px", margin: 0 } }, plan.sequence.map((s) => h("li", {}, s)))),
        ] : h("div", { class: "card" }, h("p", { class: "muted" }, "Pick a tracked job above to get targeted search queries for recruiters, hiring managers and team members.")))));
}

function contactCard(c, root) {
  const hook = h("input", { placeholder: "Optional: something personal — their post, team project, shared school…", "aria-label": "Personal hook" });
  const gen = (channel, kind) => {
    const b = h("button", { class: "btn-sm" }, { connection: "LinkedIn note", outreach: channel === "email" ? "Email" : "LinkedIn message", follow_up: channel === "email" ? "Follow-up email" : "Follow-up message" }[kind]);
    b.addEventListener("click", busy(b, async () => {
      const m = await api.post(`/api/contacts/${c.id}/outreach`, { channel, kind, hook: hook.value });
      toast(m.generator === "ai" ? "Draft written for this person — read it, edit, then approve." : (m.note || "Template draft added — personalise it, then approve."));
      render(root);
    }));
    return b;
  };
  return h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("div", {}, h("h2", {}, c.name, " ", c.verified ? h("span", { class: "badge good" }, "verified") : h("span", { class: "badge warn" }, "unverified")),
        h("div", { class: "small muted" }, [c.role, c.company].filter(Boolean).join(" · "), " · ", c.contact_type.replace(/_/g, " ")),
        c.source_url && h("a", { class: "small", href: c.source_url, target: "_blank", rel: "noopener noreferrer" }, "source ↗"),
        c.last_contacted_at && h("div", { class: "faint" }, `Last contacted ${fmtDate(c.last_contacted_at)}`)),
      h("button", { class: "btn-sm btn-danger", onclick: async () => { if (await confirmDialog("Remove contact?", `Delete ${c.name} and their drafts?`, "Remove", true)) { await api.del(`/api/contacts/${c.id}`); render(root); } } }, "Remove")),
    c.relevance && h("p", { class: "small" }, h("strong", {}, "Why: "), c.relevance),
    c.email ? h("div", { class: "small" }, "✉ ", c.email) : null,
    hook,
    h("div", { class: "row small", style: { marginTop: "6px" } }, "Draft: ", gen("linkedin", "connection"), gen("linkedin", "outreach"), gen("email", "outreach"),
      gen("linkedin", "follow_up"), gen("email", "follow_up")),
    c.messages.map((m) => messageBox(m, c, root)));
}

function sendButtons(m, c, subj, body) {
  if (m.status !== "approved") return [];
  const out = [];
  if (m.channel === "email") {
    if (c.email) {
      const enc = encodeURIComponent;
      out.push(h("a", { class: "btn btn-sm btn-primary", target: "_blank", rel: "noopener noreferrer",
        href: `https://mail.google.com/mail/?view=cm&fs=1&to=${enc(c.email)}&su=${enc(subj.value)}&body=${enc(body.value)}` }, "Open in Gmail ↗"));
      out.push(h("a", { class: "btn btn-sm", href: `mailto:${enc(c.email)}?subject=${enc(subj.value)}&body=${enc(body.value)}` }, "Open in mail app"));
    } else out.push(h("span", { class: "faint small" }, "Add their email to the contact (only one they published) to open it in your mail."));
  } else if (/linkedin\.com\/in\//.test(c.source_url || "")) {
    out.push(h("a", { class: "btn btn-sm btn-primary", href: c.source_url, target: "_blank", rel: "noopener noreferrer",
      onclick: () => navigator.clipboard.writeText(body.value).then(() => toast("Message copied — paste it on their LinkedIn profile.")) }, "Copy & open LinkedIn ↗"));
  }
  return out;
}

function messageBox(m, c, root) {
  const subj = h("input", { value: m.subject, "aria-label": "Subject" });
  const body = h("textarea", { rows: m.kind === "connection" ? 3 : 7, value: m.body, disabled: m.status === "sent", "aria-label": "Message" });
  const count = h("span", { class: "faint" }, `${m.body.length}${m.kind === "connection" ? "/300" : ""} chars`);
  body.addEventListener("input", () => (count.textContent = `${body.value.length}${m.kind === "connection" ? "/300" : ""} chars`));
  const kind = { draft: "warn", approved: "good", sent: "info" }[m.status];
  return h("div", { style: { borderTop: "1px solid var(--border)", marginTop: "12px", paddingTop: "12px" } },
    h("div", { class: "row between" }, h("strong", { class: "small" }, `${m.channel} · ${m.kind.replace("_", " ")}`),
      h("span", { class: `badge ${kind}` }, m.status === "sent" ? `sent ${fmtDate(m.sent_at)}` : m.status)),
    m.channel === "email" && m.status !== "sent" && field("Subject", subj),
    body, count,
    m.status !== "sent" && h("div", { class: "row", style: { marginTop: "6px", justifyContent: "flex-end" } },
      h("button", { class: "btn-sm btn-ghost", onclick: async () => { await api.del(`/api/outreach/${m.id}`); render(root); } }, "Delete"),
      h("button", { class: "btn-sm", onclick: async () => { await api.put(`/api/outreach/${m.id}`, { body: body.value, subject: subj.value }); toast("Saved as draft."); render(root); } }, "Save"),
      m.status === "draft" && h("button", { class: "btn-sm btn-primary", onclick: async () => {
        if (body.value !== m.body || subj.value !== m.subject) await api.put(`/api/outreach/${m.id}`, { body: body.value, subject: subj.value });
        await api.post(`/api/outreach/${m.id}/approve`, { confirm: true }); render(root);
      } }, "Approve"),
      ...sendButtons(m, c, subj, body),
      m.status === "approved" && h("button", { class: "btn-sm", onclick: async () => { await navigator.clipboard.writeText((m.channel === "email" && subj.value ? "Subject: " + subj.value + "\n\n" : "") + body.value); toast("Copied. Paste it into LinkedIn or your email client."); } }, "Copy"),
      m.status === "approved" && h("button", { class: "btn-sm btn-primary", onclick: async () => {
        if (await confirmDialog("Mark as sent?", "Only do this after you've actually sent it yourself. JobPilot never sends messages for you.", "I sent it")) { await api.post(`/api/outreach/${m.id}/mark-sent`); toast("Recorded. A reply check was added to your follow-ups."); render(root); }
      } }, "Mark as sent")));
}

async function addContact(jobId, root) {
  const f = { name: h("input"), role: h("input"), company: h("input"), source_url: h("input", { type: "url", placeholder: "https://www.linkedin.com/in/…" }),
    contact_type: h("select", {}, ["recruiter", "hiring_manager", "team_member", "alumni", "department_leader", "other"].map((v) => h("option", { value: v }, v.replace(/_/g, " ")))),
    relevance: h("textarea", { rows: 2, placeholder: "Why is this person relevant to the role?" }), email: h("input", { type: "email", placeholder: "Only if publicly provided by them" }),
    verified: h("input", { type: "checkbox" }) };
  const r = await modal("Add a contact", h("div", { class: "form-grid" },
    field("Name", f.name), field("Current role", f.role), field("Company", f.company, jobId ? "Defaults to the job's company" : null), field("Type", f.contact_type),
    h("div", { class: "full" }, field("Source URL", f.source_url, "Where you confirmed their name and role")),
    h("div", { class: "full" }, field("Relevance", f.relevance)), h("div", { class: "full" }, field("Email (optional)", f.email)),
    h("label", { class: "check full" }, f.verified, "I verified this person's current role at the source URL")),
    [{ label: "Cancel", value: () => null }, { label: "Add contact", primary: true, value: async () => {
      if (!f.name.value) { toast("Name is required.", "bad"); return false; }
      return api.post("/api/contacts", { job_id: jobId ? Number(jobId) : null, name: f.name.value, role: f.role.value, company: f.company.value,
        source_url: f.source_url.value, contact_type: f.contact_type.value, relevance: f.relevance.value, email: f.email.value, verified: f.verified.checked })
        .catch(() => false);
    } }]);
  if (r) render(root);
}
