import { api } from "../api.js";
import { h, mount, loading, field, busy, toast, modal, fmtDate, confirmDialog } from "../ui.js";
import { setPaused, route } from "../app.js";

function connectionsCard(c, root) {
  const test = (provider) => async (e) => {
    const b = e.currentTarget; b.disabled = true;
    try { const r = await api.post(`/api/integrations/${provider}/test`); toast(r.message); } catch {} finally { b.disabled = false; }
  };
  const remove = (provider) => async () => { if (await confirmDialog("Remove this connection?", "The saved key will be deleted.", "Remove", true)) { await api.del(`/api/integrations/${provider}`); render(root); } };

  // AI
  const prov = h("select", { "aria-label": "AI provider" },
    [["gemini", "Google Gemini — free plan available"], ["openai", "OpenAI — paid (a few cents per resume)"], ["custom", "Other OpenAI-compatible"]]
      .map(([v, l]) => h("option", { value: v, selected: (c.ai.provider || "gemini") === v }, l)));
  const key = h("input", { type: "password", autocomplete: "off", placeholder: c.ai.key_hint ? `saved ${c.ai.key_hint} — leave blank to keep` : "Paste API key" });
  const model = h("input", { placeholder: "default", value: c.ai.source === "app" ? (c.ai.model || "") : "" });
  const base = h("input", { placeholder: "https://… (only for Other)" });
  const help = h("div", { class: "faint" });
  const setHelp = () => {
    const v = prov.value;
    help.replaceChildren(v === "gemini" ? h("span", {}, "Get a free key at ", h("a", { href: "https://aistudio.google.com/apikey", target: "_blank", rel: "noopener noreferrer" }, "Google AI Studio ↗"),
      ". Note: on Google's free plan your prompts (resume lines + job text) may be used by Google to improve their products; the paid plan doesn't do this.")
      : v === "openai" ? h("span", {}, "Create a key at ", h("a", { href: "https://platform.openai.com/api-keys", target: "_blank", rel: "noopener noreferrer" }, "platform.openai.com ↗"), " (needs billing; tailoring one resume costs about a cent with the default model).")
      : "Any service with an OpenAI-compatible /chat/completions endpoint.");
    base.closest("label") && (base.closest("label").style.display = v === "custom" ? "" : "none");
  };
  prov.addEventListener("change", setHelp);
  const saveAI = h("button", { class: "btn-primary" }, "Save");
  saveAI.addEventListener("click", busy(saveAI, async () => {
    await api.put("/api/integrations/ai", { provider: prov.value, api_key: key.value, model: model.value, base_url: base.value });
    toast("AI connection saved. Testing…");
    try { const r = await api.post("/api/integrations/ai/test"); toast(r.message); } catch {}
    render(root);
  }));

  // Adzuna
  const appId = h("input", { autocomplete: "off", placeholder: c.adzuna.app_id_hint ? `saved ${c.adzuna.app_id_hint}` : "app_id" });
  const appKey = h("input", { type: "password", autocomplete: "off", placeholder: c.adzuna.configured ? "saved — leave blank to keep" : "app_key" });
  const saveAdz = h("button", { class: "btn-primary" }, "Save");
  saveAdz.addEventListener("click", busy(saveAdz, async () => {
    await api.put("/api/integrations/adzuna", { app_id: appId.value, app_key: appKey.value, country: "us" });
    toast("Adzuna saved. Testing…");
    try { const r = await api.post("/api/integrations/adzuna/test"); toast(r.message); } catch {}
    render(root);
  }));

  const card = h("div", { class: "card" },
    h("div", { class: "card-head" }, h("h2", {}, "Connections"), h("span", { class: "faint" }, "Keys are encrypted and only used for your account")),
    h("div", { class: "grid cols-2" },
      h("div", { class: "stack" },
        h("div", { class: "row between" }, h("h3", {}, "AI model — rewrites resume sentences for each job"),
          h("span", { class: `badge ${c.ai.configured ? "good" : "warn"}` }, c.ai.configured ? `connected · ${c.ai.model}` : "not connected")),
        field("Provider", prov), field("API key", key), field("Model (optional)", model), field("Base URL", base), help,
        h("div", { class: "row" }, saveAI, c.ai.configured && h("button", { onclick: test("ai") }, "Test"), c.ai.source === "app" && h("button", { class: "btn-danger", onclick: remove("ai") }, "Remove"))),
      h("div", { class: "stack" },
        h("div", { class: "row between" }, h("h3", {}, "Adzuna — searches most US job boards"),
          h("span", { class: `badge ${c.adzuna.configured ? "good" : "warn"}` }, c.adzuna.configured ? "connected" : "not connected")),
        h("p", { class: "small muted" }, "Free: sign up at ", h("a", { href: "https://developer.adzuna.com/signup", target: "_blank", rel: "noopener noreferrer" }, "developer.adzuna.com ↗"),
          ", then copy the Application ID and Application Key from your dashboard."),
        field("Application ID", appId), field("Application Key", appKey),
        h("div", { class: "row" }, saveAdz, c.adzuna.configured && h("button", { onclick: test("adzuna") }, "Test"), c.adzuna.configured && h("button", { class: "btn-danger", onclick: remove("adzuna") }, "Remove")),
        h("p", { class: "faint" }, "Remotive (remote jobs) and The Muse work without any key."))));
  setTimeout(setHelp, 0);
  return card;
}

export async function render(root) {
  mount(root, loading());
  const [st, health, log, conns] = await Promise.all([api.get("/api/settings"), api.get("/api/health"), api.get("/api/audit-log"),
    api.get("/api/integrations")]);
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
    ["AI model (sentence tailoring)", conns.ai.configured ? `Connected · ${conns.ai.model}` : "Not connected — see Connections above", conns.ai.configured ? "good" : "warn", null],
    ["Adzuna job search", conns.adzuna.configured ? "Connected" : "Not connected — see Connections above", conns.adzuna.configured ? "good" : "warn", "https://developer.adzuna.com/"],
    ["Remotive · The Muse", "Real · public · no key needed", "good", null],
    ["Automatic application submission", "Not available — employers' ATS APIs need employer keys; you submit manually", "", null],
    ["LinkedIn messaging", "Not integrated — drafts are copied and sent by you", "", null],
  ];

  mount(root,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Settings & privacy"), h("div", { class: "sub" }, "Control what runs automatically and what happens to your data."))),
    connectionsCard(conns, root),
    h("div", { class: "grid cols-2", style: { marginTop: "16px" } },
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
