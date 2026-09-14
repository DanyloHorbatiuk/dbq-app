-- =============================================================================
-- museum_network — integrity constraints (SPEC.md §2.2.4).
--
-- Split from 01_schema.sql on purpose: this file answers "what values are
-- valid", the previous one answers "what a row looks like structurally".
-- Applied as ALTER TABLE ... ADD CONSTRAINT, the same style legacy_schema.sql
-- already used, so the diff against it is easy to follow.
--
-- btree_gist is created here defensively (IF NOT EXISTS) even though
-- docker/postgres/initdb/20_databases.sh already enables it at the database
-- level — this keeps the file runnable on its own against a bare database,
-- e.g. while iterating on it by hand with `make psql-museum`.
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;

--------------------------------------------------------------------------------
-- Carried over from legacy_schema.sql, unchanged.
--------------------------------------------------------------------------------

ALTER TABLE museum_network.ticket_prices
    ADD CONSTRAINT check_positive_price CHECK (price >= 0);

ALTER TABLE museum_network.ticket_prices
    ADD CONSTRAINT check_visitor_category CHECK (visitor_type IN ('Adult', 'Student', 'Child', 'Senior'));

ALTER TABLE museum_network.exhibitions
    ADD CONSTRAINT check_exhibition_duration CHECK (end_date >= start_date);

ALTER TABLE museum_network.halls
    ADD CONSTRAINT check_hall_floor CHECK (floor BETWEEN -1 AND 10);

/*
This regex ensures the email follows a standard format: local-part@domain.extension
It validates that the string contains an '@' symbol, a dot, and a valid top-level domain.
*/
ALTER TABLE museum_network.staff
    ADD CONSTRAINT check_staff_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');

--------------------------------------------------------------------------------
-- Changed from legacy_schema.sql: start_date range relaxed to allow
-- historical data (SPEC.md §2.2.2) instead of forcing everything into 2026+.
--------------------------------------------------------------------------------

ALTER TABLE museum_network.exhibitions
    ADD CONSTRAINT check_start_date_range CHECK (start_date >= DATE '2000-01-01');

--------------------------------------------------------------------------------
-- New CHECK constraints for columns added in 01_schema.sql.
--------------------------------------------------------------------------------

ALTER TABLE museum_network.exhibits
    ADD CONSTRAINT check_exhibits_insurance_value CHECK (insurance_value >= 0);

ALTER TABLE museum_network.exhibits
    ADD CONSTRAINT check_exhibits_condition_status
        CHECK (condition_status IN ('excellent', 'good', 'fair', 'poor', 'under_restoration'));

ALTER TABLE museum_network.tickets
    ADD CONSTRAINT check_tickets_quantity CHECK (quantity > 0);

ALTER TABLE museum_network.tickets
    ADD CONSTRAINT check_tickets_payment_method
        CHECK (payment_method IN ('cash', 'card', 'online'));

ALTER TABLE museum_network.tickets
    ADD CONSTRAINT check_tickets_sales_channel
        CHECK (sales_channel IN ('on_site', 'online', 'group_booking'));

-- Upper bound must be strictly after the lower bound, matching the
-- exclusive-upper-bound convention the EXCLUDE constraint below uses for
-- the same columns (see excl_ticket_prices_period): a same-day valid_from =
-- valid_to would otherwise describe a price tier that is never actually in
-- effect for a full day.
ALTER TABLE museum_network.ticket_prices
    ADD CONSTRAINT check_ticket_prices_period CHECK (valid_to IS NULL OR valid_to > valid_from);

ALTER TABLE museum_network.visitor_feedback
    ADD CONSTRAINT check_visitor_feedback_rating CHECK (rating BETWEEN 1 AND 5);

ALTER TABLE museum_network.restorations
    ADD CONSTRAINT check_restorations_period CHECK (end_date IS NULL OR end_date >= start_date);

ALTER TABLE museum_network.restorations
    ADD CONSTRAINT check_restorations_cost CHECK (cost >= 0);

ALTER TABLE museum_network.guided_tours
    ADD CONSTRAINT check_guided_tours_capacity CHECK (capacity > 0);

ALTER TABLE museum_network.tour_bookings
    ADD CONSTRAINT check_tour_bookings_status
        CHECK (status IN ('booked', 'cancelled', 'attended', 'no_show'));

ALTER TABLE museum_network.audit_log
    ADD CONSTRAINT check_audit_log_operation
        CHECK (operation IN ('INSERT', 'UPDATE', 'DELETE'));

--------------------------------------------------------------------------------
-- EXCLUDE USING gist constraints (SPEC.md §2.2.4) — the two required ones.
--------------------------------------------------------------------------------

-- No two exhibitions may occupy the same hall on overlapping dates.
-- Both bounds are inclusive ('[]'): an exhibition that runs through
-- end_date is still physically in the hall on that date.
ALTER TABLE museum_network.exhibitions
    ADD CONSTRAINT excl_exhibitions_hall_period
    EXCLUDE USING gist (
        hall_id WITH =,
        daterange(start_date, end_date, '[]') WITH &&
    );

-- No two price tiers for the same (exhibition, visitor_type) may have
-- overlapping validity periods. Default range bounds ('[)') match
-- check_ticket_prices_period above: valid_from is the first day the price
-- applies, valid_to is the first day it no longer does.
ALTER TABLE museum_network.ticket_prices
    ADD CONSTRAINT excl_ticket_prices_period
    EXCLUDE USING gist (
        exhibition_id WITH =,
        visitor_type WITH =,
        daterange(valid_from, valid_to) WITH &&
    );
