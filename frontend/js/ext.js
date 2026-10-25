// Talks to the JobPilot Autofill browser extension (through its bridge script on this site).
let n = 0;
function ask(type, data = {}, timeout = 4000) {
  return new Promise((resolve) => {
    const nonce = `${Date.now()}-${++n}`;
    const onMsg = (e) => {
      if (e.source !== window || e.origin !== location.origin) return;
      const d = e.data || {};
      if (d.type === type + "_RESULT" && d.nonce === nonce) { window.removeEventListener("message", onMsg); clearTimeout(t); resolve(d); }
    };
    const t = setTimeout(() => { window.removeEventListener("message", onMsg); resolve({ ok: false, error: "timeout" }); }, timeout);
    window.addEventListener("message", onMsg);
    window.postMessage({ type, nonce, ...data }, location.origin);
  });
}

export const installed = () => !!document.documentElement.dataset.jobpilotExtension;
export async function status() {
  if (!installed()) return { installed: false, connected: false };
  const r = await ask("JOBPILOT_PING");
  return { installed: true, connected: !!r.connected, email: r.email || "" };
}
export const connect = (token, email) => ask("JOBPILOT_CONNECT", { token, email }, 10000);
export const apply = (appId, url) => ask("JOBPILOT_APPLY", { appId, url }, 20000);
