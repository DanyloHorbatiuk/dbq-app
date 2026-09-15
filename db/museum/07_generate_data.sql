-- =============================================================================
-- museum_network — bulk data generator (SPEC.md §2.2.6).
--
-- Design note used throughout this file: every table below was just
-- TRUNCATEd with RESTART IDENTITY by 06_seed_reference.sql (or, on a full
-- `make reset`, freshly created by 01_schema.sql), so IDENTITY primary keys
-- are contiguous integers starting at 1 with no gaps. That's what makes
-- "pick a uniformly random related row" as cheap as generating a random
-- integer in [1, N] instead of an array/rank lookup — used below for halls
-- (20), exhibits (5000). Where selection needs to be *skewed* rather than
-- uniform (popular exhibitions, active staff), a small helper temp table
-- maps id -> rank, and a skewed random index (power(random(), k), k > 1,
-- biases toward rank 1) is looked up against an array ordered by that
-- rank — the same technique reused for every "long tail" requirement in
-- SPEC.md §2.2.6, instead of a different trick per table.
--
-- Every INSERT here is a single INSERT ... SELECT ... FROM generate_series
-- statement (CLAUDE.md: no PL/pgSQL loop) — the 300k+ tickets requirement
-- is what makes that a hard requirement, not just a style preference.
-- =============================================================================

SELECT setseed(0.42);

DROP TABLE IF EXISTS
    tmp_exhibition_popularity, tmp_exhibition_by_rank, tmp_cashiers_by_rank,
    tmp_guides_by_rank, tmp_restorers, tmp_price_pool, tmp_prices_by_exhibition,
    tmp_cashier_array, tmp_guide_array, tmp_month_weights, tmp_ticket_exhibition,
    tmp_tickets_by_exhibition, tmp_ticket_candidates, tmp_ticket_dated;

--------------------------------------------------------------------------------
-- Exhibitions (400): 20 per hall, laid out back-to-back from 2019-01-01
-- with a random duration (20-119 days) and gap (3-37 days) before the next
-- one in the same hall. Computing each start as a running cumulative sum
-- (window function) guarantees no two exhibitions in the same hall ever
-- overlap, satisfying excl_exhibitions_hall_period by construction — no
-- loop, no retry-on-conflict needed.
--------------------------------------------------------------------------------
WITH exhibition_slots AS (
    SELECT
        h.hall_id,
        gs AS seq,
        20 + floor(random() * 100)::int AS duration_days,
        3 + floor(random() * 35)::int AS gap_days
    FROM museum_network.halls h
    CROSS JOIN generate_series(1, 20) AS gs
),
exhibition_dates AS (
    SELECT
        hall_id,
        seq,
        duration_days,
        DATE '2019-01-01'
            + COALESCE(SUM(duration_days + gap_days) OVER (
                  PARTITION BY hall_id ORDER BY seq
                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
              ), 0)::int AS start_date
    FROM exhibition_slots
),
themes AS (
    SELECT ARRAY[
        'Treasures of Rome', 'Renaissance Masters', 'Ancient Secrets', 'Modern Visions',
        'Medieval Life', 'The Golden Age', 'Voices of the Silk Road', 'Light and Shadow',
        'Masters of Bronze', 'Echoes of Empire', 'The Painted World', 'Stone and Sky',
        'Faces of History', 'Threads of Time', 'Beneath the Nile', 'Northern Lights Collection',
        'The Collector''s Eye', 'Forgotten Kingdoms', 'Art of War', 'A Century in Glass'
    ] AS words
)
INSERT INTO museum_network.exhibitions (name, start_date, end_date, hall_id)
SELECT
    t.words[1 + floor(random() * array_length(t.words, 1))::int]
        || ' — ' || row_number() OVER (ORDER BY d.hall_id, d.seq),
    d.start_date,
    d.start_date + d.duration_days - 1,
    d.hall_id
FROM exhibition_dates d
CROSS JOIN themes t;

-- Popularity ranking (1 = most popular), used to bias exhibition_items,
-- ticket_prices-driven ticket volume, visitor_feedback and guided_tours
-- toward a small set of "blockbuster" exhibitions — the long-tail shape
-- SPEC.md §2.2.6 asks for.
CREATE TEMP TABLE tmp_exhibition_popularity AS
SELECT exhibition_id, row_number() OVER (ORDER BY random()) AS popularity_rank
FROM museum_network.exhibitions;

CREATE TEMP TABLE tmp_exhibition_by_rank AS
SELECT popularity_rank, exhibition_id FROM tmp_exhibition_popularity;

