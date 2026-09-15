// "Структура БД" tab — SPEC.md §ФВ-11, backed entirely by GET
// /api/meta/schema. Each table is a collapsible card so a 30+-table
// database (dvdrental, once its dump is available) doesn't dump one huge
// wall of text.

import { api } from "./api.js";
import { el, clear, showError } from "./util.js";

export async function initSchemaTab() {
  const dbSelect = document.getElementById("schema-database");
  const treeEl = document.getElementById("schema-tree");

  await loadSchema();
  dbSelect.addEventListener("change", loadSchema);

  async function loadSchema() {
    treeEl.replaceChildren(el("div", { class: "muted", text: "Завантаження…" }));
    try {
      const schema = await api.schema(dbSelect.value);
      renderSchema(schema);
    } catch (err) {
      showError(treeEl, err);
    }
  }

  function renderSchema(schema) {
    clear(treeEl);
    if (!schema.tables.length) {
      treeEl.append(el("div", { class: "empty-state", text: "У цій базі ще немає таблиць у каталозі." }));
      return;
    }
    for (const table of schema.tables) {
      const body = el("div", { class: "schema-table-body" }, [
        el("h5", { text: "Стовпці" }),
        buildColumnsTable(table.columns),
        el("h5", { text: "Індекси" }),
        buildSimpleList(table.indexes, (i) => `${i.index_name}: ${i.definition}`),
        el("h5", { text: "Обмеження" }),
        buildSimpleList(table.constraints, (c) => `${c.constraint_name} (${c.constraint_type}): ${c.definition}`),
      ]);
      const header = el("div", { class: "schema-table-header" }, [
        `${table.schema}.${table.name}`,
        el("span", { class: "muted", text: `${table.columns.length} стовпців` }),
      ]);
      header.addEventListener("click", () => body.classList.toggle("open"));
      treeEl.append(el("div", { class: "schema-table-card" }, [header, body]));
    }
  }

  function buildColumnsTable(columns) {
    const header = el(
      "tr",
      {},
      ["Назва", "Тип", "NULL?", "За замовчуванням"].map((h) => el("th", { text: h }))
    );
    const rows = columns.map((c) =>
      el("tr", {}, [
        el("td", { text: c.column_name }),
        el("td", { text: c.data_type }),
        el("td", { text: c.is_nullable === "YES" ? "так" : "ні" }),
        el("td", { text: c.column_default || "" }),
      ])
    );
    return el("table", { class: "result-table" }, [el("thead", {}, [header]), el("tbody", {}, rows)]);
  }

  function buildSimpleList(items, formatter) {
    if (!items.length) return el("div", { class: "muted", text: "—" });
    return el("ul", {}, items.map((item) => el("li", { text: formatter(item) })));
  }
}
