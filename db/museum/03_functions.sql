-- =============================================================================
-- museum_network — functions (SPEC.md §2.2.5).
--
-- CREATE OR REPLACE makes every function here rerunnable on its own.
-- =============================================================================

--------------------------------------------------------------------------------
-- update_staff_data() — carried over from legacy_schema.sql unchanged.
--
-- SPEC.md §2.2.5 groups this together with sell_ticket() under "adapt for
-- the new ticket_prices structure", but this function has nothing to do
-- with pricing at all — it is a generic column updater for `staff`. That
-- line reads like it was written with only sell_ticket() in mind; treating
-- it as "keep update_staff_data() as-is, adapt sell_ticket()" is the
-- reading agreed on when the schema diff was reviewed.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION museum_network.update_staff_data(
    p_staff_id INT,
    p_column_name TEXT,
    p_new_value TEXT
)
RETURNS TEXT AS $$
BEGIN
    -- Uses dynamic SQL to update a specific column without hardcoding.
    -- %I safely quotes the column name as an identifier; USING
    -- parameterizes the value, so this is not open to SQL injection —
    -- though it does let a caller overwrite staff_id itself. SPEC.md says
    -- to keep this function's behavior, so that risk is intentionally
    -- left as-is.
    EXECUTE format('UPDATE museum_network.staff SET %I = $1 WHERE staff_id = $2', p_column_name)
    USING p_new_value, p_staff_id;

    RETURN 'Success: Staff ID ' || p_staff_id || ' updated (' || p_column_name || ')';
EXCEPTION
    WHEN OTHERS THEN
        RETURN 'Error: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

--------------------------------------------------------------------------------
-- price_on_date() — new (SPEC.md §2.2.5). Returns the price in effect for
-- a given exhibition/visitor_type on a given date, using the same
-- half-open period convention ([valid_from, valid_to)) as the
-- excl_ticket_prices_period EXCLUDE constraint in 02_constraints.sql.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION museum_network.price_on_date(
    p_exhibition_id INT,
    p_visitor_type TEXT,
    p_on_date DATE
)
RETURNS NUMERIC AS $$
DECLARE
    v_price NUMERIC;
BEGIN
    SELECT price INTO v_price
    FROM museum_network.ticket_prices
    WHERE exhibition_id = p_exhibition_id
      AND visitor_type = p_visitor_type
      AND valid_from <= p_on_date
      AND (valid_to IS NULL OR valid_to > p_on_date);

    IF v_price IS NULL THEN
        RAISE EXCEPTION 'No price tier for exhibition % / % on %', p_exhibition_id, p_visitor_type, p_on_date;
    END IF;

    RETURN v_price;
END;
$$ LANGUAGE plpgsql STABLE;

--------------------------------------------------------------------------------
-- sell_ticket() — adapted for the new ticket_prices/tickets structure.
-- Resolves natural keys (exhibition name, staff email) the same way
-- legacy_schema.sql did, but now also needs the specific ticket_prices
-- row valid on the visit date. It re-runs the same effective-date
-- predicate as price_on_date() rather than calling it, because tickets
-- stores a price_id (to preserve pricing history even after later price
-- changes), and price_on_date() only exposes the price value, not the row.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION museum_network.sell_ticket(
    p_exhibition_name TEXT,
    p_visitor_type TEXT,
    p_staff_email TEXT,
    p_visit_date DATE,
    p_payment_method TEXT,
    p_sales_channel TEXT,
    -- INT, not SMALLINT: tickets.quantity is SMALLINT, but a plain integer
    -- literal (e.g. from psql or psycopg) does not implicitly match a
    -- SMALLINT parameter during function overload resolution — only during
    -- column assignment. INT avoids forcing every caller to write an
    -- explicit ::smallint cast; it narrows fine on INSERT below.
    p_quantity INT DEFAULT 1
)
RETURNS TEXT AS $$
DECLARE
    v_exhibition_id INT;
    v_staff_id INT;
    v_price_id INT;
BEGIN
    SELECT exhibition_id INTO v_exhibition_id
    FROM museum_network.exhibitions
    WHERE name = p_exhibition_name;

    SELECT staff_id INTO v_staff_id
    FROM museum_network.staff
    WHERE email = p_staff_email;

    IF v_exhibition_id IS NULL OR v_staff_id IS NULL THEN
        RAISE EXCEPTION 'Lookup failed: check exhibition name and staff email.';
    END IF;

    SELECT price_id INTO v_price_id
    FROM museum_network.ticket_prices
    WHERE exhibition_id = v_exhibition_id
      AND visitor_type = p_visitor_type
      AND valid_from <= p_visit_date
      AND (valid_to IS NULL OR valid_to > p_visit_date);

    IF v_price_id IS NULL THEN
        RAISE EXCEPTION 'No price tier for % / % on %', p_exhibition_name, p_visitor_type, p_visit_date;
    END IF;

    INSERT INTO museum_network.tickets
        (price_id, staff_id, visit_date, payment_method, sales_channel, quantity)
    VALUES
        (v_price_id, v_staff_id, p_visit_date, p_payment_method, p_sales_channel, p_quantity);

    RETURN 'Success: ticket sold for ' || p_exhibition_name;
END;
$$ LANGUAGE plpgsql;

--------------------------------------------------------------------------------
-- fn_audit() — trigger function for AFTER INSERT OR UPDATE OR DELETE
-- triggers (wired up in 05_triggers.sql). changed_at/changed_by are left
-- to audit_log's own column DEFAULTs (CURRENT_TIMESTAMP/CURRENT_USER) from
-- 01_schema.sql, rather than repeating that logic here.
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION museum_network.fn_audit()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO museum_network.audit_log (table_name, operation, old_row, new_row)
    VALUES (
        TG_TABLE_NAME,
        TG_OP,
        CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN to_jsonb(OLD) ELSE NULL END,
        CASE WHEN TG_OP IN ('INSERT', 'UPDATE') THEN to_jsonb(NEW) ELSE NULL END
    );

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
