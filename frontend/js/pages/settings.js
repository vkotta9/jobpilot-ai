import { api } from "../api.js";
import { h, mount, loading, field, busy, toast, modal, fmtDate } from "../ui.js";
import { setPaused, route } from "../app.js";

export async function render(root) {
  mount(root, loading());
  const [st, health, log] = await Promise.all([api.get("/api/settings"), api.get("/api/health"), api.get("/api/audit-log")]);
  const wf = Object.assign({ discovery: true, follow_up_tasks: true, digest: true }, st.workflows || {});
  const interval = h("input", { type: "number", min: 1, max: 720, value: st.search_interval_hours });
  const threshold = h("input", { type: "number", min: 0, max: 100, value: st.high_match_threshold });
  const fdays = h("input", { type: "number", min: 1, max: 90, value: st.follow_up_days });
  const wfBoxes = Object.entries({ discovery: "Scheduled job searches", follow_up_tasks: "Automatic follow-up reminders", digest: "Weekly summary on dashboard" })
    .map(([k, l]) => { const cb = h("input", { type: "checkbox", checked: wf[k] }); cb.dataset.k = k; return h("label", { class: "check" }, cb, l); });

  const save = h("button", { class: "btn-primary" }, "Save settings");
  save.addEventListener("click", busy(save, async () => {
    await api.put("/api/settings", { search_interval_hours: Number(interval.value), high_match_threshold: Number(threshold.value), follow_up_days: Number(fdays.value),
      workflows: Object.fromEntries(wfBoxes.map((l) => { const i = l.querySelector("input"); return [i.dataset.k, i.checked]; })) });
    toast("Settings saved.");
  }));

  const pauseBtn = h("button", { class: st.automation_paused ? "btn-primary" : "btn-danger" }, st.automation_paused ? "▶ Resume all automation" : "❚❚ Pause all automation now");
  pauseBtn.addEventListener("click", busy(pauseBtn, async () => {
    const r = await api.post(st.automation_paused ? "/api/automation/resume" : "/api/automation/pause");
    setPaused(r.automation_paused);
    route();
  }));

  const delAccount = async () => {
    const email = h("input", { type: "email", placeholder: "your account email" });
    const r = await modal("Delete account and all data", h("div", {},
      h("p", {}, "This permanently deletes your profile, resumes (including stored files), jobs, applications, contacts and history. Export your data first if you want a copy."),
      field("Type your email to confirm", email)),
      [{ label: "Cancel", value: () => null }, { label: "Delete everything", danger: true, value: () => email.value || false }]);
    if (!r) return;
    await api.del(`/api/account?confirm_email=${encodeURIComponent(r)}`);
    location.hash = "#/login";
    location.reload();
  };

  const integ = [
    ["Greenhouse Job Board API", "Real · public · no credentials", "good", "https://developers.greenhouse.io/job-board.html"],
    ["Lever Postings API", "Real · public · no credentials", "good", "https://github.com/lever/postings-api"],
    ["Simulated demo source", health.simulated_sources_allowed ? "Enabled (labelled SIMULATED)" : "Disabled", health.simulated_sources_allowed ? "sim" : "", null],
    ["OpenAI (resume/letter polishing)", health.llm.configured ? `Configured · ${health.llm.model}` : "Not configured — rule-based generation in use", health.llm.configured ? "good" : "warn", "https://platform.openai.com/api-keys"],
    ["Automatic application submission", "Not available — employers' ATS APIs need employer keys; you submit manually", "", null],
    ["LinkedIn messaging", "Not integrated — drafts are copied and sent by you", "", null],
  ];

  mount(root,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Settings & privacy"), h("div", { class: "sub" }, "Control what runs automatically and what happens to your data."))),
    h("div", { class: "grid cols-2" },
      h("div", { class: "stack" },
        h("div", { class: "card" }, h("h2", {}, "Kill switch"),
          h("p", { class: "small muted" }, "Immediately stops all background work (scheduled searches). JobPilot never submits applications or sends messages on its own in any case."),
          h("div", { class: "row between" }, h("span", { class: st.automation_paused ? "pill-paused" : "pill-live" }, st.automation_paused ? "Paused" : "Running"), pauseBtn)),
        h("div", { class: "card" }, h("h2", {}, "Automation"),
          h("div", { class: "stack" }, field("Search every (hours)", interval), field("High-match threshold (0–100)", threshold),
            field("Follow up after (days)", fdays, "Reminder created this many days after you submit"), h("div", { class: "stack" }, wfBoxes), h("div", {}, save)),
          h("p", { class: "faint", style: { marginTop: "8px" } }, `Last scheduled search: ${st.last_auto_search_at ? fmtDate(st.last_auto_search_at, true) : "never"}`)),
        h("div", { class: "card" }, h("h2", {}, "Your data"),
          h("p", { class: "small muted" }, "Everything is stored in your own database. Uploaded files are private to your account."),
          h("div", { class: "row" }, h("button", { onclick: () => api.file("/api/account/export", "jobpilot_export.json") }, "⬇ Export all data (JSON)"),
            h("button", { onclick: () => api.file("/api/applications/export.csv", "jobpilot_tracker.csv") }, "⬇ Tracker CSV"),
            h("button", { class: "btn-danger", onclick: delAccount }, "Delete account")))),
      h("div", { class: "stack" },
        h("div", { class: "card" }, h("h2", {}, "Integrations"),
          integ.map(([n, d, k, url]) => h("div", { class: "list-item" }, h("div", {}, h("strong", { class: "small" }, n), url && [" ", h("a", { class: "small", href: url, target: "_blank", rel: "noopener noreferrer" }, "docs ↗")]),
            h("span", { class: `badge ${k}`, style: { whiteSpace: "normal", textAlign: "right" } }, d))),
          h("p", { class: "faint", style: { marginTop: "8px" } }, `Server: database ${health.database_backend} (${health.database}), scheduler ${health.scheduler_enabled ? "on" : "off"}.`)),
        h("div", { class: "card" }, h("h2", {}, "Audit log"), h("p", { class: "small muted" }, "Important actions on your account (latest 200)."),
          h("div", { style: { maxHeight: "380px", overflow: "auto" } }, log.map((e) => h("div", { class: "list-item small" },
            h("span", { class: "mono" }, e.action), h("span", { class: "faint" }, fmtDate(e.created_at, true)))))))));
}
