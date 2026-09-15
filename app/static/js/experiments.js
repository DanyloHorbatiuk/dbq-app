// "Експерименти з індексами" tab — SPEC.md §ФВ-06/§ФВ-07. Each card is one
// experiments/*.yaml entry; running it drives the full before/after (or
// view/matview) scenario server-side and returns both benchmark snapshots
// plus the plan's scan-node type, which is exactly what needs to change
// (Seq Scan -> Index Scan) for the ROADMAP.md demo scenario to land.

import { api } from "./api.js";
import { el, clear, showError, formatNumber } from "./util.js";

export async function initExperimentsTab() {
  const listEl = document.getElementById("experiments-list");
  const resultEl = document.getElementById("experiment-result");
  let currentChart = null;

  await loadList();

  async function loadList() {
    listEl.replaceChildren(el("div", { class: "muted", text: "Завантаження…" }));
    try {
      const experiments = await api.experimentsList();
      renderList(experiments);
    } catch (err) {
      showError(listEl, err);
    }
  }

  function renderList(experiments) {
    clear(listEl);
    if (!experiments.length) {
      listEl.append(el("div", { class: "empty-state", text: "Немає описаних експериментів." }));
      return;
    }
    for (const exp of experiments) {
      const keepInput = exp.kind === "index" ? el("input", { type: "checkbox" }) : null;
      const keepLabel = keepInput ? el("label", {}, [keepInput, " зберегти індекс"]) : null;
      const runBtn = el("button", { class: "primary small", text: "Запустити" });
      const kindLabel = exp.kind === "index" ? "індекс" : "VIEW / MATERIALIZED VIEW";
      const card = el("div", { class: "experiment-card" }, [
        el("h3", { text: exp.title }),
        el("span", {
          class: "muted",
          text: `${exp.database} · ${kindLabel}${exp.description ? " — " + exp.description : ""}`,
        }),
        el("div", { class: "run-row" }, [runBtn, keepLabel]),
      ]);
      runBtn.addEventListener("click", () => runExperiment(exp, runBtn, keepInput));
      listEl.append(card);
    }
  }

  async function runExperiment(exp, runBtn, keepInput) {
    runBtn.disabled = true;
    runBtn.textContent = "Виконується…";
    resultEl.replaceChildren(
      el("div", { class: "muted", text: "Виконання експерименту (кілька прогонів бенчмарку до і після) — це займе трохи часу…" })
    );
    try {
      const result = await api.experimentRun(exp.id, { keep_index: keepInput ? keepInput.checked : false });
      renderResult(result);
    } catch (err) {
      showError(resultEl, err);
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = "Запустити";
    }
  }

  function renderResult(result) {
    clear(resultEl);
    if (currentChart) {
      currentChart.destroy();
      currentChart = null;
    }
    const isIndex = "index_name" in result;
    resultEl.append(el("h3", { text: result.title }));

    if (isIndex) {
      resultEl.append(
        el("div", {
          class: "meta-line",
          text:
            `Індекс: ${result.index_name} · розмір: ${result.index_size} · ` +
            `час створення: ${formatNumber(result.create_index_ms)} мс · ` +
            `${result.kept_index ? "залишено в базі" : "видалено після експерименту"}`,
        }),
        el("div", {
          class: "meta-line",
          text: `Тип доступу в плані: ${result.before.scan_node_type || "?"} → ${result.after.scan_node_type || "?"}`,
        })
      );
      buildSnapshotPair(result.before, result.after, "без індексу", "з індексом");
    } else {
      resultEl.append(
        el("div", {
          class: "meta-line",
          text: `REFRESH MATERIALIZED VIEW: ${formatNumber(result.refresh_ms)} мс · розмір matview: ${result.matview_size}`,
        })
      );
      buildSnapshotPair(result.view, result.matview, "VIEW", "MATERIALIZED VIEW");
    }
  }

  function buildSnapshotPair(before, after, beforeLabel, afterLabel) {
    const canvas = el("canvas");
    resultEl.append(el("div", { class: "chart-wrap" }, [canvas]));
    currentChart = new Chart(canvas, {
      type: "bar",
      data: {
        labels: ["min", "медіана", "mean", "p95", "max"],
        datasets: [
          {
            label: beforeLabel,
            data: [before.stats.min_ms, before.stats.median_ms, before.stats.mean_ms, before.stats.p95_ms, before.stats.max_ms],
            backgroundColor: "#d97706",
          },
          {
            label: afterLabel,
            data: [after.stats.min_ms, after.stats.median_ms, after.stats.mean_ms, after.stats.p95_ms, after.stats.max_ms],
            backgroundColor: "#16a34a",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { beginAtZero: true, title: { display: true, text: "мс" } } },
      },
    });

    resultEl.append(
      el("div", { class: "snapshot-pair" }, [
        buildSnapshotCol(beforeLabel, before),
        buildSnapshotCol(afterLabel, after),
      ])
    );
  }

  function buildSnapshotCol(label, snapshot) {
    const s = snapshot.stats;
    return el("div", { class: "snapshot-col" }, [
      el("h4", { text: label }),
      el("div", {
        class: "muted",
        text: `медіана: ${formatNumber(s.median_ms)} мс · min: ${formatNumber(s.min_ms)} мс · p95: ${formatNumber(s.p95_ms)} мс`,
      }),
      el("div", { class: "muted", text: `вузол доступу: ${snapshot.scan_node_type || "—"}` }),
      el("details", {}, [
        el("summary", { text: "JSON плану (EXPLAIN)" }),
        el("pre", { class: "sql-block", text: JSON.stringify(snapshot.plan, null, 2) }),
      ]),
    ]);
  }
}
