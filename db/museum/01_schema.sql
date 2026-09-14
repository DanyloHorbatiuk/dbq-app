-- =============================================================================
-- museum_network — table definitions.
--
-- Extends the schema captured in legacy_schema.sql (kept there, unmodified,
-- as a reference point) per SPEC.md §2.2.2 / §2.2.3. Rerunnable: dropping
-- the schema with CASCADE and recreating it is simpler and just as safe as
-- an IF NOT EXISTS per-object approach here, because `make reset` always
-- runs this against a fresh database anyway (see docker/postgres/initdb).
--
-- CHECK constraints and the two EXCLUDE USING gist constraints live in
-- 02_constraints.sql, not here — keeping "what a row must look like
-- structurally" (this file) separate from "what values are allowed in it"
-- (02_constraints.sql) so each file stays small enough to explain on its own.
-- =============================================================================

DROP SCHEMA IF EXISTS museum_network CASCADE;
CREATE SCHEMA museum_network;

--------------------------------------------------------------------------------
-- Existing tables (from legacy_schema.sql), carried over with the changes
-- required by SPEC.md §2.2.2. Order: parents before children, as before.
--------------------------------------------------------------------------------

-- Halls — unchanged from legacy_schema.sql.
CREATE TABLE museum_network.halls (
    hall_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name    VARCHAR(100) NOT NULL UNIQUE,
    floor   INT NOT NULL
);

-- Artifact types — self-referencing parent_type_id added for the 3-level
-- hierarchy required for the recursive CTE query (SPEC.md §2.2.2, §3.2
-- level 3). NULL means "top-level type".
CREATE TABLE museum_network.artifact_types (
    type_id        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_name      VARCHAR(50) NOT NULL UNIQUE,
    parent_type_id INT REFERENCES museum_network.artifact_types(type_id)
);

-- Staff — unchanged from legacy_schema.sql.
CREATE TABLE museum_network.staff (
    staff_id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name  VARCHAR(50) NOT NULL,
    email      VARCHAR(100) NOT NULL UNIQUE,
    position   VARCHAR(50) NOT NULL
);

-- Exhibits — acquisition_date, insurance_value, condition_status added for
-- ABC-analysis of the collection and value-by-hall queries (§2.2.2).
CREATE TABLE museum_network.exhibits (
    exhibit_id       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title            VARCHAR(200) NOT NULL,
    creation_year    INT,
    creation_period  VARCHAR(100),
    hall_id          INT NOT NULL REFERENCES museum_network.halls(hall_id),
    type_id          INT NOT NULL REFERENCES museum_network.artifact_types(type_id),
    -- Nullable: acquisition records for older donated/transferred items are
    -- not always known precisely, unlike a purchase made by the museum itself.
    acquisition_date DATE,
    insurance_value  NUMERIC(12, 2) NOT NULL,
    condition_status VARCHAR(20) NOT NULL
);

-- Exhibitions — hall_id added so an exhibition can be pinned to a physical
-- hall (needed for the hall/date overlap EXCLUDE constraint in
-- 02_constraints.sql); the old CHECK forcing start_date into 2026+ is
-- dropped here structurally and replaced in 02_constraints.sql.
CREATE TABLE museum_network.exhibitions (
    exhibition_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          VARCHAR(150) NOT NULL UNIQUE,
    start_date    DATE NOT NULL,
    end_date      DATE NOT NULL,
    hall_id       INT NOT NULL REFERENCES museum_network.halls(hall_id)
);

-- Exhibition_Items — unchanged M2M bridge from legacy_schema.sql.
CREATE TABLE museum_network.exhibition_items (
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id) ON DELETE CASCADE,
    exhibit_id    INT NOT NULL REFERENCES museum_network.exhibits(exhibit_id) ON DELETE CASCADE,
    PRIMARY KEY (exhibition_id, exhibit_id)
);