-- Staff activity ranking, split by the position that plausibly performs
-- each downstream action, so "different staff activity levels" (§2.2.6)
-- means a handful of cashiers selling most tickets, not an even split
-- across all 200 employees regardless of role.
CREATE TEMP TABLE tmp_cashiers_by_rank AS
SELECT row_number() OVER (ORDER BY random()) AS activity_rank, staff_id
FROM museum_network.staff WHERE position = 'Cashier';

CREATE TEMP TABLE tmp_guides_by_rank AS
SELECT row_number() OVER (ORDER BY random()) AS activity_rank, staff_id
FROM museum_network.staff WHERE position = 'Tour Guide';

CREATE TEMP TABLE tmp_restorers AS
SELECT staff_id FROM museum_network.staff WHERE position IN ('Restorer', 'Curator');

--------------------------------------------------------------------------------
-- Exhibits (5000).
--------------------------------------------------------------------------------
INSERT INTO museum_network.exhibits
    (title, creation_year, creation_period, hall_id, type_id, acquisition_date, insurance_value, condition_status)
WITH pools AS (
    SELECT
        (SELECT array_agg(hall_id) FROM museum_network.halls) AS halls,
        (SELECT array_agg(type_id) FROM museum_network.artifact_types t
            WHERE NOT EXISTS (SELECT 1 FROM museum_network.artifact_types c WHERE c.parent_type_id = t.type_id)) AS leaf_types,
        ARRAY['excellent', 'good', 'fair', 'poor', 'under_restoration'] AS statuses
),
raw AS (
    SELECT
        gs AS seq,
        (-500 + floor(random() * 2521))::int AS creation_year,
        p.halls[1 + floor(random() * array_length(p.halls, 1))::int] AS hall_id,
        p.leaf_types[1 + floor(random() * array_length(p.leaf_types, 1))::int] AS type_id,
        p.statuses[1 + floor(random() * array_length(p.statuses, 1))::int] AS condition_status,
        -- power(random(), 3) skews hard toward 0: most items are modest,
        -- a long tail runs up toward the ~$1M ceiling — what makes ABC
        -- analysis of the collection (SPEC.md §2.2) meaningful later.
        round((100 + power(random(), 3) * 999900)::numeric, 2) AS insurance_value,
        CASE WHEN random() < 0.1 THEN NULL
             ELSE CURRENT_DATE - floor(random() * 18250)::int
        END AS acquisition_date
    FROM generate_series(1, 5000) AS gs
    CROSS JOIN pools p
)
SELECT
    'Exhibit #' || seq,
    creation_year,
    CASE
        WHEN creation_year < 500 THEN 'Ancient'
        WHEN creation_year < 1500 THEN 'Medieval'
        WHEN creation_year < 1800 THEN 'Renaissance/Baroque'
        WHEN creation_year < 1945 THEN 'Modern'
        ELSE 'Contemporary'
    END,
    hall_id,
    type_id,
    acquisition_date,
    insurance_value,
    condition_status
FROM raw;

--------------------------------------------------------------------------------
-- Exhibition_items (>=30000): each exhibition gets its OWN item count,
-- from a long-tail formula on its popularity_rank (rank 1 gets up to
-- ~200 items, rank 400 gets the 20-item floor) — not a probabilistic pick
-- of "which exhibition does this candidate belong to". That distinction
-- matters here specifically: with only 5000 exhibits to draw exhibit_id
-- from, a probabilistic skew concentrated enough to look like a long tail
-- (as tried initially) funnels almost every candidate onto the single
-- most popular exhibition and collides with itself well before reaching
-- 30000 rows, because exhibit_id has nowhere left to go. Fixing the count
-- per exhibition up front avoids that ceiling entirely.
--------------------------------------------------------------------------------
INSERT INTO museum_network.exhibition_items (exhibition_id, exhibit_id)
SELECT
    r.exhibition_id,
    (1 + floor(random() * 5000))::int
FROM tmp_exhibition_by_rank r
CROSS JOIN LATERAL generate_series(
    1, 20 + floor(power(1.0 - (r.popularity_rank - 1) / 400.0, 1.8) * 180)::int
) AS item_seq
ON CONFLICT DO NOTHING;

