-- PostgreSQL database schema for InstaTrade

-- Table for accounts
CREATE TABLE accounts (
    account_id SERIAL PRIMARY KEY,
    account_name VARCHAR(100) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_account_name CHECK (account_name <> '')
);

-- Table for invoices
CREATE TABLE invoices (
    invoice_id SERIAL PRIMARY KEY,
    account_id INT REFERENCES accounts(account_id) ON DELETE CASCADE,
    amount DECIMAL(10, 2) NOT NULL,
    issue_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    due_date TIMESTAMP,
    status VARCHAR(50),
    CONSTRAINT chk_amount CHECK (amount >= 0)
);

-- Table for settlements
CREATE TABLE settlements (
    settlement_id SERIAL PRIMARY KEY,
    invoice_id INT REFERENCES invoices(invoice_id) ON DELETE CASCADE,
    settlement_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    amount DECIMAL(10, 2) NOT NULL,
    CONSTRAINT chk_settlement_amount CHECK (amount >= 0)
);

-- Table for pricing quotes
CREATE TABLE pricing_quotes (
    quote_id SERIAL PRIMARY KEY,
    account_id INT REFERENCES accounts(account_id) ON DELETE CASCADE,
    quote_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price DECIMAL(10, 2) NOT NULL,
    validity_period INTERVAL,
    CONSTRAINT chk_price CHECK (price >= 0)
);

-- Table for decision ledger
CREATE TABLE decision_ledger (
    decision_id SERIAL PRIMARY KEY,
    account_id INT REFERENCES accounts(account_id) ON DELETE CASCADE,
    decision_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    decision TEXT NOT NULL,
    outcome VARCHAR(100),
    CONSTRAINT chk_decision_text CHECK (decision <> '')
);

-- Indexes
CREATE INDEX idx_account_name ON accounts(account_name);
CREATE INDEX idx_invoice_due_date ON invoices(due_date);
CREATE INDEX idx_settlement_date ON settlements(settlement_date);
CREATE INDEX idx_quote_date ON pricing_quotes(quote_date);
CREATE INDEX idx_decision_date ON decision_ledger(decision_date);