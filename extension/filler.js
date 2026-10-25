// JobPilot Autofill — fills the application form on this page with your JobPilot data.
// It never presses Submit, never accepts terms/consent boxes, never answers demographic (EEO) questions,
// and never touches CAPTCHAs. You review the highlighted fields and submit yourself.
(() => {
  if (window.__jobpilotFiller) { window.__jobpilotFiller.refill?.(); return; }
  const J = (window.__jobpilotFiller = {});
  const TOP = window.top === window;

  const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, (r) => res(r || {})));
  const norm = (s) => (s || "").replace(/\s+/g, " ").trim();
  const low = (s) => norm(s).toLowerCase();
  const visible = (el) => {
    if (el.type === "file") return true;  // file inputs are often hidden behind an "Attach" button
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none";
  };

  // ------------------------------------------------------------ label text for a field
  function labelOf(el) {
    const parts = [];
    if (el.id) {
      const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l) parts.push(l.innerText);
    }
    const anc = el.closest("label");
    if (anc) parts.push(anc.innerText);
    const lb = el.getAttribute("aria-labelledby");
    if (lb) lb.split(/\s+/).forEach((id) => { const n = document.getElementById(id); if (n) parts.push(n.innerText); });
    ["aria-label", "placeholder", "data-qa", "name", "id", "autocomplete"].forEach((a) => el.getAttribute(a) && parts.push(el.getAttribute(a)));
    if (!parts.some((p) => norm(p).length > 2)) {
      // nearest text before the field inside its container (custom form builders)
      let n = el, hops = 0;
      while (n && hops < 4 && !parts.some((p) => norm(p).length > 2)) {
        n = n.parentElement; hops++;
        if (!n) break;
        const lg = n.querySelector("legend, label, .label, [class*='label'], [class*='question']");
        if (lg && !lg.contains(el)) parts.push(lg.innerText);
      }
    }
    return norm(parts.join(" | ")).slice(0, 400);
  }
  function groupLabel(el) {  // radio/checkbox groups: the question, not the option
    const fs = el.closest("fieldset");
    if (fs) { const lg = fs.querySelector("legend"); if (lg) return norm(lg.innerText); }
    let n = el.parentElement;
    for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
      const q = n.querySelector("legend, label:not(:has(input)), [class*='label'], [class*='question'], h3, h4, p");
      if (q && !q.contains(el) && norm(q.innerText).length > 3) return norm(q.innerText);
    }
    return labelOf(el);
  }

  // ------------------------------------------------------------ setting values like a person would
  const setNative = (el, v) => {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, v);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  };
  const mark = (el, ok) => { el.style.outline = ok ? "2px solid #22c55e" : "2px solid #f59e0b"; el.style.outlineOffset = "1px"; };

  function chooseOption(options, want) {  // options: [{text, el}]
    const w = low(want);
    if (!w) return null;
    const yes = /^(yes|true|y)\b/.test(w), no = /^(no|false|n)\b/.test(w);
    let best = null, bestScore = 0;
    for (const o of options) {
      const t = low(o.text);
      if (!t || /^(select|choose|please select|--)/.test(t)) continue;
      let s = 0;
      if (t === w) s = 100;
      else if (yes && /^yes\b/.test(t)) s = 90;
      else if (no && /^no\b/.test(t)) s = 90;
      else if (t.includes(w) || w.includes(t)) s = 60 + Math.min(t.length, w.length) / Math.max(t.length, w.length) * 20;
      else {
        const tw = new Set(t.split(/\W+/).filter((x) => x.length > 2)), ww = w.split(/\W+/).filter((x) => x.length > 2);
        const hit = ww.filter((x) => tw.has(x)).length;
        if (hit) s = 30 + 30 * hit / Math.max(ww.length, 1);
      }
      if (s > bestScore) { best = o; bestScore = s; }
    }
    return bestScore >= 45 ? best : null;
  }

  function attach(input, file) {
    if (!file || !file.base64) return false;
    const bin = atob(file.base64), bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const f = new File([bytes], file.filename, { type: file.mime });
    const dt = new DataTransfer();
    dt.items.add(f);
    try {
      input.files = dt.files;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    } catch { return false; }
  }

  // ------------------------------------------------------------ what goes where
  const NEVER = /gender|sex\b|race|ethnic|hispanic|latino|veteran|disabilit|pronoun|sexual orientation|transgender|date of birth|birth ?date|\bage\b|social security|\bssn\b|religion|marital|captcha|password|signature|i agree|consent|terms|privacy|acknowledg|certify|attest/i;

  function profileValue(label, P, W) {
    const l = low(label);
    const rules = [
      [/preferred (first )?name|first[\s_-]?name|given[\s_-]?name|\bfname\b/, P.first_name],
      [/last[\s_-]?name|family[\s_-]?name|surname|\blname\b/, P.last_name],
      [/^(full[\s_-]?)?name\b|full[\s_-]?name|legal name|your name|candidate name|^name$/, P.full_name],
      [/e-?mail/, P.email],
      [/phone|mobile|telephone|\btel\b/, P.phone],
      [/linkedin/, P.linkedin],
      [/github/, P.github],
      [/portfolio|personal (web)?site|website|blog|other url|\burl\b/, P.website || P.github || P.linkedin],
      [/current (company|employer)|most recent (company|employer)|^company$|employer/, P.current_company],
      [/current (job )?title|most recent title|job title|current role|^title$/, P.current_title],
      [/school|university|college|institution/, P.school],
      [/discipline|major|field of study|area of study/, P.field],
      [/degree/, P.degree],
      [/graduation (year|date)|year of graduation|grad year/, P.grad_year],
      [/years of (professional |relevant |work )?experience|how many years/, P.years_experience != null ? String(Math.floor(P.years_experience)) : ""],
      [/\bcity\b/, P.city],
      [/\bstate\b|province|region/, P.state],
      [/country/, P.country],
      [/location|where are you (located|based)|current address|address/, P.location],
    ];
    for (const [rx, v] of rules) if (rx.test(l) && v) return v;
    // work authorization / sponsorship — only from what you saved in your profile
    if (/sponsor|visa/.test(l) && W.requires_sponsorship != null) return W.requires_sponsorship ? "Yes" : "No";
    if (/(legally )?authori[sz]ed to work|eligib\w* to work|right to work|work authori[sz]ation/.test(l) && (W.authorized_countries || []).length) {
      const c = (W.authorized_countries || []).join(" ").toLowerCase();
      const asksUS = /united states|\bu\.?s\.?\b|\busa\b/.test(l) || !/canada|kingdom|\buk\b|europe|india/.test(l);
      if (asksUS) return /united states|\busa?\b|america/.test(c) ? "Yes" : "No";
    }
    return "";
  }

  const words = (s) => new Set(low(s).replace(/[^a-z0-9 ]/g, " ").split(" ").filter((w) => w.length > 2 && !STOP.has(w)));
  const STOP = new Set(["the", "you", "your", "are", "for", "and", "with", "this", "that", "have", "what", "please", "will", "our", "any", "how", "why", "can", "does", "did", "who", "about", "would", "describe"]);
  function answerFor(label, answers) {
    const lw = words(label);
    if (!lw.size) return "";
    let best = "", score = 0;
    for (const a of answers) {
      const qw = words(a.question);
      const inter = [...qw].filter((w) => lw.has(w)).length;
      const s = inter / Math.max(1, Math.min(qw.size, lw.size));
      if (s > score) { score = s; best = a.answer; }
    }
    return score >= 0.6 ? best : "";
  }

  // ------------------------------------------------------------ fill the page
  let payload = null;
  const stats = { filled: 0, attached: [], needs: [] };

  function fill() {
    if (!payload) return;
    const P = payload.profile, W = payload.work_auth || {}, A = payload.answers || [];
    stats.filled = 0; stats.attached = []; stats.needs = [];
    const fields = [...document.querySelectorAll("input, textarea, select")].filter((el) =>
      !el.disabled && !el.readOnly && !["hidden", "submit", "button", "reset", "image", "search"].includes(el.type) && visible(el));

    // files: resume first, then cover letter
    const files = fields.filter((el) => el.type === "file");
    for (const el of files) {
      if (el.files && el.files.length) continue;
      const l = low(labelOf(el) + " " + (el.closest("div,section,fieldset")?.innerText || "").slice(0, 200));
      if (/cover/.test(l) && !/resume|cv\b/.test(low(labelOf(el)))) {
        if (payload.cover_letter && attach(el, payload.cover_letter)) stats.attached.push("cover letter");
      } else if (/resume|cv\b|curriculum/.test(l) || files.length === 1 || el === files[0]) {
        if (attach(el, payload.resume)) stats.attached.push("resume");
      }
    }

    const radiosDone = new Set();
    for (const el of fields) {
      if (el.type === "file") continue;
      if (el.type === "radio" || el.type === "checkbox") {
        if (!el.name || radiosDone.has(el.name)) continue;
        radiosDone.add(el.name);
        const q = groupLabel(el);
        if (NEVER.test(q)) continue;
        const group = [...document.querySelectorAll(`input[name="${CSS.escape(el.name)}"]`)];
        if (group.some((g) => g.checked)) continue;
        const want = profileValue(q, P, W) || answerFor(q, A);
        if (!want) { if (el.required) stats.needs.push(q); continue; }
        const opt = chooseOption(group.map((g) => ({ text: labelOf(g) + " " + g.value, el: g })), want);
        if (opt) { opt.el.click(); mark(opt.el, true); stats.filled++; }
        continue;
      }
      if (el.value && el.value.trim()) continue;  // never overwrite what's already there
      const label = labelOf(el);
      if (!label || NEVER.test(label)) continue;
      let v = profileValue(label, P, W);
      if (!v && /cover letter|why (do you want|are you interested)|additional information|message to/i.test(label) && el.tagName === "TEXTAREA" && payload.cover_letter?.text) v = payload.cover_letter.text;
      if (!v) v = answerFor(label, A);
      if (!v) { if (el.required || el.getAttribute("aria-required") === "true") { mark(el, false); stats.needs.push(label.split("|")[0]); } continue; }
      if (el.tagName === "SELECT") {
        const opt = chooseOption([...el.options].map((o) => ({ text: o.text, el: o })), v);
        if (opt) { setNative(el, opt.el.value); mark(el, true); stats.filled++; } else if (el.required) { mark(el, false); stats.needs.push(label.split("|")[0]); }
      } else {
        if (el.type === "email" && !/@/.test(v)) continue;
        if (el.type === "number" && isNaN(Number(v))) continue;
        setNative(el, String(v)); mark(el, true); stats.filled++;
      }
    }
    if (TOP) panel();
    else send({ type: "FRAME_STATS", stats });
  }

  // ------------------------------------------------------------ open the form if this is the job description page
  function openFormIfNeeded() {
    const hasForm = document.querySelector("input[type=email], input[type=file], input[name*=name i]");
    if (hasForm || sessionStorage.getItem("jp_clicked_apply")) return false;
    const href = location.href;
    if (/jobs\.lever\.co\/[^/]+\/[^/]+\/?$/.test(href)) { sessionStorage.setItem("jp_clicked_apply", "1"); location.href = href.replace(/\/?$/, "/apply"); return true; }
    if (/jobs\.ashbyhq\.com\/[^/]+\/[^/]+\/?$/.test(href)) { sessionStorage.setItem("jp_clicked_apply", "1"); location.href = href.replace(/\/?$/, "/application"); return true; }
    const btn = [...document.querySelectorAll("a, button")].find((b) => /^\s*(apply( now| for this (job|position|role))?|i'?m interested|start (your )?application)\s*$/i.test(b.innerText || "") && visible(b));
    if (btn) { sessionStorage.setItem("jp_clicked_apply", "1"); btn.click(); return true; }
    return false;
  }

  // ------------------------------------------------------------ notice when you submit
  const CONFIRM = /thank you for (your )?(applying|application|your interest|submitting)|application (has been |was )?(submitted|received)|we('|’)ve received your application|successfully (submitted|applied)|your application is (complete|on its way)/i;
  let pending = false;
  function markPending() { pending = true; send({ type: "PENDING_SUBMIT" }); }
  function watchSubmit() {
    document.addEventListener("submit", markPending, true);
    document.addEventListener("click", (e) => {
      const b = e.target.closest && e.target.closest("button, input[type=submit]");
      if (b && /^(submit( (my )?application)?|send( application)?|apply|finish)$/i.test((b.innerText || b.value || "").trim())) markPending();
    }, true);
  }
  let reported = false;
  function checkConfirmation() {
    if (!pending || reported) return false;
    const text = norm(document.body?.innerText || "");
    const m = text.match(CONFIRM);
    if (!m) return false;
    reported = true;
    const i = Math.max(0, m.index - 150);
    send({ type: "SUBMITTED", detail: text.slice(i, i + 500), url: location.href }).then((r) => r.ok && showDone(r.verified));
    return true;
  }

  // ------------------------------------------------------------ the little panel (top frame only)
  let host = null;
  function panel() {
    if (!host) {
      host = document.createElement("div");
      host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647";
      document.documentElement.appendChild(host);
      host.attachShadow({ mode: "open" });
    }
    const j = payload.job;
    const all = [stats, ...Object.values(frameStats)];
    const filled = all.reduce((a, x) => a + (x.filled || 0), 0);
    const attached = all.flatMap((x) => x.attached || []);
    const att = attached.length ? ` Attached your ${[...new Set(attached)].join(" and ")}.` : "";
    const needs = [...new Set(all.flatMap((x) => x.needs || []))].slice(0, 6);
    host.shadowRoot.innerHTML = `
      <style>
        .b{font:13px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#fff;color:#1f2337;border:1px solid #d9dcf2;border-radius:12px;
           box-shadow:0 10px 30px rgba(20,20,60,.18);padding:12px 14px;width:310px}
        .h{display:flex;align-items:center;gap:8px;font-weight:700;margin-bottom:4px}.dot{width:10px;height:10px;border-radius:3px;background:#5b4fe9}
        .m{color:#4b5068}.n{margin:6px 0 0;padding-left:18px;color:#b45309}.r{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
        button{font:600 12px system-ui;border-radius:8px;border:1px solid #d9dcf2;background:#f6f7ff;padding:6px 10px;cursor:pointer}
        button.p{background:#5b4fe9;color:#fff;border-color:#5b4fe9}.x{margin-left:auto;border:none;background:none;font-size:16px;padding:0 4px}
      </style>
      <div class="b">
        <div class="h"><span class="dot"></span>JobPilot · ${esc(j.company)}<button class="x" title="Close">×</button></div>
        <div class="m">Filled ${filled} field${filled === 1 ? "" : "s"}.${att} Green = filled by JobPilot. Check everything, then press the site's <b>Submit</b> button.</div>
        ${needs.length ? `<div class="m" style="margin-top:6px">Needs your answer (orange):</div><ul class="n">${needs.map((n) => `<li>${esc(n.slice(0, 70))}</li>`).join("")}</ul>` : ""}
        <div class="r"><button class="p" id="again">Fill again</button><button id="done">I've submitted it</button></div>
      </div>`;
    host.shadowRoot.querySelector(".x").onclick = () => host.remove();
    host.shadowRoot.getElementById("again").onclick = () => { fill(); };
    host.shadowRoot.getElementById("done").onclick = () => {
      const text = norm(document.body.innerText).slice(0, 500);
      send({ type: "SUBMITTED", detail: text, url: location.href }).then((r) => r.ok ? showDone(r.verified) : alertBox(r.error));
    };
  }
  function showDone(verified) {
    if (!TOP) return;
    if (!host) panel();
    host.shadowRoot.querySelector(".b").innerHTML =
      `<div class="h"><span class="dot" style="background:#22c55e"></span>Recorded in JobPilot</div>
       <div class="m">${verified ? "Submission recorded with the site's confirmation." : "Submission recorded."} Follow-ups are scheduled in JobPilot.</div>`;
  }
  function alertBox(msg) { if (host) host.shadowRoot.querySelector(".m").textContent = "JobPilot: " + (msg || "something went wrong"); }
  const esc = (s) => String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // ------------------------------------------------------------ start
  J.refill = () => fill();
  const frameStats = {};
  if (TOP) {
    chrome.runtime.onMessage.addListener((m) => {
      if (m.type === "FRAME_STATS") { frameStats[m.frameId] = m.stats; if (payload) panel(); }
      if (m.type === "FRAME_SUBMITTED") showDone(m.verified);
    });
  }
  (async () => {
    const r = await send({ type: "GET_PAYLOAD" });
    if (!r.ok || !r.payload) return;
    payload = r.payload;
    if (r.submitted) return;
    pending = !!r.pendingSubmit && Date.now() - r.pendingSubmit < 15 * 60 * 1000;
    if (checkConfirmation()) return;
    if (TOP && openFormIfNeeded()) return;
    watchSubmit();
    // forms are often rendered by JavaScript after load: fill now, and again as fields appear
    fill();
    let timer = null, rounds = 0;
    const mo = new MutationObserver(() => {
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (checkConfirmation()) return;
        if (rounds++ < 8) fill();
      }, 700);
    });
    mo.observe(document.documentElement, { childList: true, subtree: true });
    setTimeout(() => { if (!pending) mo.disconnect(); }, 60000);
  })();
})();
