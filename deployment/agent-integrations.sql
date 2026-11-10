-- Manual additive migration in the existing DPIA Agents MySQL database only.
-- Apply before starting this version of web/dispatcher/search/analysis workers.
-- No existing engine, user, provider, job, or result rows are altered.
CREATE TABLE ae_integrations (
  id VARCHAR(40) NOT NULL PRIMARY KEY,
  config JSON NOT NULL,
  credential_ciphertext TEXT NULL,
  enabled BOOLEAN NOT NULL DEFAULT FALSE,
  revision INT NOT NULL,
  diagnostic JSON NOT NULL,
  checked_at DATETIME NULL,
  last_success_at DATETIME NULL,
  updated_at DATETIME NOT NULL,
  CHECK (revision >= 1)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
CREATE TABLE ae_integration_audit (
  id VARCHAR(36) NOT NULL PRIMARY KEY,
  integration_id VARCHAR(40) NOT NULL,
  actor_id VARCHAR(120) NOT NULL,
  action VARCHAR(40) NOT NULL,
  revision INT NOT NULL,
  reason_code VARCHAR(80) NULL,
  created_at DATETIME NOT NULL,
  INDEX ix_ae_integration_audit_history (integration_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
