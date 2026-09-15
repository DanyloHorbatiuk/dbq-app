-- =============================================================================
-- museum_network — reference/dictionary data (SPEC.md §2.2.6): halls,
-- the 3-level artifact type hierarchy, and staff.
--
-- Halls and the type hierarchy are hand-curated, not randomly generated —
-- a museum's floor plan and classification scheme are things a curator
-- designs, not something to leave to random(). Staff is the one table
-- here that is actually generated (200 rows), so this file also calls
-- setseed(0.42): 07_generate_data.sql's own setseed call only covers its
-- own session (each NN_*.sql file is applied as a separate psql
-- invocation by 40_init_museum.sh), so reproducibility for the random()
-- calls below needs its own seed call here too.
--
-- Rerunnable via TRUNCATE ... RESTART IDENTITY CASCADE: 01_schema.sql's
-- DROP SCHEMA CASCADE already makes a full `make reset` rerunnable, but
-- this lets 06/07 be re-applied on their own while iterating, matching
-- how 02-05 are each independently rerunnable.
-- =============================================================================

-- audit_log is included on purpose, even though nothing here repopulates
-- it directly: fn_audit() writes to it as a side effect of the tickets/
-- ticket_prices inserts below and in 07_generate_data.sql, and without
-- truncating it here, a second `make seed` would leave the audit trail
-- from the previous generation mixed in with the new one instead of
-- reflecting a single clean run.
TRUNCATE museum_network.tour_bookings, museum_network.guided_tours,
         museum_network.restorations, museum_network.visitor_feedback,
         museum_network.tickets, museum_network.ticket_prices,
         museum_network.exhibition_items, museum_network.exhibitions,
         museum_network.exhibits, museum_network.staff,
         museum_network.artifact_types, museum_network.halls,
         museum_network.audit_log
    RESTART IDENTITY CASCADE;

SELECT setseed(0.42);

--------------------------------------------------------------------------------
-- Halls (20) — floors span the CHECK range (-1..10) the way a real museum
-- would use it: a basement vault, ground/upper galleries, no 20 identical
-- "Hall N" rows.
--------------------------------------------------------------------------------
INSERT INTO museum_network.halls (name, floor) VALUES
    ('Historical Vault',        -1),
    ('Ancient Egypt Room',       1),
    ('Renaissance Gallery',      1),
    ('Statue Court',             0),
    ('Medieval Armory',          2),
    ('Modern Art Wing',          2),
    ('Contemporary Pavilion',    3),
    ('Numismatics Cabinet',      0),
    ('Textile Gallery',          2),
    ('Photography Studio',       3),
    ('Natural History Hall',     1),
    ('Decorative Arts Room',     1),
    ('Baroque Gallery',          2),
    ('Asian Art Wing',           3),
    ('European Sculpture Court', 0),
    ('Archive & Manuscripts',   -1),
    ('Glass & Ceramics Room',    2),
    ('War & Peace Hall',         1),
    ('Discovery Gallery',        4),
    ('Grand Atrium',             0);

--------------------------------------------------------------------------------
-- Artifact types (40): 8 top-level domains, 19 subtypes, 13 leaf types —
-- a 3-level hierarchy for the recursive CTE query (SPEC.md §2.2.2/§3.2).
-- Each level looks its parent up by name (CLAUDE.md: no hardcoded IDs),
-- so this stays correct regardless of IDENTITY-assigned type_id values.
--------------------------------------------------------------------------------

-- Level 1 — 8 top-level domains.
INSERT INTO museum_network.artifact_types (type_name) VALUES
    ('Visual Arts'), ('Archaeology'), ('Decorative Arts'), ('Militaria'),
    ('Numismatics'), ('Photography & Media'), ('Natural History'),
    ('Textiles & Costume');

