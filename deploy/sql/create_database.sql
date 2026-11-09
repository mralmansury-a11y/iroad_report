-- MariaDB: dedicated database and least-privilege user for International Road Services – Libya
-- Run as an administrative MariaDB account (e.g. `sudo mariadb`) — the APPLICATION never uses root.
-- Replace CHANGE_ME_STRONG_PASSWORD (generate with: openssl rand -base64 32 | tr -d '/+=' | cut -c1-32).
-- Safe on an existing server: only creates objects named irs_road / irs_app (IF NOT EXISTS).

CREATE DATABASE IF NOT EXISTS irs_road
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'irs_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';

-- Runtime + migrations (DDL needed by Flask-Migrate) on THIS database only.
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES, CREATE TEMPORARY TABLES, LOCK TABLES
  ON irs_road.* TO 'irs_app'@'localhost';

-- Optional hardening: split migrations and runtime into two accounts.
-- CREATE USER IF NOT EXISTS 'irs_runtime'@'localhost' IDENTIFIED BY '...';
-- GRANT SELECT, INSERT, UPDATE, DELETE ON irs_road.* TO 'irs_runtime'@'localhost';

-- Backup account (read-only + consistent dump)
CREATE USER IF NOT EXISTS 'irs_backup'@'localhost' IDENTIFIED BY 'CHANGE_ME_BACKUP_PASSWORD';
GRANT SELECT, LOCK TABLES, SHOW VIEW, EVENT, TRIGGER ON irs_road.* TO 'irs_backup'@'localhost';

FLUSH PRIVILEGES;
