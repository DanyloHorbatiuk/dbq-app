// Renders the flattened plan-node list from POST /api/explain as an
// indented tree (SPEC.md §ФВ-04: "дерево з кольоровим маркуванням частки
// часу"). `nodes` is already depth-first / pre-order (app.explain._flatten
// walks the plan tree that way), so a flat loop with depth-based indent
// reproduces the tree without any client-side tree-building.

import { el, formatNumber } from "./util.js";

export function renderPlanTree(container, explainResponse) {
  container.replaceChildren();
  const { nodes, planning_ms, execution_ms, plan_summary } = explainResponse;

  const summaryParts = [];
  if (planning_ms !== null && planning_ms !== undefined) {
    summaryParts.push(`Планування: ${formatNumber(planning_ms)} мс`);
  }
  if (execution_ms !== null && execution_ms !== undefined) {
    summaryParts.push(`Виконання: ${formatNumber(execution_ms)} мс`);
  }
  if (plan_summary.slowest_node) {
    const sn = plan_summary.slowest_node;
    summaryParts.push(`Найповільніший вузол: ${sn.node_type} (${formatNumber(sn.self_time_ms)} мс self time)`);
  }
  if (plan_summary.estimation_error !== null && plan_summary.estimation_error !== undefined) {
    summaryParts.push(`Максимальна похибка оцінки: ${formatNumber(plan_summary.estimation_error)}×`);
  }
  container.append(el("div", { class: "plan-summary-line", text: summaryParts.join("  •  ") }));

  const totalMs = execution_ms || Math.max(0, ...nodes.map((n) => n.self_time_ms || 0)) || 1;
  const tree = el("div", { class: "plan-tree" });

  for (const node of nodes) {
    const share =
      node.self_time_ms !== null && node.self_time_ms !== undefined
        ? Math.min(100, (node.self_time_ms / totalMs) * 100)
        : 0;
    const barWrap = el("div", { class: "plan-node-bar-wrap" }, [
      el("div", { class: "plan-node-bar", style: `width:${share}%` }),
    ]);

    const stats = [`оцінка: ${formatNumber(node.plan_rows)} рядк.`];
    if (node.actual_rows !== null && node.actual_rows !== undefined) {
      stats.push(`факт: ${formatNumber(node.actual_rows)} рядк.`);
    }
    if (node.actual_loops !== null && node.actual_loops !== undefined) {
      stats.push(`loops: ${node.actual_loops}`);
    }
    if (node.actual_total_time_ms !== null && node.actual_total_time_ms !== undefined) {
      stats.push(`total: ${formatNumber(node.actual_total_time_ms)} мс`);
    }
    if (node.self_time_ms !== null && node.self_time_ms !== undefined) {
      stats.push(`self: ${formatNumber(node.self_time_ms)} мс`);
    }
    if (node.estimation_error !== null && node.estimation_error !== undefined) {
      stats.push(`похибка: ${formatNumber(node.estimation_error)}×`);
    }

    const row = el("div", { class: `plan-node${node.misestimated ? " misestimated" : ""}` }, [
      el("span", {
        class: "plan-node-label",
        style: `padding-left:${node.depth * 18}px`,
        text: node.node_type,
      }),
      barWrap,
      el("span", { class: "plan-node-stats", text: stats.join(" · ") }),
      node.misestimated ? el("span", { class: "plan-node-flag", text: "⚠ похибка > 10×" }) : null,
    ]);
    tree.append(row);
  }
  container.append(tree);
}
