/*
TASK 3: PHYSICAL DATABASE DESIGN
Subject Area: MUSEUM
*/

-- 1. Ensure the script is rerunnable by using IF NOT EXISTS and dropping the schema if necessary
-- Note: In a production or "rerunnable" assignment, often is used DROP SCHEMA ... CASCADE
-- but to be safe and additive, I will use the following block:
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'museum_network') THEN
        DROP SCHEMA museum_network CASCADE;
    END IF;
END $$;

CREATE SCHEMA museum_network;

--------------------------------------------------------------------------------
-- 2. Create Tables (Order: Parents before Children)
--------------------------------------------------------------------------------

-- Table: Halls (Parent)
-- Represents physical locations. Uses IDENTITY for PK[cite: 8, 37].
CREATE TABLE museum_network.halls (
    hall_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    floor INT NOT NULL
);

-- Table: Artifact Types (Parent)
-- Eliminates transitive dependencies for 3NF[cite: 34, 35].
CREATE TABLE museum_network.artifact_types (
    type_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    type_name VARCHAR(50) NOT NULL UNIQUE
);

-- Table: Staff (Parent)
-- email is UNIQUE to serve as a natural key for future DML lookups[cite: 37].
CREATE TABLE museum_network.staff (
    staff_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    position VARCHAR(50) NOT NULL
);

-- Table: Exhibits (Child of Halls and Types)
-- creation_year instead of exact date for historical flexibility.
CREATE TABLE museum_network.exhibits (
    exhibit_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    creation_year INT,
    creation_period VARCHAR(100),
    hall_id INT NOT NULL REFERENCES museum_network.halls(hall_id),
    type_id INT NOT NULL REFERENCES museum_network.artifact_types(type_id)
);

-- Table: Exhibitions (Parent)
CREATE TABLE museum_network.exhibitions (
    exhibition_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name VARCHAR(150) NOT NULL UNIQUE,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL
);

-- Table: Exhibition_Items (Many-to-Many Junction)
-- Satisfies the requirement for at least one M2M relationship[cite: 7, 8].
CREATE TABLE museum_network.exhibition_items (
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id) ON DELETE CASCADE,
    exhibit_id INT NOT NULL REFERENCES museum_network.exhibits(exhibit_id) ON DELETE CASCADE,
    PRIMARY KEY (exhibition_id, exhibit_id)
);

-- Table: Ticket Prices (Child of Exhibitions)
-- Stores pricing history to avoid data anomalies[cite: 27].
CREATE TABLE museum_network.ticket_prices (
    price_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    exhibition_id INT NOT NULL REFERENCES museum_network.exhibitions(exhibition_id),
    visitor_type VARCHAR(20) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    CONSTRAINT unique_price_tier UNIQUE (exhibition_id, visitor_type)
);

-- Table: Tickets (Child of Prices and Staff)
-- Represents the transaction event[cite: 32].
CREATE TABLE museum_network.tickets (
    ticket_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    price_id INT NOT NULL REFERENCES museum_network.ticket_prices(price_id),
    staff_id INT NOT NULL REFERENCES museum_network.staff(staff_id),
    purchase_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

--------------------------------------------------------------------------------
-- 3. Apply Constraints (Task 3 requirement: at least 5 check constraints)
--------------------------------------------------------------------------------

-- Constraint 1: Date must be greater than January 1, 2026
ALTER TABLE museum_network.exhibitions
ADD CONSTRAINT check_start_date_future CHECK (start_date >= '2026-01-01');

-- Constraint 2: Measured value (price) cannot be negative
ALTER TABLE museum_network.ticket_prices
ADD CONSTRAINT check_positive_price CHECK (price >= 0);

-- Constraint 3: Specific allowed values for visitor types
ALTER TABLE museum_network.ticket_prices
ADD CONSTRAINT check_visitor_category CHECK (visitor_type IN ('Adult', 'Student', 'Child', 'Senior'));

-- Constraint 4: Logical time order (end must be after start)
ALTER TABLE museum_network.exhibitions
ADD CONSTRAINT check_exhibition_duration CHECK (end_date >= start_date);

-- Constraint 5: Valid floor range for the museum
ALTER TABLE museum_network.halls
ADD CONSTRAINT check_hall_floor CHECK (floor BETWEEN -1 AND 10);

-- Constraint 6: Valid email format (regex check)
/*
This regex ensures the email follows a standard format: local-part@domain.extension
It validates that the string contains an '@' symbol, a dot, and a valid top-level domain.
*/
ALTER TABLE museum_network.staff
ADD CONSTRAINT check_staff_email_format CHECK (email ~* '^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$');


/*
TASK 4: POPULATE TABLES (DML)
*/

-- 1. Insert Artifact Types
INSERT INTO museum_network.artifact_types (type_name) VALUES
('Oil Painting'), ('Marble Sculpture'), ('Ancient Artifact'),
('Photography'), ('Textile'), ('Coin');

-- 2. Insert Halls
INSERT INTO museum_network.halls (name, floor) VALUES
('Renaissance Gallery', 1),
('Ancient Egypt Room', 1),
('Modern Art Wing', 2),
('Statue Court', 0),
('Medieval Armory', 2),
('Historical Vault', -1);

-- 3. Insert Staff
-- email is used as a Natural Key for future lookups
INSERT INTO museum_network.staff (first_name, last_name, email, position) VALUES
('Nadiya', 'Pokorna', 'n.pokorna@museum.com', 'Curator'),
('Oleksandr', 'Dovzhenko', 'o.dovzhenko@museum.com', 'Cashier'),
('Maria', 'Sydorenko', 'm.sydorenko@museum.com', 'Tour Guide'),
('Ivan', 'Franko', 'i.franko@museum.com', 'Security Manager'),
('Olena', 'Pchilka', 'o.pchilka@museum.com', 'Administrator'),
('Taras', 'Shevchenko', 't.shevchenko@museum.com', 'Cashier');

-- 4. Insert Exhibits (Avoiding Hardcoding IDs)
INSERT INTO museum_network.exhibits (title, creation_year, creation_period, hall_id, type_id) VALUES
('Mona Lisa', 1503, 'High Renaissance',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Renaissance Gallery'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Oil Painting')),
('Rosetta Stone', -196, 'Ptolemaic Period',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Ancient Egypt Room'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Ancient Artifact')),
('David Statue', 1504, 'Renaissance',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Statue Court'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Marble Sculpture')),
('Knight Armor', 1450, 'Late Middle Ages',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Medieval Armory'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Ancient Artifact')),
('Silver Denarius', 115, 'Roman Empire',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Historical Vault'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Coin')),
('Abstract View', 2024, 'Contemporary',
    (SELECT hall_id FROM museum_network.halls WHERE name = 'Modern Art Wing'),
    (SELECT type_id FROM museum_network.artifact_types WHERE type_name = 'Photography'));

