// Entry point: top-level tab switching + header badges, then hands off to
// each tab's own module. No bundler/build step (CLAUDE.md) — this is a
// plain ES module graph the browser resolves natively via <script type="module">.

import { api } from "./api.js";
import { el } from "./util.js";
import { initCatalogTab } from "./catalog.js";
import { initSqlConsoleTab } from "./sql-console.js";
import { initExperimentsTab } from "./experiments.js";
import { initSchemaTab } from "./schema.js";

function initTabs() {
  const buttons = Array.from(document.querySelectorAll(".tab-btn"));
  const panels = Array.from(document.querySelectorAll(".tab-panel"));
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.toggle("active", b === btn));
      panels.forEach((p) => p.classList.toggle("active", p.id === `tab-${btn.dataset.tab}`));
    });
  });
}

async function initHeader() {
  const badges = document.getElementById("header-badges");
  try {
    const [coverage, info] = await Promise.all([api.coverage(), api.serverInfo()]);
    const pct = coverage.coverage_pct;
    badges.append(
      el("span", {
        class: `badge ${pct >= 100 ? "badge-ok" : "badge-warn"}`,
        text: `Покриття SQL: ${pct}% (${coverage.covered_features}/${coverage.total_features})`,
      }),
      el("span", { class: "badge", text: `PostgreSQL ${info.server_version}` })
    );
  } catch {
    badges.append(el("span", { class: "badge badge-warn", text: "Не вдалося отримати метадані сервера" }));
  }
}

initTabs();
initHeader();
initCatalogTab();
initSqlConsoleTab();
initExperimentsTab();
initSchemaTab();