--------------------------------------------------------------------------------
-- Ticket prices (>=4000): 1-4 sequential, non-overlapping price periods
-- per (exhibition, visitor_type), splitting that exhibition's own
-- [start_date, end_date] window — every period sits inside a real
-- exhibition run and satisfies excl_ticket_prices_period by construction,
-- the same cumulative-window technique used for exhibitions above. Later
-- periods get a price bump, simulating demand pricing over an
-- exhibition's run and giving price_on_date() something real to resolve.
--------------------------------------------------------------------------------
WITH combos AS (
    SELECT
        e.exhibition_id, e.start_date, e.end_date,
        (e.end_date - e.start_date + 1) AS total_days,
        vt.visitor_type, vt.base_price,
        -- 1..5 periods per (exhibition, visitor_type), averaging 3: with
        -- 400 exhibitions x 4 visitor_types = 1600 combos, that targets
        -- ~4800 rows, comfortably above the 4000 minimum even with the
        -- run-to-run variance a fixed seed still leaves in a formula like
        -- this one.
        1 + floor(random() * 5)::int AS periods_count
    FROM museum_network.exhibitions e
    CROSS JOIN (VALUES
        ('Adult', 250.0), ('Student', 130.0), ('Child', 70.0), ('Senior', 150.0)
    ) AS vt(visitor_type, base_price)
),
period_slots AS (
    SELECT
        exhibition_id, start_date, end_date, total_days, visitor_type, base_price, periods_count,
        gs AS period_seq,
        GREATEST(1, total_days / periods_count) AS share_days
    FROM combos
    CROSS JOIN LATERAL generate_series(1, periods_count) AS gs
)
INSERT INTO museum_network.ticket_prices (exhibition_id, visitor_type, price, valid_from, valid_to)
SELECT
    exhibition_id,
    visitor_type,
    round((base_price * (1 + (period_seq - 1) * (0.05 + random() * 0.10)))::numeric, 2),
    start_date + ((period_seq - 1) * share_days) AS period_start,
    CASE WHEN period_seq = periods_count THEN NULL
         ELSE start_date + (period_seq * share_days)
    END AS period_end_excl
FROM period_slots;

--------------------------------------------------------------------------------
-- Tickets (>=300000): the core sales fact table.
--   1. Pick a target exhibition via the same popularity-rank technique
--      used everywhere else in this file, then uniformly pick one of
--      *that exhibition's own* ticket_prices rows (tmp_prices_by_exhibition
--      groups them per exhibition — a small array, ~12 entries on
--      average, one exhibition's worth of visitor_type x period combos).
--   2. Draw visit_date uniformly inside that price row's own validity
--      window, so every ticket's price is genuinely the one in effect on
--      its visit_date — what price_on_date()/sell_ticket() assume.
--   3. Keep the row with a probability that depends only on visit_date's
--      calendar month (tmp_month_weights): a single filter over an
--      oversampled candidate pool, not a loop, but it produces the
--      month-over-month seasonality SPEC.md §2.2.6 asks for regardless of
--      which exhibitions happen to run in which months.
--
-- An earlier version of this file instead built ONE array of price_ids
-- with popular exhibitions' rows repeated (a ~59000-element array) and
-- indexed into it per candidate row — correct in principle, but a single
-- array that large is TOASTed, and PostgreSQL re-detoasts it on every
-- subscript access; indexing it 520000 times was the entire reason a
-- first version of this file needed 115s just for this step. Grouping
-- ticket_prices by exhibition instead means every array involved is tiny
-- (a handful of price tiers per exhibition), never TOASTed, and the
-- popularity weighting happens the same way it does for
-- exhibition_items/visitor_feedback/guided_tours: a skewed target_rank
-- column, joined — never compared inside a JOIN ON with random() itself,
-- for the same reason explained by visitor_feedback below.
--------------------------------------------------------------------------------
CREATE TEMP TABLE tmp_price_pool AS
SELECT
    tp.price_id, tp.exhibition_id, tp.visitor_type, tp.price,
    tp.valid_from, tp.valid_to, e.end_date AS exhibition_end
FROM museum_network.ticket_prices tp
JOIN museum_network.exhibitions e ON e.exhibition_id = tp.exhibition_id;

ANALYZE tmp_price_pool;

CREATE TEMP TABLE tmp_prices_by_exhibition AS
SELECT exhibition_id, array_agg(price_id) AS price_ids
FROM tmp_price_pool
GROUP BY exhibition_id;

ANALYZE tmp_prices_by_exhibition;

CREATE TEMP TABLE tmp_cashier_array AS
SELECT array_agg(staff_id ORDER BY activity_rank) AS staff_ids FROM tmp_cashiers_by_rank;

