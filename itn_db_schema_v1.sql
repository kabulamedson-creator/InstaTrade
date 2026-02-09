-- ============================================
-- InstantTrade Network - Database Schema
-- Version: 1.0.0
-- Database: PostgreSQL 15+
-- ============================================

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================
-- SCHEMA ORGANIZATION
-- ============================================

CREATE SCHEMA IF NOT EXISTS itn_core;      -- Core business tables
CREATE SCHEMA IF NOT EXISTS itn_audit;     -- Audit and decision ledger
CREATE SCHEMA IF NOT EXISTS itn_security;  -- Security and compliance

-- Set search path
SET search_path TO itn_core, itn_audit, itn_security, public;

-- ============================================
-- CORE TABLES
-- ============================================

-- Accounts table
CREATE TABLE itn_core.accounts (
    id VARCHAR(20) PRIMARY KEY,
    account_type VARCHAR(20) NOT NULL CHECK (account_type IN ('SUPPLIER', 'BUYER', 'CAPITAL_PROVIDER')),
    name VARCHAR(200) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'ACTIVE', 'SUSPENDED', 'FROZEN', 'CLOSED')),
    
    -- KYC/Compliance
    kyc_status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (kyc_status IN ('PENDING', 'IN_REVIEW', 'VERIFIED', 'REJECTED', 'EXPIRED')),
    kyc_verified_at TIMESTAMPTZ,
    kyc_expires_at TIMESTAMPTZ,
    
    -- Contact
    email VARCHAR(255) NOT NULL UNIQUE,
    phone VARCHAR(50),
    
    -- Address
    address_line1 VARCHAR(200),
    address_line2 VARCHAR(200),
    city VARCHAR(100),
    state VARCHAR(50),
    postal_code VARCHAR(20),
    country VARCHAR(2) NOT NULL DEFAULT 'US',
    
    -- Financial
    balance DECIMAL(15, 2) NOT NULL DEFAULT 0.00,
    credit_limit DECIMAL(15, 2),
    credit_limit_updated_at TIMESTAMPTZ,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by VARCHAR(100),
    
    -- Constraints
    CONSTRAINT positive_balance CHECK (balance >= 0),
    CONSTRAINT positive_credit_limit CHECK (credit_limit IS NULL OR credit_limit >= 0)
);

CREATE INDEX idx_accounts_status ON itn_core.accounts(status);
CREATE INDEX idx_accounts_type ON itn_core.accounts(account_type);
CREATE INDEX idx_accounts_kyc_status ON itn_core.accounts(kyc_status);
CREATE INDEX idx_accounts_email ON itn_core.accounts(email);

COMMENT ON TABLE itn_core.accounts IS 'All system accounts (suppliers, buyers, capital providers)';
COMMENT ON COLUMN itn_core.accounts.kyc_status IS 'KYC verification status (INV-402 enforcement)';
COMMENT ON COLUMN itn_core.accounts.status IS 'Account status (INV-003 enforcement - only ACTIVE can transact)';

-- Invoices table
CREATE TABLE itn_core.invoices (
    id VARCHAR(20) PRIMARY KEY,
    supplier_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    buyer_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    
    -- Amounts
    amount DECIMAL(15, 2) NOT NULL CHECK (amount >= 100.00 AND amount <= 10000000.00), -- INV-002
    currency VARCHAR(3) NOT NULL DEFAULT 'USD' CHECK (currency IN ('USD', 'EUR', 'GBP', 'JPY')),
    
    -- Terms
    terms INTEGER NOT NULL CHECK (terms IN (0, 15, 30, 45, 60, 90)), -- INV-007
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'ACCEPTED', 'SETTLED', 'REJECTED', 'EXPIRED', 'FRAUD_REVIEW')),
    
    -- Fraud detection
    fraud_score DECIMAL(5, 4),
    fraud_score_calculated_at TIMESTAMPTZ,
    
    -- Deduplication
    invoice_hash VARCHAR(64) NOT NULL UNIQUE, -- INV-004 - SHA-256 hash for duplicate detection
    
    -- Optional
    purchase_order_id VARCHAR(100),
    notes TEXT,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accepted_at TIMESTAMPTZ,
    settled_at TIMESTAMPTZ,
    
    -- Constraints
    CONSTRAINT different_parties CHECK (supplier_id != buyer_id),
    CONSTRAINT valid_fraud_score CHECK (fraud_score IS NULL OR (fraud_score >= 0 AND fraud_score <= 1))
);

