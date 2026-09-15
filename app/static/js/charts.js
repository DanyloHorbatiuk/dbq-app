// Chart rendering for the "Діаграма" result tab (SPEC.md §ФВ-09). Chart.js
// itself is loaded globally from the CDN <script> tag in index.html.

const PALETTE = ["#2563eb", "#16a34a", "#d97706", "#dc2626", "#7c3aed", "#0891b2"];

function columnIndex(columns, name) {
  return columns.findIndex((c) => c.name === name);
}

function isNumericColumn(rows, idx) {
  for (const row of rows) {
    const v = row[idx];
    if (v !== null && v !== undefined) return typeof v === "number";
  }
  return false;
}

// Picks x/y columns and a chart type. A catalog `chart` hint wins when its
// columns are actually present in the result; otherwise falls back to the
// heuristic from SPEC.md §ФВ-09: first non-numeric column is X, numeric
// columns are series, and a single numeric column with <=10 rows becomes a
// pie chart instead of a bar.
export function resolveChartPlan(columns, rows, hint) {
  if (!rows.length) return null;

  if (hint && hint.type && hint.type !== "none") {
    const xIdx = hint.x ? columnIndex(columns, hint.x) : -1;
    const yIdxs = (hint.y || []).map((name) => columnIndex(columns, name)).filter((i) => i >= 0);
    if (yIdxs.length && (hint.x ? xIdx >= 0 : true)) {
      return {
        type: hint.type,
        xIdx: xIdx >= 0 ? xIdx : 0,
        yIdxs,
        yLabels: yIdxs.map((i) => columns[i].name),
      };
    }
  }

  const numericFlags = columns.map((_, i) => isNumericColumn(rows, i));
  const xIdx = numericFlags.findIndex((isNum) => !isNum);
  const resolvedX = xIdx >= 0 ? xIdx : 0;
  const yIdxs = columns.map((_, i) => i).filter((i) => numericFlags[i] && i !== resolvedX);
  if (!yIdxs.length) return null;

  if (yIdxs.length === 1 && rows.length <= 10) {
    return { type: "pie", xIdx: resolvedX, yIdxs: [yIdxs[0]], yLabels: [columns[yIdxs[0]].name] };
  }
  return { type: "bar", xIdx: resolvedX, yIdxs, yLabels: yIdxs.map((i) => columns[i].name) };
}

export function buildChartData(plan, rows) {
  const labels = rows.map((row) => String(row[plan.xIdx] ?? ""));
  if (plan.type === "pie") {
    return {
      labels,
      datasets: [
        {
          data: rows.map((row) => Number(row[plan.yIdxs[0]] ?? 0)),
          backgroundColor: labels.map((_, i) => PALETTE[i % PALETTE.length]),
        },
      ],
    };
  }
  return {
    labels,
    datasets: plan.yIdxs.map((idx, i) => ({
      label: plan.yLabels[i],
      data: rows.map((row) => Number(row[idx] ?? 0)),
      backgroundColor: PALETTE[i % PALETTE.length],
      borderColor: PALETTE[i % PALETTE.length],
      fill: plan.type === "line" ? false : undefined,
    })),
  };
}

// Destroys `prevChart` (if any) and draws a fresh one — Chart.js requires
// a clean teardown before reusing the same <canvas>, and result panels get
// re-rendered whenever the user reruns a query or switches chart type.
export function renderChartFromPlan(canvas, prevChart, rows, plan) {
  if (prevChart) prevChart.destroy();
  if (!plan) return null;
  const chartType = plan.type === "pie" ? "pie" : plan.type === "line" ? "line" : plan.type === "scatter" ? "scatter" : "bar";
  const data = buildChartData(plan, rows);
  return new Chart(canvas, {
    type: chartType,
    data,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: chartType === "pie" ? {} : { y: { beginAtZero: true } },
    },
  });
}
