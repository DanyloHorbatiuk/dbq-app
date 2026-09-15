import { ApiError } from "./api.js";

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2), value);
    } else if (value !== undefined && value !== null) {
      node.setAttribute(key, value);
    }
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

// Renders whatever the backend sent as an error into one readable string.
// DB errors arrive as {sqlstate, message, position}; validation errors as
// a plain string or a FastAPI/Pydantic array of {loc, msg} objects.
export function formatError(err) {
  if (!(err instanceof ApiError)) return String(err && err.message ? err.message : err);
  const d = err.detail;
  if (typeof d === "string") return d;
  if (d && typeof d === "object" && "sqlstate" in d) {
    const pos = d.position !== null && d.position !== undefined ? `, позиція ${d.position}` : "";
    return `[${d.sqlstate}] ${d.message}${pos}`;
  }
  if (Array.isArray(d)) {
    return d.map((item) => item.msg || JSON.stringify(item)).join("; ");
  }
  return JSON.stringify(d);
}

export function showError(container, err) {
  container.replaceChildren(el("div", { class: "error-box", text: formatError(err) }));
}

export function clear(node) {
  node.replaceChildren();
}

export function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: filename });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function exportRowsAsCsv(filename, columns, rows) {
  const escapeCell = (value) => {
    if (value === null || value === undefined) return "";
    const s = String(value);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map((c) => escapeCell(c.name)).join(",")];
  for (const row of rows) lines.push(row.map(escapeCell).join(","));
  // UTF-8 BOM so Excel doesn't mangle Cyrillic text (CLAUDE.md: UI text is Ukrainian).
  const blob = new Blob(["﻿" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  downloadBlob(filename, blob);
}

export function formatCell(value) {
  if (value === null || value === undefined) return { text: "NULL", isNull: true };
  if (typeof value === "number") return { text: formatNumber(value), isNull: false };
  return { text: String(value), isNull: false };
}

export function formatNumber(n) {
  if (!Number.isFinite(n)) return String(n);
  if (Number.isInteger(n)) return n.toLocaleString("uk-UA");
  return n.toLocaleString("uk-UA", { maximumFractionDigits: 3 });
}
