// Thin fetch wrapper for /api/*. Every non-2xx response is turned into an
// ApiError carrying the parsed `detail` (a string or the structured
// {sqlstate, message, position} shape the backend uses for DB errors), so
// callers can render it without re-parsing anything.

const BASE = "/api";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(BASE + path, opts);
  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) {
    const detail = data && typeof data === "object" && "detail" in data ? data.detail : data;
    throw new ApiError(res.status, detail);
  }
  return data;
}

function qs(params) {
  const entries = Object.entries(params || {}).filter(
    ([, v]) => v !== undefined && v !== null && v !== ""
  );
  if (!entries.length) return "";
  return "?" + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
}

export const api = {
  health: () => request("GET", "/health"),
  serverInfo: () => request("GET", "/meta/server-info"),
  schema: (database) => request("GET", `/meta/schema${qs({ database })}`),
  coverage: () => request("GET", "/meta/coverage"),
  catalogList: (params) => request("GET", `/catalog${qs(params)}`),
  catalogGet: (id) => request("GET", `/catalog/${encodeURIComponent(id)}`),
  execute: (body) => request("POST", "/execute", body),
  explain: (body) => request("POST", "/explain", body),
  benchmark: (body) => request("POST", "/benchmark", body),
  experimentsList: () => request("GET", "/experiments"),
  experimentRun: (id, body) => request("POST", `/experiments/${encodeURIComponent(id)}/run`, body),
};
