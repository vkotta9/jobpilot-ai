import { api } from "./api.js";
import { h, mount, toast, field, busy } from "./ui.js";
import * as dashboard from "./pages/dashboard.js";
import * as profile from "./pages/profile.js";
import * as resumes from "./pages/resumes.js";
import * as discover from "./pages/discover.js";
import * as job from "./pages/job.js";
import * as documentPage from "./pages/document.js";
import * as application from "./pages/application.js";
import * as tracker from "./pages/tracker.js";
import * as networking from "./pages/networking.js";
import * as followups from "./pages/followups.js";
import * as analytics from "./pages/analytics.js";
import * as settings from "./pages/settings.js";
import * as prep from "./pages/prep.js";

const NAV = [
  ["Workspace"],
  ["#/dashboard", "◧", "Dashboard"],
  ["#/discover", "⌕", "Discover jobs"],
  ["#/tracker", "▤", "Tracker"],
  ["#/networking", "☍", "Networking"],
  ["#/followups", "◷", "Follow-ups"],
  ["#/analytics", "▥", "Analytics"],
  ["You"],
  ["#/profile", "☺", "Profile & preferences"],
  ["#/resumes", "▣", "Resume library"],
  ["#/settings", "⚙", "Settings & privacy"],
];

const ROUTES = [
  [/^#\/dashboard$/, dashboard], [/^#\/profile$/, profile], [/^#\/resumes$/, resumes],
  [/^#\/discover$/, discover], [/^#\/jobs\/(\d+)$/, job], [/^#\/documents\/(\d+)$/, documentPage],
  [/^#\/applications\/(\d+)$/, application], [/^#\/applications\/(\d+)\/prep$/, prep], [/^#\/tracker$/, tracker], [/^#\/networking$/, networking],
  [/^#\/followups$/, followups], [/^#\/analytics$/, analytics], [/^#\/settings$/, settings],
];

const state = { user: null, paused: false };
export const appState = state;

function sidebar() {
  const cur = location.hash.split("?")[0];
  const pauseBtn = h("button", { class: "btn-sm", onclick: togglePause }, state.paused ? "▶ Resume automation" : "❚❚ Pause automation");
  return h("aside", { class: "sidebar" },
    h("div", { class: "brand" }, h("div", { class: "brand-mark", "aria-hidden": "true" }, "✈"), "JobPilot AI"),
    h("nav", { class: "nav", "aria-label": "Main" },
      NAV.map((n) => n.length === 1 ? h("div", { class: "nav-sep" }, n[0])
        : h("a", { href: n[0], class: cur.startsWith(n[0]) || (n[0] === "#/discover" && cur.startsWith("#/jobs")) || (n[0] === "#/tracker" && (cur.startsWith("#/applications") || cur.startsWith("#/documents"))) ? "active" : "" },
          h("span", { class: "ico", "aria-hidden": "true" }, n[1]), n[2]))),
    h("div", { class: "sidebar-foot" },
      h("span", { class: state.paused ? "pill-paused" : "pill-live" }, state.paused ? "Automation paused" : "Automation on"),
      pauseBtn,
      h("span", {}, state.user?.email || ""),
      h("a", { href: "#", onclick: async (e) => { e.preventDefault(); await api.post("/api/auth/logout"); state.user = null; location.hash = "#/login"; } }, "Sign out")));
}

async function togglePause() {
  const r = await api.post(state.paused ? "/api/automation/resume" : "/api/automation/pause");
  state.paused = r.automation_paused;
  toast(state.paused ? "All automation paused. Nothing will run until you resume." : "Automation resumed.");
  route();
}

function authPage(mode = "login") {
  const email = h("input", { type: "email", autocomplete: "email", required: true });
  const pw = h("input", { type: "password", autocomplete: mode === "login" ? "current-password" : "new-password", required: true, minlength: 8 });
  const submit = h("button", { class: "btn-primary", type: "submit", style: { width: "100%", justifyContent: "center" } }, mode === "login" ? "Sign in" : "Create account");
  const form = h("form", { class: "stack", onsubmit: async (e) => {
    e.preventDefault();
    await busy(submit, async () => {
      const r = await api.post(`/api/auth/${mode === "login" ? "login" : "register"}`, { email: email.value, password: pw.value });
      state.user = r.user;
      location.hash = mode === "login" ? "#/dashboard" : "#/profile";
    })().catch(() => {});
  } },
    field("Email", email), field("Password", pw, mode === "register" ? "At least 8 characters." : null), submit);
  mount(document.getElementById("app"),
    h("div", { class: "auth-wrap" }, h("div", { class: "card auth-card" },
      h("div", { class: "brand" }, h("div", { class: "brand-mark" }, "✈"), "JobPilot AI"),
      h("p", { class: "muted", style: { textAlign: "center" } }, "Your personal, privacy-first job-search co-pilot."),
      form, hrLine(),
      h("p", { class: "small muted", style: { textAlign: "center" } },
        mode === "login" ? ["New here? ", h("a", { href: "#/register" }, "Create an account")]
          : ["Already have an account? ", h("a", { href: "#/login" }, "Sign in")]))));
  email.focus();
}
const hrLine = () => h("hr");

export async function route() {
  const hash = location.hash || "#/dashboard";
  if (hash === "#/login" || hash === "#/register") return authPage(hash.slice(2));
  if (!state.user) {
    try { state.user = await api.get("/api/auth/me", { quiet: true }); }
    catch { location.hash = "#/login"; return; }
    try { const s = await api.get("/api/settings", { quiet: true }); state.paused = s.automation_paused; } catch {}
  }
  const path = hash.split("?")[0];
  const match = ROUTES.find(([rx]) => rx.test(path));
  if (!match) { location.hash = "#/dashboard"; return; }
  const params = path.match(match[0]).slice(1);
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  mount(document.getElementById("app"), h("div", { class: "shell" }, sidebar(), main));
  try { await match[1].render(main, ...params); }
  catch (e) { mount(main, h("div", { class: "alert bad" }, e.message || "Failed to load this page.")); }
  main.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

export function setPaused(p) { state.paused = p; }

window.addEventListener("hashchange", route);
route();
