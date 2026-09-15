// "Каталог запитів" tab: sidebar tree with filters + query detail panel
// with Виконати / План / Бенчмарк, driving the shared result panel.

import { api } from "./api.js";
import { el, clear, showError } from "./util.js";
import { createResultPanel } from "./results.js";

export async function initCatalogTab() {
  const dbSelect = document.getElementById("filter-database");
  const levelSelect = document.getElementById("filter-level");
  const featureSelect = document.getElementById("filter-feature");
  const searchInput = document.getElementById("filter-search");
  const tree = document.getElementById("catalog-tree");

  const emptyState = document.getElementById("query-empty");
  const detail = document.getElementById("query-detail");
  const titleEl = document.getElementById("query-title");
  const bqEl = document.getElementById("query-business-question");
  const descEl = document.getElementById("query-description");
  const insightEl = document.getElementById("query-expected-insight");
  const featuresEl = document.getElementById("query-features");
  const variantLabel = document.getElementById("variant-label");
  const variantSelect = document.getElementById("query-variant");
  const paramsEl = document.getElementById("query-parameters");
  const sqlEl = document.getElementById("query-sql");
  const btnExecute = document.getElementById("btn-execute");
  const btnPlan = document.getElementById("btn-plan");
  const btnBenchmark = document.getElementById("btn-benchmark");
  const resultContainer = document.getElementById("query-result");

  const resultPanel = createResultPanel(resultContainer);

  let currentEntry = null;
  let selectedId = null;

  await populateFeatureOptions();
  await loadTree();

  dbSelect.addEventListener("change", loadTree);
  levelSelect.addEventListener("change", loadTree);
  featureSelect.addEventListener("change", loadTree);
  let searchTimer = null;
  searchInput.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(loadTree, 250);
  });

  async function populateFeatureOptions() {
    try {
      const coverage = await api.coverage();
      const features = new Set();
      for (const level of Object.values(coverage.by_level)) {
        for (const feature of Object.keys(level.counts)) features.add(feature);
      }
      for (const feature of Array.from(features).sort()) {
        featureSelect.append(el("option", { value: feature, text: feature }));
      }
    } catch {
      // Coverage is a convenience filter, not essential — leave the
      // "усі" option only if this fails rather than blocking the tab.
    }
  }

  async function loadTree() {
    tree.replaceChildren(el("div", { class: "muted", text: "Завантаження…" }));
    try {
      const entries = await api.catalogList({
        database: dbSelect.value,
        level: levelSelect.value || undefined,
        feature: featureSelect.value || undefined,
        q: searchInput.value || undefined,
      });
      renderTree(entries);
    } catch (err) {
      showError(tree, err);
    }
  }

  function renderTree(entries) {
    tree.replaceChildren();
    if (!entries.length) {
      tree.append(el("div", { class: "empty-state", text: "Немає запитів за цим фільтром." }));
      return;
    }
    const byLevel = new Map();
    for (const entry of entries) {
      if (!byLevel.has(entry.level)) byLevel.set(entry.level, []);
      byLevel.get(entry.level).push(entry);
    }
    for (const level of Array.from(byLevel.keys()).sort()) {
      const group = el("div", { class: "level-group" }, [
        el("div", { class: "level-heading", text: `Рівень ${level}` }),
      ]);
      for (const entry of byLevel.get(level)) {
        const btn = el(
          "button",
          {
            class: `catalog-item${entry.id === selectedId ? " selected" : ""}`,
            "data-query-id": entry.id,
            onclick: () => selectQuery(entry.id),
          },
          [entry.title, el("span", { class: "item-id", text: entry.id })]
        );
        group.append(btn);
      }
      tree.append(group);
    }
  }

  async function selectQuery(id) {
    selectedId = id;
    Array.from(tree.querySelectorAll(".catalog-item")).forEach((b) =>
      b.classList.toggle("selected", b.dataset.queryId === id)
    );
    try {
      currentEntry = await api.catalogGet(id);
    } catch (err) {
      emptyState.hidden = true;
      detail.hidden = false;
      showError(detail, err);
      return;
    }
    renderDetail();
  }

  function renderDetail() {
    const entry = currentEntry;
    emptyState.hidden = true;
    detail.hidden = false;

    titleEl.textContent = entry.title;
    bqEl.textContent = entry.business_question;
    descEl.textContent = entry.description || "";
    descEl.hidden = !entry.description;
    insightEl.textContent = entry.expected_insight ? `Очікуваний інсайт: ${entry.expected_insight}` : "";
    insightEl.hidden = !entry.expected_insight;

    clear(featuresEl);
    for (const f of entry.sql_features) featuresEl.append(el("span", { class: "badge", text: f }));

    clear(variantSelect);
    if (entry.variants && entry.variants.length) {
      variantLabel.hidden = false;
      variantSelect.append(el("option", { value: "", text: "Основне формулювання" }));
      entry.variants.forEach((v, i) => {
        variantSelect.append(el("option", { value: i, text: v.label }));
      });
      variantSelect.onchange = updateSqlText;
    } else {
      variantLabel.hidden = true;
    }

    clear(paramsEl);
    if (entry.parameters && entry.parameters.length) {
      for (const p of entry.parameters) {
        const inputType = p.type === "number" ? "number" : p.type === "date" ? "date" : "text";
        const input = el("input", {
          type: inputType,
          "data-param": p.name,
          value: p.default !== null && p.default !== undefined ? p.default : "",
        });
        paramsEl.append(el("label", {}, [p.name, input]));
      }
    }

    updateSqlText();
    resultPanel.reset();

    btnExecute.onclick = () => runExecute();
    btnPlan.onclick = () => runPlan();
    btnBenchmark.onclick = () => runBenchmark();
  }

  function updateSqlText() {
    const idx = variantSelect.value === "" ? null : Number(variantSelect.value);
    sqlEl.textContent = idx === null ? currentEntry.sql : currentEntry.variants[idx].sql;
  }

  function currentVariant() {
    return variantSelect.value === "" ? null : Number(variantSelect.value);
  }

  function currentParameters() {
    const params = {};
    for (const input of paramsEl.querySelectorAll("[data-param]")) {
      const name = input.dataset.param;
      params[name] = input.type === "number" ? Number(input.value) : input.value;
    }
    return params;
  }

  async function runExecute() {
    setBusy(true);
    try {
      const response = await api.execute({
        query_id: currentEntry.id,
        variant: currentVariant(),
        parameters: currentParameters(),
      });
      resultPanel.showTable(response, currentEntry.chart);
    } catch (err) {
      resultPanel.showErrorIn("table", err);
    } finally {
      setBusy(false);
    }
  }

  async function runPlan() {
    setBusy(true);
    try {
      const response = await api.explain({
        query_id: currentEntry.id,
        variant: currentVariant(),
        parameters: currentParameters(),
        analyze: true,
        buffers: true,
      });
      resultPanel.showPlan(response);
    } catch (err) {
      resultPanel.showErrorIn("plan", err);
    } finally {
      setBusy(false);
    }
  }

  async function runBenchmark() {
    setBusy(true);
    try {
      const response = await api.benchmark({
        query_id: currentEntry.id,
        variant: currentVariant(),
        parameters: currentParameters(),
      });
      resultPanel.showBenchmark(response);
    } catch (err) {
      resultPanel.showErrorIn("bench", err);
    } finally {
      setBusy(false);
    }
  }

  function setBusy(busy) {
    btnExecute.disabled = busy;
    btnPlan.disabled = busy;
    btnBenchmark.disabled = busy;
  }
}