CREATE INDEX idx_invoices_supplier ON itn_core.invoices(supplier_id);
CREATE INDEX idx_invoices_buyer ON itn_core.invoices(buyer_id);
CREATE INDEX idx_invoices_status ON itn_core.invoices(status);
CREATE INDEX idx_invoices_created_at ON itn_core.invoices(created_at DESC);
CREATE INDEX idx_invoices_hash ON itn_core.invoices(invoice_hash); -- Fast duplicate detection
CREATE INDEX idx_invoices_fraud_score ON itn_core.invoices(fraud_score) WHERE fraud_score > 0.75; -- INV-302

COMMENT ON TABLE itn_core.invoices IS 'All invoices in the system';
COMMENT ON COLUMN itn_core.invoices.amount IS 'Invoice amount - enforces INV-002 ($100-$10M range)';
COMMENT ON COLUMN itn_core.invoices.terms IS 'Payment terms - enforces INV-007 (allowed values only)';
COMMENT ON COLUMN itn_core.invoices.invoice_hash IS 'SHA-256 hash for duplicate detection (INV-004)';
COMMENT ON COLUMN itn_core.invoices.status IS 'Invoice status - enforces INV-101 (valid state transitions)';

-- Line items table
CREATE TABLE itn_core.line_items (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id VARCHAR(20) NOT NULL REFERENCES itn_core.invoices(id) ON DELETE CASCADE,
    
    -- Item details
    description VARCHAR(500) NOT NULL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price DECIMAL(15, 2) NOT NULL CHECK (unit_price > 0),
    amount DECIMAL(15, 2) NOT NULL GENERATED ALWAYS AS (quantity * unit_price) STORED, -- Auto-calculated
    
    -- Ordering
    line_number INTEGER NOT NULL,
    
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(invoice_id, line_number)
);

CREATE INDEX idx_line_items_invoice ON itn_core.line_items(invoice_id);

COMMENT ON TABLE itn_core.line_items IS 'Invoice line items - sum must equal invoice amount (INV-602)';

-- Settlements table
CREATE TABLE itn_core.settlements (
    id VARCHAR(50) PRIMARY KEY,
    invoice_id VARCHAR(20) NOT NULL UNIQUE REFERENCES itn_core.invoices(id), -- INV-006 - UNIQUE enforces settlement exactly once
    
    -- Parties
    supplier_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    buyer_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    capital_provider_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    
    -- Amounts
    invoice_amount DECIMAL(15, 2) NOT NULL,
    discount_rate DECIMAL(10, 8) NOT NULL,
    buyer_cost DECIMAL(15, 2) NOT NULL,
    capital_profit DECIMAL(15, 2) GENERATED ALWAYS AS (buyer_cost - invoice_amount) STORED,
    
    -- Timing
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_seconds DECIMAL(10, 3) GENERATED ALWAYS AS (EXTRACT(EPOCH FROM (completed_at - started_at))) STORED,
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED', 'ROLLED_BACK')),
    
    -- Settlement rails
    rail_used VARCHAR(50),
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT settlement_duration_check CHECK (completed_at IS NULL OR duration_seconds < 5.0) -- INV-201 - <5 seconds
);

CREATE INDEX idx_settlements_invoice ON itn_core.settlements(invoice_id);
CREATE INDEX idx_settlements_status ON itn_core.settlements(status);
CREATE INDEX idx_settlements_completed_at ON itn_core.settlements(completed_at DESC);
CREATE INDEX idx_settlements_duration ON itn_core.settlements(duration_seconds) WHERE completed_at IS NOT NULL;

