import { api } from "../api.js";
import { h, mount, loading, statusBadge, statusLabel, simBadge, fmtDate, busy, toast, modal, field, scoreRing } from "../ui.js";

export async function render(root, id) {
  mount(root, loading());
  const a = await api.get(`/api/applications/${id}`);
  const j = a.job;
  const reload = () => render(root, id);
  const submitted = !!a.submitted_at;

  const btn = (label, fn, cls = "") => { const b = h("button", { class: cls }, label); b.addEventListener("click", busy(b, fn)); return b; };

  // ---- package / approval
  const reqApproval = btn("Validate & request approval", async () => {
    const r = await api.post(`/api/applications/${id}/request-approval`);
    toast(r.ok ? "Package is complete — review and approve it." : "Package needs attention: " + r.problems.join(" "), r.ok ? "" : "bad");
    reload();
  }, "btn-primary");
  const approveBtn = btn("✓ Approve package", async () => {
    const ok = await modal("Approve application package", h("div", {},
      h("p", {}, `You're approving the materials for ${j.title} at ${j.company}.`),
      h("ul", { class: "small" }, h("li", {}, a.resume_used?.type === "tailored" ? `Tailored resume v${a.resume_used.version}` : `Your resume “${a.resume_used?.filename || ""}” (as uploaded)`), a.cover_letter && h("li", {}, `Cover letter v${a.cover_letter.version}`),
        h("li", {}, `${a.answers.length} screening answer(s)`)),
      h("p", { class: "small muted" }, "JobPilot will not submit anything for you. After approving, you submit on the official site and record it here.")),
      [{ label: "Cancel", value: () => null }, { label: "I reviewed everything — approve", primary: true, value: () => true }]);
    if (!ok) return;
    await api.post(`/api/applications/${id}/approve`, { confirm: true });
    toast("Package approved.");
    reload();
  }, "btn-primary");

  const confirmation = h("textarea", { rows: 3, placeholder: "Paste the confirmation message, email subject or application/reference number" });
  const record = btn("Record submission", async () => {
    const ok = await modal("Confirm submission", h("p", {}, "Confirm that you submitted this application yourself on the official site. Without a confirmation it will be recorded as self-reported (unverified)."),
      [{ label: "Cancel", value: () => null }, { label: "Yes, I submitted it", primary: true, value: () => true }]);
    if (!ok) return;
    const r = await api.post(`/api/applications/${id}/submission`, { confirm: true, method: "manual_user_submitted", confirmation_detail: confirmation.value });
    toast(r.verified ? "Submission recorded with confirmation." : "Submission recorded as self-reported.");
    reload();
  }, "btn-primary");

  // ---- questions
  const qbox = h("textarea", { rows: 3, placeholder: "Paste screening questions, one per line" });
  const addQ = btn("Draft answers", async () => {
    const qs = qbox.value.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!qs.length) return;
    await api.post(`/api/applications/${id}/questions`, { questions: qs });
    reload();
  });

  // ---- tracker fields
  const notes = h("textarea", { rows: 4, value: a.notes, "aria-label": "Notes" });
  const followUp = h("input", { type: "date", value: a.follow_up_at ? a.follow_up_at.slice(0, 10) : "", "aria-label": "Follow-up date" });
  const lastContact = h("input", { type: "date", value: a.last_contact_at ? a.last_contact_at.slice(0, 10) : "", "aria-label": "Last contact date" });
  const nextAction = h("input", { value: a.next_action, placeholder: a.next_best_action, "aria-label": "Next action" });
  const outcome = h("textarea", { rows: 2, value: a.outcome_detail, placeholder: "Offer / rejection details, feedback" });
  const saveTrack = btn("Save", async () => {
    await api.patch(`/api/applications/${id}`, { notes: notes.value, follow_up_at: followUp.value, last_contact_at: lastContact.value,
      next_action: nextAction.value, outcome_detail: outcome.value });
    toast("Saved.");
    reload();
  });
  const statusSel = h("select", { "aria-label": "Change status" }, h("option", { value: "" }, "Move to…"),
    a.allowed_transitions.map((s) => h("option", { value: s }, statusLabel(s))));
  statusSel.addEventListener("change", async () => {
    if (!statusSel.value) return;
    await api.post(`/api/applications/${id}/status`, { status: statusSel.value });
    reload();
  });

  const ivStage = h("input", { placeholder: "e.g. Recruiter screen" });
  const ivDate = h("input", { type: "datetime-local" });
  const addIv = btn("Add interview", async () => {
    if (!ivStage.value) return toast("Enter the interview stage.", "bad");
    await api.post(`/api/applications/${id}/interviews`, { stage: ivStage.value, scheduled_at: ivDate.value || null });
    reload();
  });

  const docLine = (d, label, kind) => h("div", { class: "list-item" },
    h("div", {}, h("strong", {}, label), d ? ` v${d.version}` : "", d && h("div", { class: "faint" }, d.generator)),
    d ? h("div", { class: "row" }, h("span", { class: `badge ${d.status === "approved" ? "good" : "warn"}` }, d.status), h("a", { class: "btn btn-sm", href: `#/documents/${d.id}` }, "Review"))
      : btn(`Generate`, async () => { const nd = await api.post(`/api/jobs/${j.id}/${kind === "resume" ? "resume/tailor" : "cover-letter"}`); location.hash = `#/documents/${nd.id}`; }, "btn-sm"));

  // resume: the approved tailored version if there is one, otherwise the user's own resume as uploaded
  const resumeLine = () => {
    const u = a.resume_used || {};
    const draft = a.resume && a.resume.status !== "approved";
    const tailorBtn = btn(a.resume ? "Tailor again" : "Tailor for this job (optional)", async () => {
      const nd = await api.post(`/api/jobs/${j.id}/resume/tailor`); location.hash = `#/documents/${nd.id}`; }, "btn-sm");
    if (u.type === "tailored") {
      return h("div", { class: "list-item" }, h("div", {}, h("strong", {}, "Resume"), ` · tailored v${u.version}`, h("div", { class: "faint" }, "Approved tailored version for this job")),
        h("div", { class: "row" }, h("span", { class: "badge good" }, "approved"), h("a", { class: "btn btn-sm", href: `#/documents/${u.doc_id}` }, "Review")));
    }
    if (u.type === "master") {
      return h("div", { class: "list-item" },
        h("div", {}, h("strong", {}, "Resume"), ` · ${u.filename}`,
          h("div", { class: "faint" }, draft ? `Using your resume as uploaded. A tailored draft (v${a.resume.version}) exists — approve it to use it instead.` : "Using your resume as uploaded — tailoring is optional.")),
        h("div", { class: "row" }, draft && h("a", { class: "btn btn-sm", href: `#/documents/${a.resume.id}` }, "Review draft"), tailorBtn));
    }
    return h("div", { class: "list-item" }, h("div", {}, h("strong", {}, "Resume"), h("div", { class: "faint" }, "Upload your resume in the Resume library.")),
      h("a", { class: "btn btn-sm", href: "#/resumes" }, "Resume library"));
  };
  const resumeDownload = () => {
    const u = a.resume_used || {};
    if (u.type === "tailored") return h("button", { onclick: () => api.file(`/api/documents/${u.doc_id}/download?format=pdf`, "resume.pdf") }, "⬇ Resume");
    if (u.type === "master") return h("button", { onclick: () => api.file(`/api/resumes/${u.resume_id}/file`, u.filename) }, "⬇ Resume");
    return null;
  };

  mount(root,
    h("div", { class: "faint", style: { marginBottom: "8px" } }, h("a", { href: "#/tracker" }, "← Tracker")),
    j.is_simulated && h("div", { class: "alert sim", style: { marginBottom: "12px" } }, "This is a SIMULATED demo listing. Its official URL points to example.com — there is nothing real to submit."),
    h("div", { class: "page-head" },
      h("div", { class: "row", style: { alignItems: "flex-start", gap: "14px" } }, scoreRing(a.match_score),
        h("div", {}, h("h1", {}, j.title), h("div", { class: "sub" }, h("a", { href: `#/jobs/${j.id}` }, j.company), j.location ? ` · ${j.location}` : ""),
          h("div", { class: "row", style: { marginTop: "6px" } }, statusBadge(a.status), j.is_simulated && simBadge(),
            submitted && h("span", { class: `badge ${a.submission_verified ? "good" : "warn"}` }, a.submission_verified ? "Submission verified" : "Self-reported submission")))),
      h("div", { class: "row" }, statusSel)),
    h("div", { class: "alert", style: { marginBottom: "16px" } }, h("strong", {}, "Next best action: "), a.next_best_action || "—"),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        h("div", { class: "card" },
          h("div", { class: "card-head" }, h("h2", {}, "1 · Application package"), a.approval_current ? h("span", { class: "badge good" }, `Approved ${fmtDate(a.approved_at)}`) : h("span", { class: "badge warn" }, "Not approved")),
          resumeLine(), docLine(a.cover_letter, "Cover letter (optional)", "cover_letter"),
          a.problems.length > 0 && !submitted && h("div", { class: "alert warn", style: { marginTop: "10px" } }, h("strong", {}, "Before approval:"), h("ul", {}, a.problems.map((p) => h("li", {}, p)))),
          !submitted && h("div", { class: "row", style: { marginTop: "12px" } },
            a.status !== "awaiting_approval" ? reqApproval : !a.approval_current ? approveBtn : h("span", { class: "badge good" }, "Ready to submit"))),
        h("div", { class: "card" }, h("h2", {}, "2 · Screening questions"),
          h("p", { class: "small muted" }, "JobPilot drafts from your verified profile and never guesses work authorization, salary, demographics or other personal answers."),
          a.answers.map((x) => answerRow(x, reload)),
          !submitted && [qbox, h("div", { class: "row", style: { marginTop: "8px" } }, addQ)]),
        h("div", { class: "card" }, h("h2", {}, "3 · Submit on the official site"),
          submitted ? h("div", {}, h("p", {}, `Submitted ${fmtDate(a.submitted_at, true)} (${a.submission_method.replace(/_/g, " ")}).`),
            a.confirmation_detail && h("div", { class: "desc small" }, a.confirmation_detail))
            : h("div", { class: "stack" },
              h("p", { class: "small muted" }, "JobPilot never submits applications automatically. Open the official form, attach your downloaded resume/letter, paste your approved answers, and submit it yourself."),
              h("div", { class: "row" },
                j.apply_url && h("a", { class: "btn", href: j.apply_url, target: "_blank", rel: "noopener noreferrer" }, "Open official application ↗"),
                resumeDownload(),
                a.cover_letter && h("button", { onclick: () => api.file(`/api/documents/${a.cover_letter.id}/download?format=pdf`, "cover_letter.pdf") }, "⬇ Letter PDF")),
              a.approval_current ? [field("Confirmation (recommended)", confirmation), h("div", {}, record)]
                : h("div", { class: "alert warn" }, "Approve the package first — submissions can only be recorded for an approved package."))),
        h("div", { class: "card" }, h("h2", {}, "History"),
          h("div", { class: "timeline" }, a.events.map((e) => h("div", { class: "ev" },
            h("div", { class: "small" }, h("strong", {}, e.kind === "status" ? `${statusLabel(e.from_status)} → ${statusLabel(e.to_status)}` : e.kind.replace(/_/g, " ")),
              e.verified && h("span", { class: "badge good", style: { marginLeft: "6px" } }, "verified")),
            h("div", { class: "faint" }, `${fmtDate(e.created_at, true)} · ${e.detail}`)))))),
      h("div", { class: "stack" },
        h("div", { class: "card" }, h("h2", {}, "Tracking"),
          h("div", { class: "stack" }, field("Next action", nextAction), field("Follow-up date", followUp), field("Last contact", lastContact),
            field("Notes", notes), field("Outcome / feedback", outcome), h("div", {}, saveTrack))),
        h("div", { class: "card" }, h("h2", {}, "Interviews"),
          a.interviews.map((i) => h("div", { class: "list-item small" }, h("strong", {}, i.stage), h("span", {}, fmtDate(i.scheduled_at, true)))),
          !a.interviews.length && h("p", { class: "muted small" }, "None yet."),
          h("div", { class: "stack", style: { marginTop: "8px" } }, ivStage, ivDate, h("div", {}, addIv))),
        h("div", { class: "card" }, h("h2", {}, "Tasks"),
          a.tasks.map((t) => h("div", { class: "list-item small" }, h("span", { style: { textDecoration: t.done ? "line-through" : "" } }, t.title), h("span", { class: "faint" }, fmtDate(t.due_at)))),
          !a.tasks.length && h("p", { class: "muted small" }, "Follow-ups are created automatically after you submit."),
          h("a", { class: "btn btn-sm", href: `#/networking?job=${j.id}`, style: { marginTop: "8px" } }, "Networking for this job →")))));
}

