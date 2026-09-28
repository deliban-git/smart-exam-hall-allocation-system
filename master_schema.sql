-- Master / control database - Smart Exam Hall Allocation System (multi-tenant)
--
-- This lives in the ONE database named by MYSQL_DATABASE in your .env /
-- Render environment variables. It is the central registry of every COE
-- (Controller of Examination) account that has signed up. Each row's
-- `db_name` column points at that COE's own, fully isolated tenant
-- database (created automatically by db.provision_tenant_db() the moment
-- someone signs up - see db.py and app.py's /signup route).
--
-- IMPORTANT: unlike schema.sql (the per-tenant schema, which is run fresh
-- against a brand-new, empty database for every sign-up), this file is
-- safe to run again at any time - it uses CREATE TABLE IF NOT EXISTS, so
-- running `python db.py` a second time will NEVER drop or wipe your
-- already-registered COE accounts.

CREATE TABLE IF NOT EXISTS tenants (
    id                INT AUTO_INCREMENT PRIMARY KEY,
    username          VARCHAR(50) UNIQUE NOT NULL,
    full_name         VARCHAR(120),
    institution_name  VARCHAR(150) NOT NULL,
    password_hash     VARCHAR(255) NOT NULL,
    db_name           VARCHAR(80) UNIQUE NOT NULL,
    failed_attempts   INT NOT NULL DEFAULT 0,
    locked_until      DATETIME NULL,
    last_login_at     DATETIME NULL,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    KEY idx_tenants_institution (institution_name)
) ENGINE=InnoDB;

-- `username UNIQUE NOT NULL` above is what guarantees, at the database
-- level, that two sign-ups can never end up with the same username - even
-- if two requests race each other, MySQL itself rejects the second INSERT
-- (app.py catches that as db.IntegrityError and cleans up the tenant
-- database it had just created for that failed sign-up).