-- 5. Insert Exhibitions
INSERT INTO museum_network.exhibitions (name, start_date, end_date) VALUES
('Treasures of Rome', '2026-05-01', '2026-08-30'),
('Renaissance Masters', '2026-06-01', '2026-09-15'),
('Ancient Secrets', '2026-04-01', '2026-07-20'),
('Modern Visions', '2026-07-01', '2026-12-01'),
('Medieval Life', '2026-05-15', '2026-11-15'),
('The Golden Age', '2026-08-01', '2026-12-31');

-- 6. Insert Exhibition_Items (Many-to-Many Bridge)
INSERT INTO museum_network.exhibition_items (exhibition_id, exhibit_id) VALUES
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Renaissance Masters'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'Mona Lisa')),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Ancient Secrets'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'Rosetta Stone')),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Medieval Life'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'Knight Armor')),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Treasures of Rome'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'Silver Denarius')),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Modern Visions'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'Abstract View')),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Renaissance Masters'),
 (SELECT exhibit_id FROM museum_network.exhibits WHERE title = 'David Statue'));

-- 7. Insert Ticket Prices
INSERT INTO museum_network.ticket_prices (exhibition_id, visitor_type, price) VALUES
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Treasures of Rome'), 'Adult', 250.00),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Treasures of Rome'), 'Student', 120.00),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Renaissance Masters'), 'Adult', 300.00),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Ancient Secrets'), 'Child', 50.00),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Modern Visions'), 'Senior', 150.00),
((SELECT exhibition_id FROM museum_network.exhibitions WHERE name = 'Medieval Life'), 'Adult', 200.00);

-- 8. Insert Tickets (Transactions for the last 3 months/future 2026 context)
INSERT INTO museum_network.tickets (price_id, staff_id, purchase_date) VALUES
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Treasures of Rome' AND tp.visitor_type = 'Adult'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 'o.dovzhenko@museum.com'), '2026-05-10 10:30:00'),
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Renaissance Masters' AND tp.visitor_type = 'Adult'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 'o.pchilka@museum.com'), '2026-06-12 11:45:00'),
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Ancient Secrets' AND tp.visitor_type = 'Child'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 't.shevchenko@museum.com'), '2026-04-15 14:20:00'),
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Modern Visions' AND tp.visitor_type = 'Senior'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 'o.dovzhenko@museum.com'), '2026-07-05 09:15:00'),
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Medieval Life' AND tp.visitor_type = 'Adult'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 'o.pchilka@museum.com'), '2026-05-20 16:40:00'),
((SELECT price_id FROM museum_network.ticket_prices tp JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id WHERE e.name = 'Treasures of Rome' AND tp.visitor_type = 'Student'),
 (SELECT staff_id FROM museum_network.staff WHERE email = 't.shevchenko@museum.com'), '2026-05-11 12:00:00');


-- TASK 5: FUNCTIONS
/*
-- 5.1: Universal Update Function
-- This function allows updating any column in the 'staff' table dynamically.
It uses PL/pgSQL 'EXECUTE' to handle column names as identifiers safely.
*/

