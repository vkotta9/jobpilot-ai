// Runs only on your JobPilot site: lets the JobPilot page talk to the extension.
(() => {
  const VERSION = chrome.runtime.getManifest().version;
  document.documentElement.dataset.jobpilotExtension = VERSION;
  const ALLOWED = new Set(["JOBPILOT_PING", "JOBPILOT_CONNECT", "JOBPILOT_APPLY"]);
  window.addEventListener("message", (e) => {
    if (e.source !== window || e.origin !== location.origin) return;
    const d = e.data || {};
    if (!ALLOWED.has(d.type)) return;
    chrome.runtime.sendMessage({ ...d, origin: location.origin }, (resp) => {
      const err = chrome.runtime.lastError;
      window.postMessage({ type: d.type + "_RESULT", nonce: d.nonce, ...(resp || { ok: false, error: err ? err.message : "no response" }) }, location.origin);
    });
  });
})();
