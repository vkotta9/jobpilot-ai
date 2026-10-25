// JobPilot Autofill — background service worker.
// Keeps the connection to your JobPilot site, opens application pages you start from JobPilot,
// and fills them (only in tabs JobPilot opened, or when you click "Fill this page").
importScripts("config.js");

const api = async (path, opts = {}) => {
  const { conn } = await chrome.storage.local.get("conn");
  if (!conn?.token) throw new Error("Not connected — open JobPilot → Settings → Browser extension → Connect.");
  const r = await fetch(conn.origin + path, {
    ...opts,
    headers: { "Authorization": "Bearer " + conn.token, "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  let body = null;
  try { body = await r.json(); } catch { /* not JSON */ }
  if (!r.ok) throw new Error((body && body.detail) || `JobPilot returned HTTP ${r.status}`);
  return body;
};

const allowedOrigin = (origin) => !self.JOBPILOT_ORIGIN || origin === self.JOBPILOT_ORIGIN;

async function tabState(tabId) {
  const k = "tab:" + tabId;
  return (await chrome.storage.session.get(k))[k] || null;
}
async function setTabState(tabId, v) {
  await chrome.storage.session.set({ ["tab:" + tabId]: v });
}

async function inject(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["filler.js"] });
  } catch (e) {
    // pages like the Chrome Web Store or PDFs can't be scripted; nothing to fill there
    console.warn("JobPilot: couldn't open the page for filling:", e.message);
  }
}

chrome.tabs.onUpdated.addListener(async (tabId, info) => {
  if (info.status !== "complete") return;
  const st = await tabState(tabId);
  if (st) inject(tabId);  // each new page in an application tab (multi-step forms, confirmation page)
});
chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove("tab:" + tabId));

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  (async () => {
    try {
      switch (msg.type) {
        // ---- from the JobPilot site (bridge.js)
        case "JOBPILOT_PING": {
          const { conn } = await chrome.storage.local.get("conn");
          return reply({ ok: true, installed: true, connected: !!conn?.token && conn.origin === msg.origin, email: conn?.email || "" });
        }
        case "JOBPILOT_CONNECT": {
          if (!allowedOrigin(msg.origin)) return reply({ ok: false, error: "This extension belongs to a different JobPilot site." });
          await chrome.storage.local.set({ conn: { origin: msg.origin, token: msg.token, email: msg.email || "" } });
          const me = await api("/api/extension/ping");
          await chrome.storage.local.set({ conn: { origin: msg.origin, token: msg.token, email: me.email } });
          return reply({ ok: true, email: me.email });
        }
        case "JOBPILOT_APPLY": {
          const { conn } = await chrome.storage.local.get("conn");
          if (!conn?.token || conn.origin !== msg.origin) return reply({ ok: false, error: "not_connected" });
          const payload = await api(`/api/applications/${msg.appId}/autofill`);  // fails early if not approved
          const tab = await chrome.tabs.create({ url: msg.url || payload.job.url, active: true });
          await setTabState(tab.id, { appId: msg.appId, payload, filledAt: 0 });
          await chrome.storage.local.set({ lastApp: { appId: msg.appId, title: payload.job.title, company: payload.job.company } });
          return reply({ ok: true });
        }
        // ---- from the filler running on the application page
        case "GET_PAYLOAD": {
          const st = await tabState(sender.tab.id);
          if (!st) return reply({ ok: false });
          return reply({ ok: true, payload: st.payload, appId: st.appId, submitted: !!st.submitted, pendingSubmit: st.pendingSubmit || 0 });
        }
        case "FRAME_STATS": {  // a form inside an iframe (e.g. an embedded Greenhouse form) reports to the page's panel
          chrome.tabs.sendMessage(sender.tab.id, { type: "FRAME_STATS", stats: msg.stats, frameId: sender.frameId }, { frameId: 0 }).catch(() => {});
          return reply({ ok: true });
        }
        case "PENDING_SUBMIT": {
          const st = await tabState(sender.tab.id);
          if (st) await setTabState(sender.tab.id, { ...st, pendingSubmit: Date.now() });
          return reply({ ok: true });
        }
        case "SUBMITTED": {
          const st = await tabState(sender.tab.id);
          if (!st || st.submitted) return reply({ ok: true, already: true });
          const r = await api(`/api/applications/${st.appId}/extension-submitted`, {
            method: "POST", body: JSON.stringify({ confirmation_detail: msg.detail || "", page_url: msg.url || "" }),
          });
          await setTabState(sender.tab.id, { ...st, submitted: true, pendingSubmit: 0 });
          if (sender.frameId) chrome.tabs.sendMessage(sender.tab.id, { type: "FRAME_SUBMITTED", verified: r.verified }, { frameId: 0 }).catch(() => {});
          return reply({ ok: true, verified: r.verified });
        }
        // ---- from the popup
        case "POPUP_STATE": {
          const { conn, lastApp } = await chrome.storage.local.get(["conn", "lastApp"]);
          const st = msg.tabId ? await tabState(msg.tabId) : null;
          return reply({ connected: !!conn?.token, origin: conn?.origin || self.JOBPILOT_ORIGIN || "", email: conn?.email || "", lastApp, tabApp: st && st.payload.job });
        }
        case "FILL_THIS_PAGE": {
          const { lastApp } = await chrome.storage.local.get("lastApp");
          let st = await tabState(msg.tabId);
          if (!st) {
            if (!lastApp) return reply({ ok: false, error: "Start an application from JobPilot first (Apply with JobPilot)." });
            const payload = await api(`/api/applications/${lastApp.appId}/autofill`);
            st = { appId: lastApp.appId, payload, filledAt: 0 };
            await setTabState(msg.tabId, st);
          }
          await inject(msg.tabId);
          return reply({ ok: true });
        }
        case "DISCONNECT": {
          await chrome.storage.local.remove(["conn", "lastApp"]);
          return reply({ ok: true });
        }
        default:
          return reply({ ok: false, error: "unknown message" });
      }
    } catch (e) {
      reply({ ok: false, error: String(e.message || e) });
    }
  })();
  return true;  // async reply
});
