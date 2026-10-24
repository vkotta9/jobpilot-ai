import { api } from "../api.js";
import { h, mount, loading, empty, fmtDate, field, busy, toast } from "../ui.js";

let monthOffset = 0;

export async function render(root) {
  mount(root, loading());
  const [tasks, apps] = await Promise.all([api.get("/api/tasks"), api.get("/api/applications")]);
  const now = new Date();
  const day = (d) => new Date(d).toDateString();
  const groups = { Overdue: [], Today: [], "Next 7 days": [], Later: [] };
  for (const t of tasks) {
    const d = new Date(t.due_at);
    if (t.overdue && day(d) !== now.toDateString()) groups.Overdue.push(t);
    else if (day(d) === now.toDateString()) groups.Today.push(t);
    else if (d - now < 7 * 864e5) groups["Next 7 days"].push(t);
    else groups.Later.push(t);
  }

  const title = h("input", { placeholder: "e.g. Email recruiter at Acme" });
  const due = h("input", { type: "date", value: new Date(Date.now() + 2 * 864e5).toISOString().slice(0, 10) });
  const appSel = h("select", {}, h("option", { value: "" }, "Not linked to an application"), apps.map((a) => h("option", { value: a.id }, `${a.job.title} · ${a.job.company}`)));
  const add = h("button", { class: "btn-primary" }, "Add");
  add.addEventListener("click", busy(add, async () => {
    if (!title.value) return toast("Give the task a title.", "bad");
    await api.post("/api/tasks", { title: title.value, due_at: due.value + "T09:00:00", application_id: appSel.value ? Number(appSel.value) : null });
    render(root);
  }));

  mount(root,
    h("div", { class: "page-head" }, h("div", {}, h("h1", {}, "Follow-ups"),
      h("div", { class: "sub" }, "Reminders are created automatically after you submit an application, schedule an interview or send a message."))),
    h("div", { class: "grid side" },
      h("div", { class: "stack" },
        calendar(tasks, root),
        h("div", { class: "card" }, h("h2", {}, "Add a reminder"), h("div", { class: "form-grid" },
          h("div", { class: "full" }, field("What", title)), field("Due", due), field("Application", appSel)), h("div", { style: { marginTop: "10px" } }, add))),
      h("div", { class: "stack" },
        tasks.length ? Object.entries(groups).filter(([, v]) => v.length).map(([g, items]) => h("div", { class: "card" },
          h("h2", { style: { color: g === "Overdue" ? "var(--bad)" : "" } }, `${g} (${items.length})`),
          items.map((t) => h("div", { class: "list-item" },
            h("div", {}, h("div", { class: "small", style: { fontWeight: 600 } }, t.title),
              h("div", { class: "faint" }, fmtDate(t.due_at), " · ", t.kind.replace(/_/g, " "), t.application_id ? [" · ", h("a", { href: `#/applications/${t.application_id}` }, "open")] : "")),
            h("div", { class: "row", style: { gap: "4px" } },
              h("button", { class: "btn-sm", title: "Snooze 2 days", onclick: async () => { await api.post(`/api/tasks/${t.id}/snooze?days=2`); render(root); } }, "+2d"),
              h("button", { class: "btn-sm btn-primary", onclick: async () => { await api.post(`/api/tasks/${t.id}/done`); toast("Done."); render(root); } }, "✓ Done"))))))
          : h("div", { class: "card" }, empty("◷", "No open follow-ups", "You're all caught up.")))));
}

function calendar(tasks, root) {
  const base = new Date();
  base.setDate(1);
  base.setMonth(base.getMonth() + monthOffset);
  const start = new Date(base);
  start.setDate(1 - ((start.getDay() + 6) % 7));
  const days = [];
  for (let i = 0; i < 42; i++) { const d = new Date(start); d.setDate(start.getDate() + i); days.push(d); }
  const todayStr = new Date().toDateString();
  return h("div", { class: "card" },
    h("div", { class: "card-head" },
      h("h2", {}, base.toLocaleDateString(undefined, { month: "long", year: "numeric" })),
      h("div", { class: "row" },
        h("button", { class: "btn-sm", "aria-label": "Previous month", onclick: () => { monthOffset--; render(root); } }, "‹"),
        h("button", { class: "btn-sm", onclick: () => { monthOffset = 0; render(root); } }, "Today"),
        h("button", { class: "btn-sm", "aria-label": "Next month", onclick: () => { monthOffset++; render(root); } }, "›"))),
    h("div", { class: "cal" },
      ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].map((d) => h("div", { class: "dow" }, d)),
      days.map((d) => {
        const items = tasks.filter((t) => new Date(t.due_at).toDateString() === d.toDateString());
        return h("div", { class: `day ${d.getMonth() !== base.getMonth() ? "out" : ""} ${d.toDateString() === todayStr ? "today" : ""}` },
          h("div", { class: "faint" }, String(d.getDate())),
          items.slice(0, 3).map((t) => h("span", { class: `ev ${t.overdue ? "over" : ""}`, title: t.title }, t.title)),
          items.length > 3 && h("span", { class: "faint" }, `+${items.length - 3}`));
      })));
}