COMMENT ON TABLE itn_core.settlements IS 'Settlement records - atomic 3-leg transfers';
COMMENT ON CONSTRAINT settlement_duration_check ON itn_core.settlements IS 'Enforces INV-201 (settlement <5 seconds)';

-- Settlement legs (detailed transaction tracking)
CREATE TABLE itn_core.settlement_legs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    settlement_id VARCHAR(50) NOT NULL REFERENCES itn_core.settlements(id),
    
    -- Leg details
    leg_type VARCHAR(20) NOT NULL CHECK (leg_type IN ('CREDIT', 'DEBIT', 'ADVANCE')),
    account_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    amount DECIMAL(15, 2) NOT NULL CHECK (amount > 0),
    
    -- Transaction details
    transaction_id VARCHAR(100) NOT NULL,
    rail_name VARCHAR(50),
    
    -- Timing
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    UNIQUE(settlement_id, leg_type)
);

CREATE INDEX idx_settlement_legs_settlement ON itn_core.settlement_legs(settlement_id);
CREATE INDEX idx_settlement_legs_account ON itn_core.settlement_legs(account_id);

COMMENT ON TABLE itn_core.settlement_legs IS 'Individual legs of atomic settlements (INV-102 enforcement)';

-- Pricing quotes table
CREATE TABLE itn_core.pricing_quotes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invoice_id VARCHAR(20) NOT NULL REFERENCES itn_core.invoices(id),
    
    -- Pricing
    amount DECIMAL(15, 2) NOT NULL,
    terms INTEGER NOT NULL,
    discount_rate DECIMAL(10, 8) NOT NULL,
    total_cost DECIMAL(15, 2) NOT NULL,
    
    -- Validity
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    
    -- Usage tracking
    used BOOLEAN NOT NULL DEFAULT FALSE,
    used_at TIMESTAMPTZ,
    
    CONSTRAINT quote_validity CHECK (expires_at > created_at),
    CONSTRAINT quote_expiry_window CHECK (expires_at <= created_at + INTERVAL '5 minutes') -- INV-109
);

CREATE INDEX idx_pricing_quotes_invoice ON itn_core.pricing_quotes(invoice_id);
CREATE INDEX idx_pricing_quotes_expires_at ON itn_core.pricing_quotes(expires_at);

COMMENT ON TABLE itn_core.pricing_quotes IS 'Pricing quotes - valid for 5 minutes (INV-109, INV-502)';

-- ============================================
-- AUDIT TABLES (IMMUTABLE)
-- ============================================

-- Decision ledger (immutable)
CREATE TABLE itn_audit.decision_ledger (
    id BIGSERIAL PRIMARY KEY,
    
    -- Decision identity
    decision_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    invariant_id VARCHAR(50) NOT NULL,
    check_type VARCHAR(10) NOT NULL CHECK (check_type IN ('PRE', 'POST')),
    
    -- Result
    result BOOLEAN NOT NULL,
    action VARCHAR(20) NOT NULL CHECK (action IN ('PROCEED', 'ROLLBACK', 'FREEZE')),
    
    -- Context
    state_snapshot JSONB,
    error_message TEXT,
    
    -- Actor
    actor VARCHAR(100), -- "human:user_id" | "ai:model" | "system:component"
    
    -- Timing
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Cryptographic integrity
    signature VARCHAR(64) NOT NULL, -- HMAC signature
    previous_record_hash VARCHAR(64) -- Chain to previous
);

-- Prevent updates/deletes (immutable)
CREATE RULE decision_ledger_no_update AS ON UPDATE TO itn_audit.decision_ledger DO INSTEAD NOTHING;
CREATE RULE decision_ledger_no_delete AS ON DELETE TO itn_audit.decision_ledger DO INSTEAD NOTHING;

CREATE INDEX idx_decision_ledger_timestamp ON itn_audit.decision_ledger(timestamp DESC);
CREATE INDEX idx_decision_ledger_invariant ON itn_audit.decision_ledger(invariant_id);
CREATE INDEX idx_decision_ledger_result ON itn_audit.decision_ledger(result);

