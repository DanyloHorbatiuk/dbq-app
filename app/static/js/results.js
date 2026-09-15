// The result panel shared by the catalog tab and the "Довільний SQL" tab:
// four subtabs (Таблиця / Діаграма / План / Статистика часу) fed by
// POST /api/execute, /api/explain and /api/benchmark respectively — kept
// as three separate calls rather than execute's with_plan flag, matching
// ROADMAP.md Etap 11's three distinct buttons (Виконати / План / Бенчмарк).

import { el, formatCell, formatNumber, exportRowsAsCsv, showError } from "./util.js";
import { resolveChartPlan, renderChartFromPlan } from "./charts.js";
import { renderPlanTree } from "./plan.js";

export function createResultPanel(container) {
  container.replaceChildren();

  const tableContent = el("div", { class: "result-tab-content active" });
  const chartContent = el("div", { class: "result-tab-content" });
  const planContent = el("div", { class: "result-tab-content" });
  const benchContent = el("div", { class: "result-tab-content" });

  const tabDefs = [
    ["table", "Таблиця", tableContent],
    ["chart", "Діаграма", chartContent],
    ["plan", "План", planContent],
    ["bench", "Статистика часу", benchContent],
  ];
  const buttons = {};
  const contents = {};
  const tabsBar = el(
    "div",
    { class: "result-tabs" },
    tabDefs.map(([key, label, content], i) => {
      const btn = el("button", {
        class: `result-tab-btn${i === 0 ? " active" : ""}`,
        text: label,
        onclick: () => showTab(key),
      });
      buttons[key] = btn;
      contents[key] = content;
      return btn;
    })
  );

  container.append(tabsBar, tableContent, chartContent, planContent, benchContent);

  function showTab(name) {
    for (const key of Object.keys(buttons)) {
      buttons[key].classList.toggle("active", key === name);
      contents[key].classList.toggle("active", key === name);
    }
  }

  let currentChart = null;
  let currentBenchChart = null;
  let currentColumns = [];
  let currentRows = [];
  let currentHint = null;

  function reset() {
    tableContent.replaceChildren(
      el("div", { class: "empty-state", text: "Натисніть «Виконати», щоб побачити результат." })
    );
    chartContent.replaceChildren();
    planContent.replaceChildren(
      el("div", { class: "empty-state", text: "Натисніть «План», щоб побачити план виконання." })
    );
    benchContent.replaceChildren(
      el("div", { class: "empty-state", text: "Натисніть «Бенчмарк», щоб виміряти продуктивність." })
    );
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
    if (currentBenchChart) {
      currentBenchChart.destroy();
      currentBenchChart = null;
    }
    showTab("table");
  }
  reset();

  function showTable(execResponse, hint) {
    currentColumns = execResponse.columns;
    currentRows = execResponse.rows;
    currentHint = hint || null;
    renderTable(execResponse.row_count, execResponse.truncated);
    // A rendering bug (or Chart.js failing to load) must not take the
    // already-rendered table down with it — the caller's try/catch around
    // showTable() only expects to handle *request* failures.
    try {
      renderChartTab();
    } catch (err) {
      chartContent.replaceChildren(el("div", { class: "error-box", text: `Не вдалося побудувати діаграму: ${err}` }));
    }
    showTab("table");
  }

  function renderTable(rowCount, truncated) {
    tableContent.replaceChildren();
    const meta = el("div", {
      class: "meta-line",
      text: `Рядків: ${rowCount}${truncated ? " (результат обрізано за лімітом)" : ""}`,
    });
    const exportBtn = el("button", {
      class: "small",
      text: "Експорт CSV",
      onclick: () => exportRowsAsCsv("result.csv", currentColumns, currentRows),
    });
    const header = el(
      "tr",
      {},
      currentColumns.map((c) => el("th", { text: `${c.name} (${c.type})` }))
    );
    const bodyRows = currentRows.map((row) =>
      el(
        "tr",
        {},
        row.map((v) => {
          const { text, isNull } = formatCell(v);
          return el("td", { class: isNull ? "null-value" : undefined, title: text, text });
        })
      )
    );
    const table = el("table", { class: "result-table" }, [
      el("thead", {}, [header]),
      el("tbody", {}, bodyRows),
    ]);
    tableContent.append(
      el("div", { class: "action-row" }, [meta, exportBtn]),
      el("div", { class: "table-scroll" }, [table])
    );
  }

  function renderChartTab() {
    chartContent.replaceChildren();
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
    if (!currentRows.length) {
      chartContent.append(el("div", { class: "empty-state", text: "Немає даних для діаграми." }));
      return;
    }

    let plan = resolveChartPlan(currentColumns, currentRows, currentHint) || {
      type: "bar",
      xIdx: 0,
      yIdxs: [],
      yLabels: [],
    };

    const typeSelect = el(
      "select",
      { onchange: () => { plan = { ...plan, type: typeSelect.value }; redraw(); } },
      ["bar", "line", "pie", "scatter"].map((t) =>
        el("option", { value: t, selected: plan.type === t ? "" : undefined, text: t })
      )
    );
    const xSelect = el(
      "select",
      { onchange: () => { plan = { ...plan, xIdx: Number(xSelect.value) }; redraw(); } },
      currentColumns.map((c, i) =>
        el("option", { value: i, selected: plan.xIdx === i ? "" : undefined, text: c.name })
      )
    );
    const ySelect = el(
      "select",
      {
        multiple: "",
        size: Math.min(6, currentColumns.length),
        onchange: () => {
          const idxs = Array.from(ySelect.selectedOptions).map((o) => Number(o.value));
          plan = { ...plan, yIdxs: idxs, yLabels: idxs.map((i) => currentColumns[i].name) };
          redraw();
        },
      },
      currentColumns.map((c, i) =>
        el("option", { value: i, selected: plan.yIdxs.includes(i) ? "" : undefined, text: c.name })
      )
    );
    const exportPngBtn = el("button", {
      class: "small",
      text: "Зберегти PNG",
      onclick: () => {
        if (!currentChart) return;
        const a = el("a", { href: currentChart.toBase64Image(), download: "chart.png" });
        document.body.append(a);
        a.click();
        a.remove();
      },
    });

    const canvas = el("canvas");
    chartContent.append(
      el("div", { class: "chart-controls" }, [
        el("label", {}, ["Тип", typeSelect]),
        el("label", {}, ["Вісь X", xSelect]),
        el("label", {}, ["Серії Y", ySelect]),
        exportPngBtn,
      ]),
      el("div", { class: "chart-wrap" }, [canvas])
    );

    function redraw() {
      currentChart = renderChartFromPlan(canvas, currentChart, currentRows, plan);
    }
    if (plan.yIdxs.length) redraw();
  }

  function showPlan(explainResponse) {
    renderPlanTree(planContent, explainResponse);
    showTab("plan");
  }

  function showBenchmark(benchResponse) {
    benchContent.replaceChildren();
    if (currentBenchChart) {
      currentBenchChart.destroy();
      currentBenchChart = null;
    }
    const s = benchResponse.stats;
    const row = (label, value) => el("tr", {}, [el("th", { text: label }), el("td", { text: value })]);
    const statsTable = el("table", { class: "bench-stats-table" }, [
      row("Прогонів (без холодного)", String(benchResponse.runs)),
      row("Холодний прогін", `${formatNumber(benchResponse.cold_run_ms)} мс`),
      row("min", `${formatNumber(s.min_ms)} мс`),
      row("медіана", `${formatNumber(s.median_ms)} мс`),
      row("mean", `${formatNumber(s.mean_ms)} мс`),
      row("p95", `${formatNumber(s.p95_ms)} мс`),
      row("max", `${formatNumber(s.max_ms)} мс`),
      row("stddev", `${formatNumber(s.stddev_ms)} мс`),
    ]);

    const env = benchResponse.environment;
    const envLines = [
      `PostgreSQL ${env.server_version}`,
      `shared_buffers=${env.shared_buffers}`,
      `work_mem=${env.work_mem}`,
      `random_page_cost=${env.random_page_cost}`,
      ...Object.entries(env.table_sizes).map(([t, size]) => `${t}: ${size}`),
    ];
    const envBox = el("div", { class: "meta-line", text: envLines.join("  ·  ") });

    const canvas = el("canvas");
    benchContent.append(statsTable, envBox, el("div", { class: "chart-wrap" }, [canvas]));
    try {
      currentBenchChart = buildSamplesChart(canvas, benchResponse);
    } catch (err) {
      benchContent.append(el("div", { class: "error-box", text: `Не вдалося побудувати діаграму: ${err}` }));
    }
    showTab("bench");
  }

  function buildSamplesChart(canvas, benchResponse) {
    return new Chart(canvas, {
      type: "bar",
      data: {
        labels: benchResponse.samples_ms.map((_, i) => `#${i + 1}`),
        datasets: [{ label: "тривалість, мс", data: benchResponse.samples_ms, backgroundColor: "#2563eb" }],
      },
      options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } },
    });
  }

  function showErrorIn(tabName, err) {
    showError(contents[tabName], err);
    showTab(tabName);
  }

  return { reset, showTable, showPlan, showBenchmark, showErrorIn };
}
