"""
InstantTrade Network - Prometheus Metrics
Comprehensive observability for production monitoring
"""

from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry

# Create custom registry
metrics_registry = CollectorRegistry()

# ============================================
# BUSINESS METRICS
# ============================================

# Invoice metrics
invoice_created_counter = Counter(
    'itn_invoices_created_total',
    'Total number of invoices created',
    ['supplier_id', 'buyer_id'],
    registry=metrics_registry
)

invoice_accepted_counter = Counter(
    'itn_invoices_accepted_total',
    'Total number of invoices accepted',
    ['buyer_id'],
    registry=metrics_registry
)

invoice_rejected_counter = Counter(
    'itn_invoices_rejected_total',
    'Total number of invoices rejected',
    ['reason'],
    registry=metrics_registry
)

# Settlement metrics
settlement_completed_counter = Counter(
    'itn_settlements_completed_total',
    'Total number of settlements completed',
    ['supplier_id', 'buyer_id'],
    registry=metrics_registry
)

settlement_failed_counter = Counter(
    'itn_settlements_failed_total',
    'Total number of settlements failed',
    ['reason'],
    registry=metrics_registry
)

settlement_duration_histogram = Histogram(
    'itn_settlement_duration_seconds',
    'Settlement duration in seconds',
    buckets=[0.5, 1.0, 2.0, 3.0, 4.0, 5.0, 10.0],
    registry=metrics_registry
)

# Volume metrics
invoice_amount_histogram = Histogram(
    'itn_invoice_amount_dollars',
    'Invoice amounts in dollars',
    buckets=[100, 1000, 5000, 10000, 50000, 100000, 500000, 1000000, 10000000],
    registry=metrics_registry
)

total_volume_gauge = Gauge(
    'itn_total_volume_dollars',
    'Total transaction volume in dollars',
    registry=metrics_registry
)

# ============================================
# INVARIANT ENFORCEMENT METRICS
# ============================================

invariant_check_counter = Counter(
    'itn_invariant_checks_total',
    'Total number of invariant checks',
    ['invariant_id', 'check_type', 'result'],
    registry=metrics_registry
)

invariant_violation_counter = Counter(
    'itn_invariant_violations_total',
    'Total number of invariant violations',
    ['invariant_id', 'criticality'],
    registry=metrics_registry
)

rollback_counter = Counter(
    'itn_rollbacks_total',
    'Total number of rollbacks executed',
    ['reason'],
    registry=metrics_registry
)

# ============================================
# SYSTEM HEALTH METRICS
# ============================================

system_health_gauge = Gauge(
    'itn_system_health_score',
    'Overall system health score (0-1)',
    registry=metrics_registry
)

ledger_balance_gauge = Gauge(
    'itn_ledger_balance_variance_dollars',
    'Ledger balance variance (should be ~0)',
    registry=metrics_registry
)

ledger_integrity_gauge = Gauge(
    'itn_ledger_integrity',
    'Ledger chain integrity (1=verified, 0=compromised)',
    registry=metrics_registry
)

# ============================================
# PERFORMANCE METRICS
# ============================================

api_request_duration_histogram = Histogram(
    'itn_api_request_duration_seconds',
    'API request duration',
    ['endpoint', 'method'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
    registry=metrics_registry
)

api_request_counter = Counter(
    'itn_api_requests_total',
    'Total API requests',
    ['endpoint', 'method', 'status_code'],
    registry=metrics_registry
)

# Database metrics
db_query_duration_histogram = Histogram(
    'itn_db_query_duration_seconds',
    'Database query duration',
    ['query_type'],
    registry=metrics_registry
)

db_connection_pool_gauge = Gauge(
    'itn_db_connection_pool_size',
    'Database connection pool size',
    ['state'],  # active, idle
    registry=metrics_registry
)

# ============================================
# INFRASTRUCTURE METRICS
# ============================================

settlement_rail_health_gauge = Gauge(
    'itn_settlement_rail_health',
    'Settlement rail health status (1=up, 0=down)',
    ['rail_name'],
    registry=metrics_registry
)

settlement_rail_latency_histogram = Histogram(
    'itn_settlement_rail_latency_seconds',
    'Settlement rail latency',
    ['rail_name'],
    buckets=[0.1, 0.2, 0.5, 1.0, 2.0, 5.0],
    registry=metrics_registry
)

# ============================================
# FINANCIAL METRICS
# ============================================

capital_competition_rate_gauge = Gauge(
    'itn_capital_competition_rate',
    'Percentage of invoices with 3+ capital bids',
    registry=metrics_registry
)

average_discount_rate_gauge = Gauge(
    'itn_average_discount_rate',
    'Average discount rate across settlements',
    registry=metrics_registry
)

fraud_score_histogram = Histogram(
    'itn_fraud_score',
    'Distribution of fraud scores',
    buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.9, 1.0],
    registry=metrics_registry
)

# ============================================
# COMPLIANCE METRICS
# ============================================

kyc_verification_counter = Counter(
    'itn_kyc_verifications_total',
    'Total KYC verifications performed',
    ['result'],  # approved, rejected
    registry=metrics_registry
)

sanctions_check_counter = Counter(
    'itn_sanctions_checks_total',
    'Total sanctions list checks',
    ['result'],  # clear, blocked
    registry=metrics_registry
)

# ============================================
# HELPER FUNCTIONS
# ============================================

def record_invoice_created(supplier_id: str, buyer_id: str, amount: float):
    """Record invoice creation metrics."""
    invoice_created_counter.labels(
        supplier_id=supplier_id,
        buyer_id=buyer_id
    ).inc()
    invoice_amount_histogram.observe(amount)

def record_settlement_completed(supplier_id: str, buyer_id: str, duration: float, amount: float):
    """Record settlement completion metrics."""
    settlement_completed_counter.labels(
        supplier_id=supplier_id,
        buyer_id=buyer_id
    ).inc()
    settlement_duration_histogram.observe(duration)
    total_volume_gauge.inc(amount)

def record_invariant_check(invariant_id: str, check_type: str, result: bool):
    """Record invariant check metrics."""
    invariant_check_counter.labels(
        invariant_id=invariant_id,
        check_type=check_type,
        result="passed" if result else "failed"
    ).inc()
    
    if not result:
        # Assume CRITICAL for now - should pass actual criticality
        invariant_violation_counter.labels(
            invariant_id=invariant_id,
            criticality="CRITICAL"
        ).inc()

def update_system_health(health_score: float, ledger_variance: float, ledger_integrity: bool):
    """Update system health metrics."""
    system_health_gauge.set(health_score)
    ledger_balance_gauge.set(ledger_variance)
    ledger_integrity_gauge.set(1 if ledger_integrity else 0)

def record_api_request(endpoint: str, method: str, status_code: int, duration: float):
    """Record API request metrics."""
    api_request_counter.labels(
        endpoint=endpoint,
        method=method,
        status_code=status_code
    ).inc()
    api_request_duration_histogram.labels(
        endpoint=endpoint,
        method=method
    ).observe(duration)