-- Ticket prices — valid_from/valid_to turn this into an SCD Type 2 history
-- table (§2.2.2): a (exhibition_id, visitor_type) pair can now have several
-- rows over time instead of exactly one. The old UNIQUE(exhibition_id,
-- visitor_type) is dropped here and replaced in 02_constraints.sql by an
-- EXCLUDE constraint that forbids two *overlapping* periods for the same
-- pair, while allowing successive ones (price changes over time).
CREATE TABLE museum_network.ticket_prices (
    price_id      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id),
    visitor_type  VARCHAR(20) NOT NULL,
    price         DECIMAL(10, 2) NOT NULL,
    valid_from    DATE NOT NULL,
    -- NULL = still in effect (open-ended period).
    valid_to      DATE
);

-- Tickets — visit_date/payment_method/sales_channel/quantity added for
-- sales-channel segmentation (§2.2.2). purchase_date is upgraded from
-- TIMESTAMP to TIMESTAMPTZ: every other timestamped table added in this
-- stage (visitor_feedback.created_at, guided_tours.starts_at, audit_log)
-- uses TIMESTAMPTZ, and mixing the two in one schema is exactly the kind
-- of inconsistency that produces silent off-by-timezone bugs in later
-- month-over-month revenue queries — not something SPEC.md asked for
-- explicitly, but a direct consequence of extending this table at all.
CREATE TABLE museum_network.tickets (
    ticket_id      INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_id       INT NOT NULL REFERENCES museum_network.ticket_prices(price_id),
    staff_id       INT NOT NULL REFERENCES museum_network.staff(staff_id),
    purchase_date  TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    -- The day the visitor actually attends, which may differ from
    -- purchase_date when a ticket is bought in advance.
    visit_date     DATE NOT NULL,
    payment_method VARCHAR(20) NOT NULL,
    sales_channel  VARCHAR(20) NOT NULL,
    quantity       SMALLINT NOT NULL DEFAULT 1
);

--------------------------------------------------------------------------------
-- New tables (SPEC.md §2.2.3).
--------------------------------------------------------------------------------

-- Visitor feedback — ratings and free-text comments per exhibition. The GIN
-- index for full-text search over `comment` is added later, as part of the
-- index experiments (§ФВ-06), not here — this file only defines structure.
CREATE TABLE museum_network.visitor_feedback (
    feedback_id   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id),
    rating        SMALLINT NOT NULL,
    comment       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Restorations — cost/workload tracking per exhibit and per restorer.
-- end_date is nullable: a restoration that is still in progress has no end
-- date yet.
CREATE TABLE museum_network.restorations (
    restoration_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exhibit_id     INT NOT NULL REFERENCES museum_network.exhibits(exhibit_id),
    staff_id       INT NOT NULL REFERENCES museum_network.staff(staff_id),
    start_date     DATE NOT NULL,
    end_date       DATE,
    cost           NUMERIC(12, 2) NOT NULL
);

-- Guided tours — scheduled tours tied to an exhibition and led by a staff
-- member.
CREATE TABLE museum_network.guided_tours (
    tour_id       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id),
    staff_id      INT NOT NULL REFERENCES museum_network.staff(staff_id),
    starts_at     TIMESTAMPTZ NOT NULL,
    capacity      SMALLINT NOT NULL
);

-- Tour bookings — the second M2M relationship required by the assignment:
-- a ticket can be booked onto a guided tour, with its own status (not a
-- plain bridge table, since the booking itself has a lifecycle).
CREATE TABLE museum_network.tour_bookings (
    booking_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tour_id    INT NOT NULL REFERENCES museum_network.guided_tours(tour_id),
    ticket_id  INT NOT NULL REFERENCES museum_network.tickets(ticket_id),
    status     VARCHAR(20) NOT NULL DEFAULT 'booked'
);

-- Audit log — target of the fn_audit() trigger added in 05_triggers.sql
-- (Etap 2). table_name/operation identify the event; old_row/new_row carry
-- the full before/after row as JSONB, which is what makes JSONB queries
-- over audit history possible later. log_id is BIGINT rather than INT
-- because this table only grows and 300k+ tickets alone will generate at
-- least that many INSERT rows here.
CREATE TABLE museum_network.audit_log (
    log_id     BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name TEXT NOT NULL,
    operation  TEXT NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changed_by TEXT NOT NULL DEFAULT CURRENT_USER,
    old_row    JSONB,
    new_row    JSONB
);
