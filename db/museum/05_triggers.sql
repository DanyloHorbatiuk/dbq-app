-- =============================================================================
-- museum_network — triggers (SPEC.md §2.2.5).
--
-- CREATE OR REPLACE TRIGGER (PostgreSQL 14+) makes this rerunnable without
-- a separate DROP TRIGGER IF EXISTS step.
-- =============================================================================

CREATE OR REPLACE TRIGGER trg_audit_tickets
    AFTER INSERT OR UPDATE OR DELETE ON museum_network.tickets
    FOR EACH ROW EXECUTE FUNCTION museum_network.fn_audit();

CREATE OR REPLACE TRIGGER trg_audit_ticket_prices
    AFTER INSERT OR UPDATE OR DELETE ON museum_network.ticket_prices
    FOR EACH ROW EXECUTE FUNCTION museum_network.fn_audit();