CREATE TEMP TABLE tmp_month_weights (month INT, weight NUMERIC);
INSERT INTO tmp_month_weights (month, weight) VALUES
    (1, 0.7), (2, 0.6), (3, 0.8), (4, 0.9), (5, 1.0), (6, 1.3),
    (7, 1.5), (8, 1.4), (9, 1.0), (10, 0.9), (11, 0.7), (12, 1.2);
ANALYZE tmp_month_weights;

-- Broken into explicit temp-table stages, each ANALYZEd before the next
-- statement uses it, rather than one big nested-CTE statement. Two
-- independent problems forced this:
--   1. Postgres cannot estimate selectivity for a join on a column built
--      from array-index arithmetic (candidates.price_id) without real
--      statistics on it — as one CTE, the planner misjudged a ~520000-row
--      join against ~4800-row tmp_price_pool as ~11 million rows and
--      picked a plan to match, which is one of the reasons a first
--      version of this file blew the 60s budget.
--   2. More seriously: a trailing WHERE random() < month_weight / 1.5,
--      run against a CTE built on a join, gets pushed down by the planner
--      to filter tmp_month_weights' own 12 rows *before* the join —
--      legal in relational algebra for a single-relation predicate, but
--      wrong here, because it calls random() once per month instead of
--      once per candidate ticket, so it would keep or drop whole months
--      wholesale instead of sampling individual tickets. Drawing keep_pick
--      once per row back in tmp_ticket_candidates (a plain column by the
--      time it's compared) and filtering on that stored value, rather
--      than re-invoking random() in the final WHERE, avoids this — a
--      materialized column can't be silently re-evaluated at a different
--      place in the plan the way a bare random() call can.
CREATE TEMP TABLE tmp_ticket_candidates AS
WITH draws AS (
    SELECT
        gs AS seq,
        LEAST(400, GREATEST(1, (1 + floor(power(random(), 2.5) * 400))::int)) AS target_rank,
        random() AS price_pick,
        random() AS lead_pick,
        random() AS pm_pick,
        random() AS ch_pick,
        random() AS qty_pick,
        random() AS purchase_hour_pick,
        random() AS keep_pick,
        ca.staff_ids[
            LEAST(array_length(ca.staff_ids, 1),
                  GREATEST(1, (1 + floor(power(random(), 2.0) * array_length(ca.staff_ids, 1)))::int))
        ] AS staff_id
    FROM generate_series(1, 520000) AS gs
    CROSS JOIN tmp_cashier_array ca
)
SELECT
    pbe.price_ids[1 + floor(d.price_pick * array_length(pbe.price_ids, 1))::int] AS price_id,
    d.staff_id, d.lead_pick, d.pm_pick, d.ch_pick, d.qty_pick, d.purchase_hour_pick, d.keep_pick
FROM draws d
JOIN tmp_exhibition_by_rank r ON r.popularity_rank = d.target_rank
JOIN tmp_prices_by_exhibition pbe ON pbe.exhibition_id = r.exhibition_id;

ANALYZE tmp_ticket_candidates;

CREATE TEMP TABLE tmp_ticket_dated AS
SELECT
    c.price_id, c.staff_id, c.lead_pick, c.pm_pick, c.ch_pick, c.qty_pick,
    c.purchase_hour_pick, c.keep_pick,
    pp.valid_from
        + floor(random() * GREATEST(1, COALESCE(pp.valid_to, pp.exhibition_end + 1) - pp.valid_from))::int
        AS visit_date
FROM tmp_ticket_candidates c
JOIN tmp_price_pool pp ON pp.price_id = c.price_id;

ANALYZE tmp_ticket_dated;

INSERT INTO museum_network.tickets
    (price_id, staff_id, purchase_date, visit_date, payment_method, sales_channel, quantity)
SELECT
    d.price_id,
    d.staff_id,
    -- lead_pick^2 skews toward 0: most tickets are bought 0-a few days
    -- before the visit, a minority weeks in advance.
    (d.visit_date - floor(d.lead_pick * d.lead_pick * 30)::int)::timestamptz
        + (9 + d.purchase_hour_pick * 10) * interval '1 hour' AS purchase_date,
    d.visit_date,
    CASE WHEN d.pm_pick < 0.55 THEN 'card' WHEN d.pm_pick < 0.85 THEN 'cash' ELSE 'online' END,
    CASE WHEN d.ch_pick < 0.60 THEN 'on_site' WHEN d.ch_pick < 0.90 THEN 'online' ELSE 'group_booking' END,
    CASE WHEN d.qty_pick < 0.60 THEN 1 WHEN d.qty_pick < 0.85 THEN 2 WHEN d.qty_pick < 0.95 THEN 3 ELSE 4 END
FROM tmp_ticket_dated d
JOIN tmp_month_weights mw ON mw.month = EXTRACT(MONTH FROM d.visit_date)::int
WHERE d.keep_pick < mw.weight / 1.5;

--------------------------------------------------------------------------------
-- Visitor feedback (80000): weighted toward popular exhibitions, ratings
-- skewed positive (opt-in museum feedback is rarely evenly split),
-- created_at falls during the exhibition's run or up to a month after.
--------------------------------------------------------------------------------
INSERT INTO museum_network.visitor_feedback (exhibition_id, rating, comment, created_at)
WITH comment_pool AS (
    SELECT ARRAY[
        'Absolutely stunning collection, worth the visit.',
        'Great exhibition but too crowded on weekends.',
        'The audio guide was very informative.',
        'Loved it, will come back with the kids.',
        'A bit small for the price of the ticket.',
        'One of the best exhibitions I have seen this year.',
        'Poor lighting made some pieces hard to see.',
        'Friendly staff and a well-organized layout.',
        NULL, NULL, NULL
    ] AS comments
),
-- target_rank is drawn here, in a plain SELECT list, and only compared
-- against tmp_exhibition_by_rank afterward — never inside a JOIN ON
-- clause. A volatile function such as random() inside a join condition
-- can be re-evaluated once per row *comparison* rather than once per
-- input row (Postgres makes no promise otherwise for a nested-loop plan),
-- silently producing zero, one, or several matches per candidate instead
-- of exactly one. This is what actually broke guided_tours (0 rows) and
-- doubled visitor_feedback (160000 rows) the first time this file ran —
-- not a logic error in the weighting formula itself, just random() in
-- the wrong clause.
draws AS (
    SELECT
        gs AS seq,
        LEAST(400, GREATEST(1, (1 + floor(power(random(), 2.0) * 400))::int)) AS target_rank,
        random() AS rating_pick,
        random() AS comment_pick,
        random() AS date_pick
    FROM generate_series(1, 80000) AS gs
),
picks AS (
    SELECT
        d.rating_pick, d.comment_pick, d.date_pick,
        r.exhibition_id, e.start_date, e.end_date
    FROM draws d
    JOIN tmp_exhibition_by_rank r ON r.popularity_rank = d.target_rank
    JOIN museum_network.exhibitions e ON e.exhibition_id = r.exhibition_id
)
SELECT
    p.exhibition_id,
    -- power(x, 0.4) skews toward 1: mostly 4-5 star ratings, a shorter
    -- tail of 1-2 star ones.
    LEAST(5, GREATEST(1, (1 + floor(power(p.rating_pick, 0.4) * 5))::int)),
    cp.comments[1 + floor(p.comment_pick * array_length(cp.comments, 1))::int],
    (p.start_date + floor(p.date_pick * (p.end_date - p.start_date + 30))::int)::timestamptz
        + (random() * interval '12 hours')
FROM picks p
CROSS JOIN comment_pool cp;

--------------------------------------------------------------------------------
-- Guided tours (8000): scheduled during the exhibition's run, led by a
-- tour guide (activity-weighted, same technique as cashiers).
--------------------------------------------------------------------------------
CREATE TEMP TABLE tmp_guide_array AS
SELECT array_agg(staff_id ORDER BY activity_rank) AS staff_ids FROM tmp_guides_by_rank;

INSERT INTO museum_network.guided_tours (exhibition_id, staff_id, starts_at, capacity)
-- Same target_rank-as-a-column technique as visitor_feedback above (see
-- the comment there): never put random() inside a JOIN ON clause.
WITH draws AS (
    SELECT
        gs AS seq,
        LEAST(400, GREATEST(1, (1 + floor(power(random(), 1.8) * 400))::int)) AS target_rank
    FROM generate_series(1, 8000) AS gs
),
picks AS (
    SELECT
        r.exhibition_id, e.start_date, e.end_date,
        pl.staff_ids[1 + floor(random() * array_length(pl.staff_ids, 1))::int] AS staff_id,
        floor(random() * 9)::int AS start_hour_offset,  -- opens 09:00, last tour 17:00
        floor(random() * (e.end_date - e.start_date + 1))::int AS day_offset,
        (10 + floor(random() * 21))::int AS capacity
    FROM draws d
    JOIN tmp_exhibition_by_rank r ON r.popularity_rank = d.target_rank
    JOIN museum_network.exhibitions e ON e.exhibition_id = r.exhibition_id
    CROSS JOIN tmp_guide_array pl
)
SELECT
    exhibition_id,
    staff_id,
    (start_date + day_offset)::timestamptz + (9 + start_hour_offset) * interval '1 hour',
    capacity
FROM picks;

--------------------------------------------------------------------------------
-- Tour bookings (>=50000): the second M2M relationship. Each booking's
-- ticket is matched to the same exhibition as the tour it books, so a
-- visitor only ever books a tour for the exhibition they bought a ticket
-- to — up to 8 candidate bookings per tour, dropped wherever an
-- exhibition ended up with zero tickets (rare, only the least popular
-- ones), comfortably clearing 50000 either way.
--------------------------------------------------------------------------------
CREATE TEMP TABLE tmp_ticket_exhibition AS
SELECT t.ticket_id, tp.exhibition_id
FROM museum_network.tickets t
JOIN museum_network.ticket_prices tp ON tp.price_id = t.price_id;

CREATE TEMP TABLE tmp_tickets_by_exhibition AS
SELECT exhibition_id, array_agg(ticket_id) AS ticket_ids
FROM tmp_ticket_exhibition
GROUP BY exhibition_id;

INSERT INTO museum_network.tour_bookings (tour_id, ticket_id, status)
SELECT
    cand.tour_id,
    tbe.ticket_ids[1 + floor(random() * array_length(tbe.ticket_ids, 1))::int],
    CASE WHEN cand.st_pick < 0.80 THEN 'attended'
         WHEN cand.st_pick < 0.90 THEN 'booked'
         WHEN cand.st_pick < 0.97 THEN 'cancelled'
         ELSE 'no_show'
    END
FROM (
    SELECT gt.tour_id, gt.exhibition_id, random() AS st_pick
    FROM museum_network.guided_tours gt
    CROSS JOIN generate_series(1, 8) AS rep
) cand
JOIN tmp_tickets_by_exhibition tbe ON tbe.exhibition_id = cand.exhibition_id;

--------------------------------------------------------------------------------
-- Restorations (3000): exhibit and restorer/curator picked uniformly (no
-- strong activity skew needed — restoration work is naturally rarer and
-- more evenly spread than ticket sales). ~15% are still in progress
-- (end_date NULL). Cost uses the same long-tail shape as
-- exhibits.insurance_value.
--------------------------------------------------------------------------------
INSERT INTO museum_network.restorations (exhibit_id, staff_id, start_date, end_date, cost)
WITH pools AS (
    SELECT array_agg(staff_id) AS restorer_ids FROM tmp_restorers
),
picks AS (
    SELECT
        (1 + floor(random() * 5000))::int AS exhibit_id,
        pl.restorer_ids[1 + floor(random() * array_length(pl.restorer_ids, 1))::int] AS staff_id,
        CURRENT_DATE - floor(random() * 2555)::int AS start_date,
        (10 + floor(random() * 170))::int AS duration_days,
        round((100 + power(random(), 2.5) * 49900)::numeric, 2) AS cost,
        random() AS ongoing_pick
    FROM generate_series(1, 3000) AS gs
    CROSS JOIN pools pl
)
SELECT
    exhibit_id,
    staff_id,
    start_date,
    CASE WHEN ongoing_pick < 0.15 THEN NULL ELSE start_date + duration_days END,
    cost
FROM picks;

--------------------------------------------------------------------------------
-- Refresh mv_monthly_revenue now that tickets exist, and update planner
-- statistics on every populated table — skipping this would leave the
-- planner working off empty-table statistics for the first real queries.
--------------------------------------------------------------------------------
REFRESH MATERIALIZED VIEW museum_network.mv_monthly_revenue;

-- Named explicitly rather than a bare ANALYZE: saw_admin doesn't own the
-- postgres system catalogs, and a database-wide ANALYZE would print a
-- permission-denied warning for each of them.
ANALYZE museum_network.halls;
ANALYZE museum_network.artifact_types;
ANALYZE museum_network.staff;
ANALYZE museum_network.exhibits;
ANALYZE museum_network.exhibitions;
ANALYZE museum_network.exhibition_items;
ANALYZE museum_network.ticket_prices;
ANALYZE museum_network.tickets;
ANALYZE museum_network.visitor_feedback;
ANALYZE museum_network.guided_tours;
ANALYZE museum_network.tour_bookings;
ANALYZE museum_network.restorations;
ANALYZE museum_network.audit_log;
