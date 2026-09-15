// "Довільний SQL" tab (SPEC.md §ФВ-03) — same three actions and the same
// result panel as the catalog tab, but sends raw sql + database instead of
// a query_id. Rejections (wrong statement, more than one statement, write
// keyword, …) come back as HTTP 400 and are shown as-is, not swallowed.

import { api } from "./api.js";
import { createResultPanel } from "./results.js";

export function initSqlConsoleTab() {
  const dbSelect = document.getElementById("sql-database");
  const sqlText = document.getElementById("sql-text");
  const btnExecute = document.getElementById("sql-btn-execute");
  const btnPlan = document.getElementById("sql-btn-plan");
  const btnBenchmark = document.getElementById("sql-btn-benchmark");
  const resultContainer = document.getElementById("sql-result");

  const resultPanel = createResultPanel(resultContainer);

  function baseRequest() {
    return { sql: sqlText.value, database: dbSelect.value };
  }

  function setBusy(busy) {
    btnExecute.disabled = busy;
    btnPlan.disabled = busy;
    btnBenchmark.disabled = busy;
  }

  btnExecute.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await api.execute(baseRequest());
      resultPanel.showTable(response, null);
    } catch (err) {
      resultPanel.showErrorIn("table", err);
    } finally {
      setBusy(false);
    }
  });

  btnPlan.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await api.explain({ ...baseRequest(), analyze: true, buffers: true });
      resultPanel.showPlan(response);
    } catch (err) {
      resultPanel.showErrorIn("plan", err);
    } finally {
      setBusy(false);
    }
  });

  btnBenchmark.addEventListener("click", async () => {
    setBusy(true);
    try {
      const response = await api.benchmark(baseRequest());
      resultPanel.showBenchmark(response);
    } catch (err) {
      resultPanel.showErrorIn("bench", err);
    } finally {
      setBusy(false);
    }
  });
}