CREATE OR REPLACE FUNCTION museum_network.update_staff_data(
    p_staff_id INT,
    p_column_name TEXT,
    p_new_value TEXT
)
RETURNS TEXT AS $$
BEGIN
    -- Uses dynamic SQL to update a specific column without hardcoding
    EXECUTE format('UPDATE museum_network.staff SET %I = $1 WHERE staff_id = $2', p_column_name)
    USING p_new_value, p_staff_id;

    RETURN 'Success: Staff ID ' || p_staff_id || ' updated (' || p_column_name || ')';
EXCEPTION
    WHEN OTHERS THEN
        RETURN 'Error: ' || SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- TEST the Update FUCTION
-- Let's change Nadiya's position to 'Senior Curator'
SELECT museum_network.update_staff_data(1, 'position', 'Senior Curator');
-- Verify the change in the Staff table
SELECT * FROM museum_network.staff WHERE staff_id = 1;


-- 5.2: Transaction Function (Ticket Sale)
-- Automates ticket insertion by resolving Natural Keys (names/emails) into IDs.
-- This prevents hardcoding and ensures data integrity through internal lookups.
CREATE OR REPLACE FUNCTION museum_network.sell_ticket(
    p_exhibition_name TEXT,
    p_visitor_type TEXT,
    p_staff_email TEXT
)
RETURNS TEXT AS $$
DECLARE
    v_price_id INT;
    v_staff_id INT;
BEGIN
    -- Resolve price_id using exhibition name and category
    SELECT tp.price_id INTO v_price_id
    FROM museum_network.ticket_prices tp
    JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id
    WHERE e.name = p_exhibition_name AND tp.visitor_type = p_visitor_type;

    -- Resolve staff_id using unique email
    SELECT staff_id INTO v_staff_id
    FROM museum_network.staff
    WHERE email = p_staff_email;

    -- Validation check before insertion
    IF v_price_id IS NULL OR v_staff_id IS NULL THEN
        RAISE EXCEPTION 'Lookup failed: Check names and emails.';
    END IF;

    -- Record the transaction
    INSERT INTO museum_network.tickets (price_id, staff_id, purchase_date)
    VALUES (v_price_id, v_staff_id, CURRENT_TIMESTAMP);

    RETURN 'Success: Ticket sold for ' || p_exhibition_name;
END;
$$ LANGUAGE plpgsql;

-- TEST the Ticket Sale FUNCTION (Anti-hardcoding check)
-- We sell an 'Adult' ticket for 'Treasures of Rome' using a staff email.
SELECT museum_network.sell_ticket('Treasures of Rome', 'Adult', 'o.dovzhenko@museum.com');
-- Verify the transaction by joining tables to see human-readable names
SELECT
    t.ticket_id,
    e.name AS exhibition,
    tp.visitor_type,
    s.first_name AS sold_by,
    t.purchase_date
FROM museum_network.tickets t
JOIN museum_network.ticket_prices tp ON t.price_id = tp.price_id
JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id
JOIN museum_network.staff s ON t.staff_id = s.staff_id
ORDER BY t.purchase_date DESC
LIMIT 1;



-- TASK 6: ANALYTICS VIEW

-- This view provides a business-ready summary of sales and revenue.
-- It filters data for the current quarter and hides all technical ID fields.
CREATE OR REPLACE VIEW museum_network.v_quarterly_sales_performance AS
SELECT
    e.name AS exhibition_title,
    tp.visitor_type AS category,
    COUNT(t.ticket_id) AS total_tickets_sold,
    SUM(tp.price) AS total_revenue,
    MIN(t.purchase_date)::DATE AS period_start,
    MAX(t.purchase_date)::DATE AS period_end
FROM museum_network.tickets t
JOIN museum_network.ticket_prices tp ON t.price_id = tp.price_id
JOIN museum_network.exhibitions e ON tp.exhibition_id = e.exhibition_id
WHERE t.purchase_date >= DATE_TRUNC('quarter', CURRENT_DATE)
GROUP BY e.name, tp.visitor_type
ORDER BY total_revenue DESC;

-- To check the result:
-- SELECT * FROM museum_network.v_quarterly_sales_performance;



-- TASK 7: SECURITY AND ROLES

-- Creating a dedicated role for museum management with read-only access.
-- This ensures that business users cannot accidentally modify or delete data.
DO $$
BEGIN
    -- Check if role exists to keep the script rerunnable
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'museum_manager') THEN
        CREATE ROLE museum_manager WITH LOGIN PASSWORD 'SecureMuseumAdmin2026';
    END IF;
END $$;

-- Granting access to the specific schema
GRANT USAGE ON SCHEMA museum_network TO museum_manager;

-- Granting read-only permissions on all existing tables and views
GRANT SELECT ON ALL TABLES IN SCHEMA museum_network TO museum_manager;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA museum_network TO museum_manager;

-- Ensuring the manager will have access to any tables created in the future
ALTER DEFAULT PRIVILEGES IN SCHEMA museum_network
GRANT SELECT ON TABLES TO museum_manager;