function answerRow(x, reload) {
  const ta = h("textarea", { rows: 2, value: x.answer, "aria-label": x.question });
  const reuse = h("input", { type: "checkbox", checked: x.reusable });
  const save = (approve) => async () => { await api.put(`/api/answers/${x.id}`, { answer: ta.value, approve, reusable: reuse.checked }); reload(); };
  const kind = { approved: "good", draft: "warn", needs_input: "bad" }[x.status];
  const approveBtn = h("button", { class: "btn-sm btn-primary", onclick: save(true), style: { display: x.status === "approved" ? "none" : "" } }, "Approve answer");
  ta.addEventListener("input", () => (approveBtn.style.display = ""));
  return h("div", { style: { padding: "10px 0", borderBottom: "1px solid var(--border)" } },
    h("div", { class: "row between" }, h("strong", { class: "small" }, x.question),
      h("span", { class: `badge ${kind}` }, x.status === "needs_input" ? "needs your input" : x.status)),
    h("div", { class: "faint", style: { margin: "2px 0 6px" } }, `${x.category.replace(/_/g, " ")} · ${x.source}`),
    ta,
    h("div", { class: "row between", style: { marginTop: "6px" } },
      h("label", { class: "check small" }, reuse, "Save for reuse"),
      h("div", { class: "row" },
        h("button", { class: "btn-sm btn-ghost", onclick: async () => { await api.del(`/api/answers/${x.id}`); reload(); } }, "Remove"),
        h("button", { class: "btn-sm", onclick: save(false) }, "Save draft"),
        approveBtn)));
}
