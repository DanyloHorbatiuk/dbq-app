-- =============================================================================
-- museum_network — views (SPEC.md §2.2.5) and the museum_manager role's
-- grants.
--
-- Role/grant wiring for museum_manager lands in this file rather than a
-- separate file: this schema's build order only defines files through
-- Etap 2 (03_functions.sql / 04_views.sql / 05_triggers.sql), and putting
-- the grants here — after every table (Etap 1) and view/matview (this
-- file) exists — means one GRANT ON ALL TABLES IN SCHEMA covers both in a
-- single rerunnable statement, with nothing left for a later stage to
-- remember. The role itself (CREATE ROLE, with its password) is created
-- separately in docker/postgres/initdb/10_roles.sh, because it needs an
-- env var, not something that belongs in a committed SQL file.
-- =============================================================================

--------------------------------------------------------------------------------
-- v_quarterly_sales_performance — kept from legacy_schema.sql (SPEC.md
-- §2.2.5 says "зберегти"), but the aggregation is adapted: tickets.quantity
-- now means one row can represent more than one admission, so both the
-- ticket count and the revenue sum have to account for it instead of
-- treating every row as exactly one ticket at its listed price.
--------------------------------------------------------------------------------
CREATE OR REPLACE VIEW museum_network.v_quarterly_sales_performance AS
SELECT
    e.name AS exhibition_title,
    tp.visitor_type AS category,
    SUM(t.quantity) AS total_tickets_sold,
    SUM(tp.price * t.quantity) AS total_revenue,
    MIN(t.purchase_date)::DATE AS period_start,
    MAX(t.purchase_date)::DATE AS period_end
FROM museum_network.tickets t
JOIN museum_network.ticket_prices tp ON t.price_id = tp.price_id
JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id
WHERE t.purchase_date >= DATE_TRUNC('quarter', CURRENT_DATE)
GROUP BY e.name, tp.visitor_type
ORDER BY total_revenue DESC;

--------------------------------------------------------------------------------
-- mv_monthly_revenue — new (SPEC.md §2.2.5): monthly revenue by exhibition
-- and visitor category. A unique index on the grouping columns is required
-- for REFRESH MATERIALIZED VIEW CONCURRENTLY (§ФВ-07's VIEW-vs-MATERIALIZED
-- VIEW benchmark needs the refresh to not block concurrent reads).
--
-- No DROP MATERIALIZED VIEW / CREATE OR REPLACE exists for matviews in
-- PostgreSQL, so rerunnability here means dropping it first.
--------------------------------------------------------------------------------
DROP MATERIALIZED VIEW IF EXISTS museum_network.mv_monthly_revenue;

CREATE MATERIALIZED VIEW museum_network.mv_monthly_revenue AS
SELECT
    e.exhibition_id,
    e.name AS exhibition_title,
    tp.visitor_type,
    DATE_TRUNC('month', t.purchase_date)::DATE AS revenue_month,
    SUM(t.quantity) AS tickets_sold,
    SUM(tp.price * t.quantity) AS revenue
FROM museum_network.tickets t
JOIN museum_network.ticket_prices tp ON t.price_id = tp.price_id
JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id
GROUP BY e.exhibition_id, e.name, tp.visitor_type, DATE_TRUNC('month', t.purchase_date);

CREATE UNIQUE INDEX ux_mv_monthly_revenue
    ON museum_network.mv_monthly_revenue (exhibition_id, visitor_type, revenue_month);

--------------------------------------------------------------------------------
-- museum_manager grants — SELECT-only, matching legacy_schema.sql's Task 7
-- intent. "ALL TABLES IN SCHEMA" also covers views and materialized views
-- in PostgreSQL, so this one GRANT is enough for both of the above plus
-- every Etap 1 table. ALTER DEFAULT PRIVILEGES covers objects the later
-- stages (06_seed_reference.sql etc.) still add.
--------------------------------------------------------------------------------
GRANT USAGE ON SCHEMA museum_network TO museum_manager;
GRANT SELECT ON ALL TABLES IN SCHEMA museum_network TO museum_manager;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA museum_network TO museum_manager;

-- FOR ROLE is omitted deliberately: 40_init_museum.sh runs this file
-- connected as saw_admin, and ALTER DEFAULT PRIVILEGES defaults to "the
-- role executing this statement" when FOR ROLE is left out — so this stays
-- correct even if SAW_ADMIN_USER is renamed via .env.
ALTER DEFAULT PRIVILEGES IN SCHEMA museum_network
    GRANT SELECT ON TABLES TO museum_manager;