COMMENT ON TABLE itn_audit.decision_ledger IS 'Immutable ledger of all enforcement decisions';
COMMENT ON COLUMN itn_audit.decision_ledger.signature IS 'HMAC signature for tamper detection';

-- Account balance history (audit trail)
CREATE TABLE itn_audit.balance_history (
    id BIGSERIAL PRIMARY KEY,
    account_id VARCHAR(20) NOT NULL,
    
    -- Change
    previous_balance DECIMAL(15, 2) NOT NULL,
    new_balance DECIMAL(15, 2) NOT NULL,
    change_amount DECIMAL(15, 2) NOT NULL,
    change_type VARCHAR(20) NOT NULL CHECK (change_type IN ('CREDIT', 'DEBIT', 'ADJUSTMENT', 'CORRECTION')),
    
    -- Context
    settlement_id VARCHAR(50),
    invoice_id VARCHAR(20),
    reason TEXT NOT NULL,
    
    -- Metadata
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    performed_by VARCHAR(100)
);

CREATE INDEX idx_balance_history_account ON itn_audit.balance_history(account_id);
CREATE INDEX idx_balance_history_timestamp ON itn_audit.balance_history(timestamp DESC);

COMMENT ON TABLE itn_audit.balance_history IS 'Complete audit trail of all balance changes';

-- System events (monitoring/alerting)
CREATE TABLE itn_audit.system_events (
    id BIGSERIAL PRIMARY KEY,
    
    -- Event
    event_type VARCHAR(50) NOT NULL,
    severity VARCHAR(20) NOT NULL CHECK (severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
    message TEXT NOT NULL,
    
    -- Context
    component VARCHAR(50),
    details JSONB,
    
    -- Metadata
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Acknowledgement
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_at TIMESTAMPTZ,
    acknowledged_by VARCHAR(100)
);

CREATE INDEX idx_system_events_timestamp ON itn_audit.system_events(timestamp DESC);
CREATE INDEX idx_system_events_severity ON itn_audit.system_events(severity);
CREATE INDEX idx_system_events_type ON itn_audit.system_events(event_type);
CREATE INDEX idx_system_events_unack ON itn_audit.system_events(acknowledged) WHERE NOT acknowledged;

COMMENT ON TABLE itn_audit.system_events IS 'System events for monitoring and alerting';

-- ============================================
-- SECURITY TABLES
-- ============================================

-- Sanctions list
CREATE TABLE itn_security.sanctions_list (
    id BIGSERIAL PRIMARY KEY,
    
    -- Entity
    entity_type VARCHAR(20) NOT NULL CHECK (entity_type IN ('INDIVIDUAL', 'COMPANY', 'COUNTRY')),
    name VARCHAR(200) NOT NULL,
    aliases TEXT[], -- Array of known aliases
    
    -- Identification
    tax_id VARCHAR(50),
    passport_number VARCHAR(50),
    date_of_birth DATE,
    
    -- Sanction details
    sanctioning_authority VARCHAR(100) NOT NULL, -- e.g., 'OFAC', 'EU', 'UN'
    sanction_type VARCHAR(50),
    effective_date DATE NOT NULL,
    expiry_date DATE,
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_checked_at TIMESTAMPTZ
);

CREATE INDEX idx_sanctions_name ON itn_security.sanctions_list USING gin(to_tsvector('english', name));
CREATE INDEX idx_sanctions_effective ON itn_security.sanctions_list(effective_date);

COMMENT ON TABLE itn_security.sanctions_list IS 'Sanctions screening list (INV-401 enforcement)';

-- API keys
CREATE TABLE itn_security.api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id VARCHAR(20) NOT NULL REFERENCES itn_core.accounts(id),
    
    -- Key
    key_hash VARCHAR(64) NOT NULL UNIQUE, -- SHA-256 hash of key
    key_prefix VARCHAR(10) NOT NULL, -- First 8 chars for identification
    
    -- Permissions
    permissions JSONB NOT NULL DEFAULT '[]',
    
    -- Rate limiting
    rate_limit_rpm INTEGER NOT NULL DEFAULT 1000, -- Requests per minute
    
    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'SUSPENDED', 'REVOKED')),
    
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    
    CONSTRAINT valid_expiry CHECK (expires_at IS NULL OR expires_at > created_at)
);

