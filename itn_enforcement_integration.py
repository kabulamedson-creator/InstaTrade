"""
InstantTrade Network - Enforcement Layer Integration
Re-exports enforcement components for API usage
"""

# Import all enforcement components from itn_enforcement_v1
from itn_enforcement_v1 import (
    # Core enforcement
    Invariant,
    InvariantType,
    Criticality,
    InvariantEnforcer,
    DecisionLedger,
    EnforcementDecision,
    EnforcementResult,
    
    # Exceptions
    InvariantViolation,
    SystemCompromised,
    CircuitBreakerOpen,
    SettlementFailed,
    
    # State invariants
    UniqueInvoiceIDs,
    ValidInvoiceAmounts,
    AccountStatusActive,
    NoDuplicateInvoiceHash,
    CreditLimitNotExceeded,
    SettlementExactlyOnce,
    ValidPaymentTerms,
    
    # Transition invariants
    ValidStatusTransitions,
    AtomicSettlementTransition,
    
    # Temporal invariants
    SettlementWithin5Seconds,
    FraudScoreFresh,
    
    # Security invariants
    SanctionsListCheck,
    
    # Financial invariants
    LedgerBalanceReconciliation,
    PricingAccuracy,
    
    # Logging
    logger
)

# Import from itn_remaining_invariants_v1
from itn_remaining_invariants_v1 import (
    # Additional transition invariants
    PricingQuoteBeforeAcceptance,
    BuyerAuthorizationOnly,
    NoRetroactiveStatusChanges,
    
    # Additional temporal invariants
    BuyerAcceptanceDeadline,
    FXRateFreshness,
    CreditLimitStaleness,
    SettlementRailHealthCheck,
    CapitalBidExpiry,
    
    # Probabilistic invariants
    CapitalCompetitionRate,
    FraudDetectionAccuracy,
    SettlementSuccessRate,
    
    # Additional security invariants
    VerifiedAccountRequired,
    CryptographicSignatureRequired,
    RateLimiting,
    
    # Additional financial invariants
    CapitalProviderLiquidity,
    
    # Data integrity invariants
    ImmutableLedger,
    LineItemsSumToTotal,
    PricingQuoteFreshness
)

# Import mock services (in production, these would be real implementations)
from itn_invoice_service_v1 import InvoiceStorage, AccountService
from itn_settlement_service_v1 import (
    SettlementLedger,
    SettlementRailManager,
    BalanceService
)

__all__ = [
    # Core classes
    'Invariant',
    'InvariantType',
    'Criticality',
    'InvariantEnforcer',
    'DecisionLedger',
    'EnforcementDecision',
    'EnforcementResult',
    
    # Exceptions
    'InvariantViolation',
    'SystemCompromised',
    'CircuitBreakerOpen',
    'SettlementFailed',
    
    # All invariants (30 total)
    'UniqueInvoiceIDs',
    'ValidInvoiceAmounts',
    'AccountStatusActive',
    'NoDuplicateInvoiceHash',
    'CreditLimitNotExceeded',
    'SettlementExactlyOnce',
    'ValidPaymentTerms',
    'ValidStatusTransitions',
    'AtomicSettlementTransition',
    'PricingQuoteBeforeAcceptance',
    'BuyerAuthorizationOnly',
    'NoRetroactiveStatusChanges',
    'SettlementWithin5Seconds',
    'FraudScoreFresh',
    'BuyerAcceptanceDeadline',
    'FXRateFreshness',
    'CreditLimitStaleness',
    'SettlementRailHealthCheck',
    'CapitalBidExpiry',
    'CapitalCompetitionRate',
    'FraudDetectionAccuracy',
    'SettlementSuccessRate',
    'SanctionsListCheck',
    'VerifiedAccountRequired',
    'CryptographicSignatureRequired',
    'RateLimiting',
    'LedgerBalanceReconciliation',
    'PricingAccuracy',
    'CapitalProviderLiquidity',
    'ImmutableLedger',
    'LineItemsSumToTotal',
    'PricingQuoteFreshness',
    
    # Services
    'InvoiceStorage',
    'AccountService',
    'SettlementLedger',
    'SettlementRailManager',
    'BalanceService',
    
    # Logging
    'logger'
]
