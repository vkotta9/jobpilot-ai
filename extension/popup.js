const $ = (id) => document.getElementById(id);
const esc = (x) => String(x || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const send = (m) => new Promise((r) => chrome.runtime.sendMessage(m, (x) => r(x || {})));
(async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const s = await send({ type: "POPUP_STATE", tabId: tab?.id });
  const st = $("state"), act = $("actions");
  if (!s.connected) {
    st.innerHTML = `<span class="bad">Not connected.</span> Open JobPilot → <b>Settings → Browser extension</b> and click <b>Connect</b>.`;
    if (s.origin) { const a = document.createElement("a"); a.className = "btn p"; a.href = s.origin + "/#/settings"; a.target = "_blank"; a.textContent = "Open JobPilot"; act.append(a); }
    return;
  }
  st.innerHTML = `<span class="ok">Connected</span> as ${esc(s.email) || "you"}.` +
    (s.tabApp ? `<br>This tab: <b>${esc(s.tabApp.title)}</b> at ${esc(s.tabApp.company)}.` : s.lastApp ? `<br>Last application: <b>${esc(s.lastApp.title)}</b> at ${esc(s.lastApp.company)}.` : "<br>Click <b>Apply with JobPilot</b> on an approved application to start.");
  if (s.tabApp || s.lastApp) {
    const b = document.createElement("button"); b.className = "p"; b.textContent = "Fill this page";
    b.onclick = async () => { const r = await send({ type: "FILL_THIS_PAGE", tabId: tab.id }); st.textContent = r.ok ? "Filling… check the page." : r.error; };
    act.append(b);
  }
  const o = document.createElement("a"); o.className = "btn"; o.href = s.origin + "/#/tracker"; o.target = "_blank"; o.textContent = "Open JobPilot"; act.append(o);
  const d = document.createElement("button"); d.textContent = "Disconnect";
  d.onclick = async () => { await send({ type: "DISCONNECT" }); location.reload(); };
  act.append(d);
})();