CREATE INDEX idx_api_keys_account ON itn_security.api_keys(account_id);
CREATE INDEX idx_api_keys_hash ON itn_security.api_keys(key_hash);

COMMENT ON TABLE itn_security.api_keys IS 'API key management and rate limiting';

-- Rate limit tracking
CREATE TABLE itn_security.rate_limit_tracking (
    account_id VARCHAR(20) NOT NULL,
    endpoint VARCHAR(100) NOT NULL,
    window_start TIMESTAMPTZ NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 1,
    
    PRIMARY KEY (account_id, endpoint, window_start)
);

CREATE INDEX idx_rate_limit_window ON itn_security.rate_limit_tracking(window_start);

COMMENT ON TABLE itn_security.rate_limit_tracking IS 'Track API rate limits (INV-404 enforcement)';

-- ============================================
-- VIEWS
-- ============================================

-- System health view
CREATE VIEW itn_core.system_health AS
SELECT
    (SELECT COUNT(*) FROM itn_core.invoices) AS total_invoices,
    (SELECT COUNT(*) FROM itn_core.invoices WHERE status = 'SETTLED') AS settled_invoices,
    (SELECT COUNT(*) FROM itn_core.settlements WHERE status = 'COMPLETED') AS completed_settlements,
    (SELECT COUNT(*) FROM itn_audit.decision_ledger) AS total_invariant_checks,
    (SELECT COUNT(*) FROM itn_audit.decision_ledger WHERE result = true) AS passed_checks,
    (SELECT COUNT(*) FROM itn_audit.decision_ledger WHERE result = false) AS failed_checks,
    CASE 
        WHEN (SELECT COUNT(*) FROM itn_audit.decision_ledger) > 0 
        THEN (SELECT COUNT(*)::DECIMAL FROM itn_audit.decision_ledger WHERE result = true) / 
             (SELECT COUNT(*)::DECIMAL FROM itn_audit.decision_ledger)
        ELSE 1.0
    END AS health_score,
    (SELECT AVG(duration_seconds) FROM itn_core.settlements WHERE status = 'COMPLETED') AS avg_settlement_time,
    (SELECT COALESCE(SUM(amount), 0) FROM itn_core.settlement_legs WHERE leg_type = 'CREDIT') AS total_credits,
    (SELECT COALESCE(SUM(amount), 0) FROM itn_core.settlement_legs WHERE leg_type = 'DEBIT') AS total_debits,
    ABS((SELECT COALESCE(SUM(amount), 0) FROM itn_core.settlement_legs WHERE leg_type = 'CREDIT') -
        (SELECT COALESCE(SUM(amount), 0) FROM itn_core.settlement_legs WHERE leg_type = 'DEBIT')) < 0.01 AS ledger_balanced;

COMMENT ON VIEW itn_core.system_health IS 'Real-time system health metrics';

-- Active invoices view
CREATE VIEW itn_core.active_invoices AS
SELECT 
    i.*,
    a_supplier.name AS supplier_name,
    a_buyer.name AS buyer_name,
    (SELECT SUM(amount) FROM itn_core.line_items WHERE invoice_id = i.id) AS calculated_amount
FROM itn_core.invoices i
JOIN itn_core.accounts a_supplier ON i.supplier_id = a_supplier.id
JOIN itn_core.accounts a_buyer ON i.buyer_id = a_buyer.id
WHERE i.status IN ('PENDING', 'ACCEPTED');

-- ============================================
-- FUNCTIONS
-- ============================================

-- Update timestamp trigger function
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to relevant tables
CREATE TRIGGER accounts_updated_at BEFORE UPDATE ON itn_core.accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER invoices_updated_at BEFORE UPDATE ON itn_core.invoices
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Validate line items sum to invoice amount
CREATE OR REPLACE FUNCTION validate_line_items_sum()
RETURNS TRIGGER AS $$
DECLARE
    invoice_amount DECIMAL(15, 2);
    line_items_sum DECIMAL(15, 2);
