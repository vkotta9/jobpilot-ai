// Interview prep plan for one application.
import { api } from "../api.js";
import { h, mount, loading, busy, toast, fmtDate } from "../ui.js";

const PRI = { high: ["bad", "High priority"], medium: ["warn", "Medium"], low: ["", "Low"] };
const link = (r) => h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, r.title, " ↗");

export async function render(root, id) {
  mount(root, loading());
  const r = await api.get(`/api/applications/${id}/prep`);
  let p = r.prep;
  const j = r.job;

  const regen = (useAi) => {
    const b = h("button", { class: useAi ? "btn-primary" : "" }, useAi ? "✨ Add questions for this posting (AI)" : "↻ Refresh plan");
    b.addEventListener("click", busy(b, async () => {
      const out = await api.post(`/api/applications/${id}/prep`, { use_ai: useAi });
      p = out.prep;
      toast(p.ai_note || (useAi ? "Added questions written for this posting." : "Plan refreshed."), p.ai_note ? "bad" : "");
      draw();
    }));
    return b;
  };

  const saveDone = async () => { await api.put(`/api/applications/${id}/prep/progress`, { done: p.done || [] }); };

  function planCard() {
    const done = new Set(p.done || []);
    const days = {};
    p.plan.forEach((t) => (days[t.day] = days[t.day] || []).push(t));
    const pct = Math.round((100 * done.size) / Math.max(1, p.plan.length));
    const bar = h("div", { style: { height: "8px", background: "var(--surface-2)", borderRadius: "99px", overflow: "hidden", margin: "6px 0 12px" } },
      h("div", { style: { width: `${pct}%`, height: "100%", background: "var(--good)" } }));
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, `📅 Your ${p.plan_days}-day prep plan`),
        h("span", { class: "faint" }, `${done.size} of ${p.plan.length} done` + (p.next_interview ? ` · next interview ${fmtDate(p.next_interview, true)}` : ""))),
      bar,
      Object.entries(days).map(([d, ts]) => h("div", { style: { marginBottom: "10px" } },
        h("h3", {}, `Day ${d}`),
        ts.map((t) => {
          const cb = h("input", { type: "checkbox", checked: done.has(t.id) });
          cb.addEventListener("change", async () => {
            p.done = cb.checked ? [...done, t.id] : [...done].filter((x) => x !== t.id);
            await saveDone(); draw();
          });
          return h("label", { class: "check", style: { alignItems: "flex-start", margin: "5px 0", textDecoration: done.has(t.id) ? "line-through" : "", opacity: done.has(t.id) ? 0.6 : 1 } },
            cb, h("span", {}, t.task, h("span", { class: "faint small" }, ` · ${t.area}`)));
        }))));
  }

  function stagesCard() {
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "🧭 What the process usually looks like"),
        h("span", { class: "faint" }, `${p.role.family_name} · ${p.role.level} level${p.role.years_required ? ` · ${p.role.years_required}+ yrs asked` : ""}`)),
      h("p", { class: "small muted" }, "Typical rounds for this kind of role — each company varies, so confirm the steps with your recruiter."),
      h("div", { class: "timeline" }, p.stages.map((s, i) => h("div", { class: "ev" },
        h("div", {}, h("strong", {}, `${i + 1}. ${s.name}`), h("span", { class: "faint small" }, ` · ${s.length}`)),
        h("div", { class: "small" }, s.what),
        h("div", { class: "small", style: { color: "var(--accent)" } }, "How to do well: " + s.how)))),
      p.company && h("div", { class: "alert", style: { marginTop: "10px" } },
        h("strong", {}, `${p.company.name}: `), p.company.notes.join(" "), " ", link({ title: `${p.company.name}'s official interview guide`, url: p.company.url })));
  }

  function focusCard() {
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "📚 What to prepare"), h("span", { class: "faint" }, "from the posting and your resume")),
      p.gaps.length > 0 && h("div", { class: "alert warn", style: { marginBottom: "10px" } },
        h("strong", {}, "Close these gaps first: "), p.gaps.map((g) => g.skill).join(", "),
        h("div", { class: "small" }, p.gaps[0].advice)),
      p.focus.map((f) => h("details", { class: "list-item", style: { display: "block" }, open: f.priority === "high" && f === p.focus[0] },
        h("summary", { style: { cursor: "pointer" } }, h("strong", {}, f.label), " ", h("span", { class: `badge ${PRI[f.priority][0]}` }, PRI[f.priority][1]),
          h("div", { class: "faint small" }, f.why)),
        h("div", { class: "grid cols-2", style: { gap: "10px", marginTop: "8px" } },
          h("div", {}, h("div", { class: "small", style: { fontWeight: 600 } }, "Topics"), h("ul", { class: "small" }, f.topics.map((t) => h("li", {}, t)))),
          h("div", {}, h("div", { class: "small", style: { fontWeight: 600 } }, "Practice questions"), h("ul", { class: "small" }, f.questions.map((q) => h("li", {}, q))))),
        h("div", { class: "small" }, h("strong", {}, "Resources: "), f.resources.map((x, i) => [i ? " · " : "", link(x)])))));
  }

  function behavioralCard() {
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "🗣 Behavioral questions — with stories from your resume"), link(p.behavioral_resources[0])),
      h("p", { class: "small muted" }, "Answer with STAR: Situation → Task → Action (what you did) → Result (with a number). Practice each out loud in about 2 minutes."),
      p.behavioral.map((b) => h("div", { class: "list-item", style: { display: "block" } },
        h("div", {}, h("strong", {}, b.question)),
        b.story ? h("div", { class: "small", style: { marginTop: "4px" } }, h("span", { class: "faint" }, "Use: "), b.story) : null,
        h("div", { class: "small", style: { color: b.story ? "var(--accent)" : "var(--warn)" } }, b.tip))));
  }

  function aiCard() {
    const qs = p.ai_questions || [];
    return h("div", { class: "card" },
      h("div", { class: "card-head" }, h("h2", {}, "🎯 Questions likely for this posting"), regen(true)),
      qs.length ? qs.map((q) => h("div", { class: "list-item", style: { display: "block" } },
        h("div", {}, h("strong", {}, q.question), " ", h("span", { class: "badge" }, q.type)),
        h("div", { class: "small faint" }, "Why likely: " + q.why_likely),
        h("div", { class: "small" }, h("strong", {}, "A strong answer covers: "), q.strong_answer_covers),
        q.use_from_resume && h("div", { class: "small", style: { color: "var(--accent)" } }, "Use from your resume: " + q.use_from_resume)))
        : h("p", { class: "small muted" }, "Your AI model can write ~10 questions tailored to this exact posting, each with what a strong answer covers and which of your experiences to use. (These are likely questions, not the employer's actual ones.)"),
      p.ai_note && h("div", { class: "small", style: { color: "var(--warn)" } }, p.ai_note));
  }

  function draw() {
    mount(root,
      h("div", { class: "faint", style: { marginBottom: "8px" } }, h("a", { href: `#/applications/${id}` }, `← Application · ${j.title} @ ${j.company}`)),
      h("div", { class: "page-head" },
        h("div", {}, h("h1", {}, "Interview prep"), h("div", { class: "sub" }, `${j.title} at ${j.company} — what to expect, what to study, and how to answer.`)),
        h("div", { class: "row" }, regen(false))),
      h("div", { class: "grid side" },
        h("div", { class: "stack" }, stagesCard(), focusCard(), behavioralCard(), aiCard()),
        h("div", { class: "stack" }, planCard(),
          h("div", { class: "card" }, h("h2", {}, "❓ Questions to ask them"), h("ul", { class: "small" }, p.ask_them.map((q) => h("li", {}, q)))),
          h("div", { class: "card" }, h("h2", {}, "🔗 Practice"), h("ul", { class: "small" }, p.general_resources.map((x) => h("li", {}, link(x))))))));
  }
  draw();
}
