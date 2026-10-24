// API client. The session lives in an httpOnly cookie, so no token is ever
// readable by page scripts; no API keys exist in the frontend.
import { download, toast } from "./ui.js";

async function request(method, path, body, { raw = false, quiet = false } = {}) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(path, opts); }
  catch { const e = new Error("Cannot reach the JobPilot server. Is it running?"); if (!quiet) toast(e.message, "bad"); throw e; }
  if (res.status === 401 && !path.startsWith("/api/auth/")) { location.hash = "#/login"; throw new Error("Please sign in"); }
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { const j = await res.json(); if (j.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch {}
    const e = new Error(detail); e.status = res.status;
    if (!quiet) toast(detail, "bad");
    throw e;
  }
  if (raw) return res;
  const ct = res.headers.get("content-type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

export const api = {
  get: (p, o) => request("GET", p, undefined, o),
  post: (p, b, o) => request("POST", p, b ?? {}, o),
  put: (p, b, o) => request("PUT", p, b, o),
  patch: (p, b, o) => request("PATCH", p, b, o),
  del: (p, o) => request("DELETE", p, undefined, o),
  async file(path, fallbackName) {
    const res = await request("GET", path, undefined, { raw: true });
    const cd = res.headers.get("content-disposition") || "";
    const m = /filename="?([^";]+)"?/.exec(cd);
    download(await res.blob(), m ? m[1] : fallbackName);
  },
};

export function qs(obj) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(obj)) if (v !== "" && v !== null && v !== undefined) p.set(k, v);
  const s = p.toString();
  return s ? `?${s}` : "";
}