-- Level 2 — 19 subtypes.
INSERT INTO museum_network.artifact_types (type_name, parent_type_id)
SELECT v.child_name, p.type_id
FROM (VALUES
    ('Painting',              'Visual Arts'),
    ('Sculpture',             'Visual Arts'),
    ('Drawing & Printmaking',  'Visual Arts'),
    ('Ancient Pottery',       'Archaeology'),
    ('Stone Tools',           'Archaeology'),
    ('Funerary Artifacts',    'Archaeology'),
    ('Furniture',             'Decorative Arts'),
    ('Glassware',             'Decorative Arts'),
    ('Ceramics',              'Decorative Arts'),
    ('Armor & Weapons',       'Militaria'),
    ('Military Uniforms',     'Militaria'),
    ('Coins',                 'Numismatics'),
    ('Medals',                'Numismatics'),
    ('Photography',           'Photography & Media'),
    ('Film & Video',          'Photography & Media'),
    ('Minerals & Fossils',    'Natural History'),
    ('Taxidermy',             'Natural History'),
    ('Garments',              'Textiles & Costume'),
    ('Tapestries',            'Textiles & Costume')
) AS v(child_name, parent_name)
JOIN museum_network.artifact_types p ON p.type_name = v.parent_name;

-- Level 3 — 13 leaf types.
INSERT INTO museum_network.artifact_types (type_name, parent_type_id)
SELECT v.child_name, p.type_id
FROM (VALUES
    ('Oil Painting',        'Painting'),
    ('Watercolor Painting', 'Painting'),
    ('Marble Sculpture',    'Sculpture'),
    ('Bronze Sculpture',    'Sculpture'),
    ('Greek Pottery',       'Ancient Pottery'),
    ('Roman Pottery',       'Ancient Pottery'),
    ('Flint Tools',         'Stone Tools'),
    ('Antique Furniture',   'Furniture'),
    ('Stained Glass',       'Glassware'),
    ('Plate Armor',         'Armor & Weapons'),
    ('Edged Weapons',       'Armor & Weapons'),
    ('Ancient Coins',       'Coins'),
    ('Ceremonial Garments', 'Garments')
) AS v(child_name, parent_name)
JOIN museum_network.artifact_types p ON p.type_name = v.parent_name;

--------------------------------------------------------------------------------
-- Staff (200) — the one dictionary table actually generated: real museums
-- don't have 200 hand-named employees to enumerate. Positions are weighted
-- (cashiers and guides are the bulk of frontline staff, administrators are
-- rare), which is what later makes "different staff activity levels"
-- (SPEC.md §2.2.6) plausible once ticket sales are weighted by role too.
-- first_name/last_name/seq keeps every email unique even when the same
-- name pair is drawn twice.
--------------------------------------------------------------------------------
INSERT INTO museum_network.staff (first_name, last_name, email, position)
WITH name_pools AS (
    SELECT
        ARRAY['Olena','Ivan','Maria','Taras','Nadiya','Oleksandr','Sofia','Andriy',
              'Kateryna','Mykola','Anna','Yuriy','Iryna','Dmytro','Natalia','Petro',
              'Halyna','Vasyl','Oksana','Roman'] AS first_names,
        ARRAY['Shevchenko','Franko','Kovalenko','Bondarenko','Tkachenko','Kravchenko',
              'Oliynyk','Shevchuk','Polishchuk','Melnyk','Rudenko','Marchenko',
              'Savchenko','Boyko','Pavlenko','Lysenko','Moroz','Kozak','Zayats','Pchilka'] AS last_names
),
draws AS (
    SELECT
        gs AS seq,
        (first_names)[1 + floor(random() * array_length(first_names, 1))::int] AS first_name,
        (last_names)[1 + floor(random() * array_length(last_names, 1))::int] AS last_name,
        random() AS role_pick
    FROM generate_series(1, 200) AS gs, name_pools
)
SELECT
    first_name,
    last_name,
    lower(first_name || '.' || last_name || seq || '@museum.com'),
    CASE
        WHEN role_pick < 0.45 THEN 'Cashier'
        WHEN role_pick < 0.65 THEN 'Tour Guide'
        WHEN role_pick < 0.80 THEN 'Security'
        WHEN role_pick < 0.90 THEN 'Restorer'
        WHEN role_pick < 0.97 THEN 'Curator'
        ELSE 'Administrator'
    END
FROM draws;