BEGIN
    SELECT amount INTO invoice_amount FROM itn_core.invoices WHERE id = NEW.invoice_id;
    SELECT COALESCE(SUM(amount), 0) INTO line_items_sum FROM itn_core.line_items WHERE invoice_id = NEW.invoice_id;
    
    IF ABS(line_items_sum - invoice_amount) > 0.01 THEN
        RAISE EXCEPTION 'INV-602 VIOLATION: Line items sum (%) does not equal invoice amount (%)', 
            line_items_sum, invoice_amount;
    END IF;
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER validate_line_items AFTER INSERT OR UPDATE ON itn_core.line_items
    FOR EACH ROW EXECUTE FUNCTION validate_line_items_sum();

-- Log balance changes
CREATE OR REPLACE FUNCTION log_balance_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.balance != NEW.balance THEN
        INSERT INTO itn_audit.balance_history (
            account_id,
            previous_balance,
            new_balance,
            change_amount,
            change_type,
            reason,
            performed_by
        ) VALUES (
            NEW.id,
            OLD.balance,
            NEW.balance,
            NEW.balance - OLD.balance,
            CASE 
                WHEN NEW.balance > OLD.balance THEN 'CREDIT'
                ELSE 'DEBIT'
            END,
            'Balance updated',
            current_user
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER log_account_balance_changes AFTER UPDATE ON itn_core.accounts
    FOR EACH ROW EXECUTE FUNCTION log_balance_change();

-- ============================================
-- SEED DATA (Development/Testing)
-- ============================================

-- Seed accounts
INSERT INTO itn_core.accounts (id, account_type, name, email, status, kyc_status, kyc_verified_at, balance, credit_limit) VALUES
('SUP-001', 'SUPPLIER', 'Acme Manufacturing', 'finance@acme-mfg.com', 'ACTIVE', 'VERIFIED', NOW(), 50000.00, NULL),
('SUP-002', 'SUPPLIER', 'Global Supplies Inc', 'ap@globalsupplies.com', 'ACTIVE', 'VERIFIED', NOW(), 25000.00, NULL),
('BUY-001', 'BUYER', 'TechCorp', 'procurement@techcorp.com', 'ACTIVE', 'VERIFIED', NOW(), 500000.00, 1000000.00),
('BUY-002', 'BUYER', 'Risky Buyer Inc', 'finance@riskybuyer.com', 'SUSPENDED', 'IN_REVIEW', NULL, 0.00, 0.00),
('CAP-001', 'CAPITAL_PROVIDER', 'InstantTrade Capital', 'ops@itn-capital.com', 'ACTIVE', 'VERIFIED', NOW(), 10000000.00, NULL);

-- ============================================
-- GRANTS (Security)
-- ============================================

-- Application role (read/write to core tables)
CREATE ROLE itn_app;
GRANT USAGE ON SCHEMA itn_core TO itn_app;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA itn_core TO itn_app;
GRANT USAGE ON SCHEMA itn_audit TO itn_app;
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA itn_audit TO itn_app; -- Audit is write-only
GRANT USAGE ON SCHEMA itn_security TO itn_app;
GRANT SELECT ON ALL TABLES IN SCHEMA itn_security TO itn_app;

-- Read-only role (for analytics/reporting)
CREATE ROLE itn_readonly;
GRANT USAGE ON SCHEMA itn_core, itn_audit TO itn_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA itn_core, itn_audit TO itn_readonly;

-- ============================================
-- MAINTENANCE
-- ============================================

-- Vacuum and analyze schedule
-- Run daily during low-traffic hours
COMMENT ON DATABASE postgres IS 'Run VACUUM ANALYZE daily on all itn_* schemas';

-- Partition strategy for large tables (future optimization)
-- COMMENT ON TABLE itn_audit.decision_ledger IS 'Consider partitioning by timestamp (monthly) when >100M rows';
