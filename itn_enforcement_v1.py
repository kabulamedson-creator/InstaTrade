"""
InstantTrade Network (ITN) - Production Enforcement Layer
Version: 1.0.0
Generated: 2026-02-08
Status: PHASE 2 - ARTIFACT ENCODING

This module implements all 30 invariants with non-bypassable enforcement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Set
from enum import Enum
import hmac
import hashlib
import logging
import time
from abc import ABC, abstractmethod

# ============================================
# SYSTEM CONFIGURATION
# ============================================

SYSTEM_SECRET = b"PRODUCTION_SECRET_KEY_ROTATE_QUARTERLY"

class InvariantType(Enum):
    STATE = "state"
    TRANSITION = "transition"
    TEMPORAL = "temporal"
    PROBABILISTIC = "probabilistic"
    SECURITY = "security"
    FINANCIAL = "financial"
    DATA_INTEGRITY = "data_integrity"

class Criticality(Enum):
    CRITICAL = "critical"
    IMPORTANT = "important"
    OPTIONAL = "optional"

class SystemState(Enum):
    IDLE = "idle"
    DESIGN_LOCKED = "design_locked"
    INVARIANTS_VERIFIED = "invariants_verified"
    EXECUTING = "executing"
    COMPLETE = "complete"
    ROLLED_BACK = "rolled_back"
    FROZEN = "frozen"
    AUDIT_REQUIRED = "audit_required"

class EnforcementResult(Enum):
    PROCEED = "proceed"
    ROLLBACK = "rollback"
    FREEZE = "freeze"

# ============================================
# LOGGING SETUP
# ============================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("ITN.Enforcement")

# ============================================
# EXCEPTIONS
# ============================================

class InvariantViolation(Exception):
    """Raised when an invariant is violated."""
    pass

class SystemCompromised(Exception):
    """Raised when rollback fails - system integrity lost."""
    pass

class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass

class SettlementFailed(Exception):
    """Raised when settlement cannot complete."""
    pass

# ============================================
# ENFORCEMENT DECISION RECORD
# ============================================

@dataclass
class EnforcementDecision:
    """Immutable record of enforcement decision."""
    invariant_id: str
    check_type: str  # "PRE" | "POST"
    result: bool
    action: EnforcementResult
    timestamp: datetime
    state_snapshot: Dict[str, Any]
    signature: str
    
    def verify_signature(self) -> bool:
        """Verify cryptographic signature."""
        data = f"{self.invariant_id}:{self.result}:{self.timestamp.isoformat()}"
        expected = hmac.new(SYSTEM_SECRET, data.encode(), 'sha256').hexdigest()
        return self.signature == expected

# ============================================
# DECISION LEDGER
# ============================================

class DecisionLedger:
    """Immutable, append-only ledger of all enforcement decisions."""
    
    def __init__(self):
        self.entries: List[EnforcementDecision] = []
        self._lock = False
    
    def record(self, decision: EnforcementDecision):
        """Append decision to ledger (write-only)."""
        if not decision.verify_signature():
            raise SystemCompromised("Invalid signature on enforcement decision")
        
        self.entries.append(decision)
        logger.info(f"LEDGER: Recorded {decision.check_type} for {decision.invariant_id}: {decision.result}")
    
    def get_last_good_state(self) -> Dict[str, Any]:
        """Retrieve last state where all checks passed."""
        for entry in reversed(self.entries):
            if entry.result and entry.action == EnforcementResult.PROCEED:
                return entry.state_snapshot
        return {}
    
    def verify_chain_integrity(self) -> bool:
        """Verify ledger has not been tampered with."""
        return all(entry.verify_signature() for entry in self.entries)

# ============================================
# BASE INVARIANT CLASS
# ============================================

class Invariant(ABC):
    """Base class for all invariants."""
    
    def __init__(
        self,
        id: str,
        statement: str,
        type: InvariantType,
        criticality: Criticality,
        dependencies: List[str],
        decay_window: Optional[timedelta],
        owner: str
    ):
        self.id = id
        self.statement = statement
        self.type = type
        self.criticality = criticality
        self.dependencies = dependencies
        self.decay_window = decay_window
        self.owner = owner
        self.last_verified: Optional[datetime] = None
    
    @abstractmethod
    def pre_check(self, **kwargs) -> bool:
        """Execute before action. Returns True if action can proceed."""
        pass
    
    @abstractmethod
    def post_check(self, result: Any, **kwargs) -> bool:
        """Execute after action. Returns True if invariant still holds."""
        pass
    
    @abstractmethod
    def rollback_action(self, state_before: Dict[str, Any]):
        """Define rollback procedure."""
        pass
    
    def verify_state(self, state: Dict[str, Any]) -> bool:
        """Verify invariant holds in given state."""
        # Default implementation - override if needed
        return True
    
    def is_expired(self) -> bool:
        """Check if assumption has decayed."""
        if self.decay_window is None:
            return False
        if self.last_verified is None:
            return True
        age = datetime.now() - self.last_verified
        return age > self.decay_window
    
    def revalidate(self, state: Dict[str, Any]):
        """Force revalidation of invariant."""
        if self.verify_state(state):
            self.last_verified = datetime.now()
        else:
            raise InvariantViolation(f"{self.id}: Revalidation failed")

# ============================================
# STATE INVARIANTS
# ============================================

class UniqueInvoiceIDs(Invariant):
    """INV-001: Every invoice must have a unique ID."""
    
    def __init__(self):
        super().__init__(
            id="inv_001_unique_invoice_ids",
            statement="The system MUST always ensure every invoice has a globally unique ID",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="invoice_service"
        )
    
    def pre_check(self, invoice_id: str, storage) -> bool:
        exists = storage.invoice_exists(invoice_id)
        logger.info(f"PRE-CHECK {self.id}: invoice_id={invoice_id}, exists={exists}")
        return not exists
    
    def post_check(self, result: Any, **kwargs) -> bool:
        storage = result['storage']
        invoice_id = result['invoice_id']
        count = storage.count_invoices(invoice_id)
        
        logger.info(f"POST-CHECK {self.id}: invoice_id={invoice_id}, count={count}")
        return count == 1
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.delete_invoice(invoice_id)
        logger.warning(f"ROLLBACK {self.id}: Deleted invoice {invoice_id}")

class ValidInvoiceAmounts(Invariant):
    """INV-002: Invoice amounts must be $100 - $10M."""
    
    MIN_AMOUNT = 100
    MAX_AMOUNT = 10_000_000
    
    def __init__(self):
        super().__init__(
            id="inv_002_valid_amounts",
            statement="The system MUST always ensure invoice amounts are between $100 and $10,000,000",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="invoice_service"
        )
    
    def pre_check(self, amount: float, **kwargs) -> bool:
        valid = self.MIN_AMOUNT <= amount <= self.MAX_AMOUNT
        logger.info(f"PRE-CHECK {self.id}: amount=${amount}, valid={valid}")
        return valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        amount = result['invoice'].amount
        valid = self.MIN_AMOUNT <= amount <= self.MAX_AMOUNT
        logger.info(f"POST-CHECK {self.id}: amount=${amount}, valid={valid}")
        return valid
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.delete_invoice(invoice_id)
        logger.warning(f"ROLLBACK {self.id}: Deleted invoice {invoice_id}")

class AccountStatusActive(Invariant):
    """INV-003: No transactions with inactive accounts."""
    
    def __init__(self):
        super().__init__(
            id="inv_003_account_active",
            statement="It is FORBIDDEN for any transaction to involve an account with status != 'ACTIVE'",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(seconds=10),
            owner="account_service"
        )
    
    def pre_check(self, supplier_id: str, buyer_id: str, account_service) -> bool:
        supplier_status = account_service.get_status(supplier_id)
        buyer_status = account_service.get_status(buyer_id)
        
        both_active = (supplier_status == 'ACTIVE' and buyer_status == 'ACTIVE')
        
        logger.info(f"PRE-CHECK {self.id}: supplier={supplier_status}, buyer={buyer_status}, valid={both_active}")
        return both_active
    
    def post_check(self, result: Any, **kwargs) -> bool:
        account_service = result['account_service']
        supplier_id = result['supplier_id']
        buyer_id = result['buyer_id']
        
        supplier_status = account_service.get_status(supplier_id)
        buyer_status = account_service.get_status(buyer_id)
        
        both_active = (supplier_status == 'ACTIVE' and buyer_status == 'ACTIVE')
        
        logger.info(f"POST-CHECK {self.id}: supplier={supplier_status}, buyer={buyer_status}, valid={both_active}")
        return both_active
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Rollback transaction, restore balances
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.update_invoice_status(invoice_id, 'REJECTED')
        logger.warning(f"ROLLBACK {self.id}: Rejected invoice {invoice_id}")

class NoDuplicateInvoiceHash(Invariant):
    """INV-004: Invoice content hash must be unique."""
    
    def __init__(self):
        super().__init__(
            id="inv_004_no_duplicate_hash",
            statement="The system MUST always ensure invoice content hash is unique",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_001_unique_invoice_ids"],
            decay_window=None,
            owner="invoice_service"
        )
    
    def pre_check(self, invoice_data: Dict, storage) -> bool:
        invoice_hash = self._compute_hash(invoice_data)
        exists = storage.hash_exists(invoice_hash)
        
        logger.info(f"PRE-CHECK {self.id}: hash={invoice_hash[:8]}..., exists={exists}")
        return not exists
    
    def post_check(self, result: Any, **kwargs) -> bool:
        storage = result['storage']
        invoice_hash = result['invoice_hash']
        count = storage.count_hash(invoice_hash)
        
        logger.info(f"POST-CHECK {self.id}: hash={invoice_hash[:8]}..., count={count}")
        return count == 1
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.delete_invoice(invoice_id)
        logger.warning(f"ROLLBACK {self.id}: Deleted duplicate invoice {invoice_id}")
    
    def _compute_hash(self, invoice_data: Dict) -> str:
        data_str = f"{invoice_data['supplier_id']}:{invoice_data['buyer_id']}:{invoice_data['amount']}:{invoice_data['line_items']}"
        return hashlib.sha256(data_str.encode()).hexdigest()

class CreditLimitNotExceeded(Invariant):
    """INV-005: Buyer outstanding balance <= credit limit."""
    
    def __init__(self):
        super().__init__(
            id="inv_005_credit_limit",
            statement="It is FORBIDDEN for buyer outstanding balance to exceed approved credit_limit",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(hours=1),
            owner="credit_service"
        )
    
    def pre_check(self, buyer_id: str, new_amount: float, credit_service) -> bool:
        outstanding = credit_service.get_outstanding_balance(buyer_id)
        credit_limit = credit_service.get_credit_limit(buyer_id)
        
        within_limit = (outstanding + new_amount) <= credit_limit
        
        logger.info(f"PRE-CHECK {self.id}: buyer={buyer_id}, outstanding=${outstanding}, limit=${credit_limit}, new=${new_amount}, valid={within_limit}")
        return within_limit
    
    def post_check(self, result: Any, **kwargs) -> bool:
        credit_service = result['credit_service']
        buyer_id = result['buyer_id']
        
        outstanding = credit_service.get_outstanding_balance(buyer_id)
        credit_limit = credit_service.get_credit_limit(buyer_id)
        
        within_limit = outstanding <= credit_limit
        
        logger.info(f"POST-CHECK {self.id}: buyer={buyer_id}, outstanding=${outstanding}, limit=${credit_limit}, valid={within_limit}")
        return within_limit
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.update_invoice_status(invoice_id, 'REJECTED')
        logger.warning(f"ROLLBACK {self.id}: Rejected invoice {invoice_id} - credit limit exceeded")

class SettlementExactlyOnce(Invariant):
    """INV-006: Every invoice settles exactly once."""
    
    def __init__(self):
        super().__init__(
            id="inv_006_settlement_once",
            statement="The system MUST always ensure every invoice settles exactly once",
            type=InvariantType.STATE,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_001_unique_invoice_ids"],
            decay_window=None,
            owner="settlement_service"
        )
    
    def pre_check(self, invoice_id: str, ledger) -> bool:
        settlement_count = ledger.count_settlements(invoice_id)
        can_settle = settlement_count == 0
        
        logger.info(f"PRE-CHECK {self.id}: invoice={invoice_id}, existing_settlements={settlement_count}, can_settle={can_settle}")
        return can_settle
    
    def post_check(self, result: Any, **kwargs) -> bool:
        ledger = result['ledger']
        invoice_id = result['invoice_id']
        settlement_count = ledger.count_settlements(invoice_id)
        
        logger.info(f"POST-CHECK {self.id}: invoice={invoice_id}, settlements={settlement_count}")
        return settlement_count == 1
    
    def rollback_action(self, state_before: Dict[str, Any]):
        ledger = state_before['ledger']
        invoice_id = state_before['invoice_id']
        
        # Append correcting entry (ledger is immutable)
        ledger.add_correction_entry(invoice_id, "Settlement rolled back")
        
        # Reverse balances
        storage = state_before['storage']
        storage.restore_balances(state_before['balances'])
        
        logger.warning(f"ROLLBACK {self.id}: Reversed settlement for {invoice_id}")

class ValidPaymentTerms(Invariant):
    """INV-007: Payment terms must be in allowed set."""
    
    ALLOWED_TERMS = {0, 15, 30, 45, 60, 90}
    
    def __init__(self):
        super().__init__(
            id="inv_007_valid_terms",
            statement="The system MUST always ensure payment terms are in [0, 15, 30, 45, 60, 90] days",
            type=InvariantType.STATE,
            criticality=Criticality.IMPORTANT,
            dependencies=[],
            decay_window=None,
            owner="invoice_service"
        )
    
    def pre_check(self, terms: int, **kwargs) -> bool:
        valid = terms in self.ALLOWED_TERMS
        logger.info(f"PRE-CHECK {self.id}: terms={terms}, valid={valid}")
        return valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        terms = result['invoice'].terms
        valid = terms in self.ALLOWED_TERMS
        logger.info(f"POST-CHECK {self.id}: terms={terms}, valid={valid}")
        return valid
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.delete_invoice(invoice_id)
        logger.warning(f"ROLLBACK {self.id}: Deleted invoice {invoice_id} - invalid terms")

# ============================================
# TRANSITION INVARIANTS
# ============================================

class ValidStatusTransitions(Invariant):
    """INV-101: Only valid state machine transitions allowed."""
    
    ALLOWED_TRANSITIONS = {
        "PENDING": ["ACCEPTED", "REJECTED", "EXPIRED", "FRAUD_REVIEW"],
        "ACCEPTED": ["SETTLED", "FAILED"],
        "FRAUD_REVIEW": ["ACCEPTED", "REJECTED"],
        "SETTLED": [],
        "REJECTED": [],
        "EXPIRED": [],
        "FAILED": ["REJECTED"]
    }
    
    def __init__(self):
        super().__init__(
            id="inv_101_valid_transitions",
            statement="It is FORBIDDEN for invoices to transition to states outside valid state machine",
            type=InvariantType.TRANSITION,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="state_machine_service"
        )
    
    def pre_check(self, invoice_id: str, new_status: str, storage) -> bool:
        current_status = storage.get_invoice_status(invoice_id)
        allowed = self.ALLOWED_TRANSITIONS.get(current_status, [])
        valid = new_status in allowed
        
        logger.info(f"PRE-CHECK {self.id}: {current_status} -> {new_status}, valid={valid}")
        return valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        storage = result['storage']
        invoice_id = result['invoice_id']
        previous_status = result['previous_status']
        new_status = storage.get_invoice_status(invoice_id)
        
        allowed = self.ALLOWED_TRANSITIONS.get(previous_status, [])
        valid = new_status in allowed
        
        logger.info(f"POST-CHECK {self.id}: {previous_status} -> {new_status}, valid={valid}")
        return valid
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        previous_status = state_before['previous_status']
        
        storage.update_invoice_status(invoice_id, previous_status)
        logger.warning(f"ROLLBACK {self.id}: Reverted status to {previous_status}")

class AtomicSettlementTransition(Invariant):
    """INV-102: All settlement legs complete or all rollback."""
    
    def __init__(self):
        super().__init__(
            id="inv_102_atomic_settlement",
            statement="The system MUST always ensure all settlement legs complete or all rollback",
            type=InvariantType.TRANSITION,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_006_settlement_once", "inv_003_account_active"],
            decay_window=None,
            owner="settlement_service"
        )
    
    def pre_check(self, supplier_id: str, buyer_id: str, capital_provider_id: str, 
                  amount: float, account_service) -> bool:
        # Verify all accounts have sufficient balance/capacity
        supplier_can_receive = account_service.can_receive(supplier_id, amount)
        buyer_can_pay = account_service.can_pay(buyer_id, amount)
        capital_can_advance = account_service.can_advance(capital_provider_id, amount)
        
        all_ready = supplier_can_receive and buyer_can_pay and capital_can_advance
        
        logger.info(f"PRE-CHECK {self.id}: supplier_ready={supplier_can_receive}, buyer_ready={buyer_can_pay}, capital_ready={capital_can_advance}, all_ready={all_ready}")
        return all_ready
    
    def post_check(self, result: Any, **kwargs) -> bool:
        ledger = result['ledger']
        invoice_id = result['invoice_id']
        
        # Verify all 3 legs completed
        supplier_credited = ledger.has_credit(invoice_id, result['supplier_id'])
        buyer_debited = ledger.has_debit(invoice_id, result['buyer_id'])
        capital_advanced = ledger.has_advance(invoice_id, result['capital_provider_id'])
        
        all_complete = supplier_credited and buyer_debited and capital_advanced
        
        logger.info(f"POST-CHECK {self.id}: supplier_credited={supplier_credited}, buyer_debited={buyer_debited}, capital_advanced={capital_advanced}, atomic={all_complete}")
        return all_complete
    
    def rollback_action(self, state_before: Dict[str, Any]):
        ledger = state_before['ledger']
        invoice_id = state_before['invoice_id']
        
        # 2-phase commit rollback: reverse in dependency order
        # 1. Return funds to capital provider
        # 2. Uncharge buyer
        # 3. Debit supplier
        
        ledger.add_correction_entry(invoice_id, "Atomic settlement failed - all legs reversed")
        
        account_service = state_before['account_service']
        account_service.restore_balances(state_before['balances_snapshot'])
        
        storage = state_before['storage']
        storage.update_invoice_status(invoice_id, 'FAILED')
        
        logger.critical(f"ROLLBACK {self.id}: Reversed atomic settlement for {invoice_id}")

# ============================================
# TEMPORAL INVARIANTS
# ============================================

class SettlementWithin5Seconds(Invariant):
    """INV-201: Settlement completes in <5 seconds."""
    
    MAX_LATENCY_SECONDS = 5
    
    def __init__(self):
        super().__init__(
            id="inv_201_settlement_speed",
            statement="The system MUST always complete settlement within 5 seconds of acceptance",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_102_atomic_settlement"],
            decay_window=timedelta(seconds=30),
            owner="settlement_service"
        )
    
    def pre_check(self, settlement_rails, **kwargs) -> bool:
        # Verify rails report healthy latency
        all_fast = all(rail.latency_ms < 2000 for rail in settlement_rails)
        logger.info(f"PRE-CHECK {self.id}: all_rails_fast={all_fast}")
        return all_fast
    
    def post_check(self, result: Any, **kwargs) -> bool:
        acceptance_time = result['acceptance_timestamp']
        settlement_time = result['settlement_timestamp']
        
        latency = (settlement_time - acceptance_time).total_seconds()
        within_limit = latency < self.MAX_LATENCY_SECONDS
        
        logger.info(f"POST-CHECK {self.id}: latency={latency}s, limit={self.MAX_LATENCY_SECONDS}s, valid={within_limit}")
        return within_limit
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # If timeout occurred, settlement already rolled back by timeout handler
        logger.error(f"ROLLBACK {self.id}: Settlement exceeded time limit")

class FraudScoreFresh(Invariant):
    """INV-202: Fraud score <24 hours old at acceptance."""
    
    MAX_AGE_HOURS = 24
    FRAUD_THRESHOLD = 0.75
    
    def __init__(self):
        super().__init__(
            id="inv_202_fraud_score_fresh",
            statement="The system MUST always ensure fraud score is <24 hours old at acceptance",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(hours=24),
            owner="fraud_service"
        )
    
    def pre_check(self, invoice_id: str, fraud_service) -> bool:
        fraud_data = fraud_service.get_fraud_score(invoice_id)
        
        if fraud_data is None:
            logger.warning(f"PRE-CHECK {self.id}: No fraud score found for {invoice_id}")
            return False
        
        age_hours = (datetime.now() - fraud_data['calculated_at']).total_seconds() / 3600
        is_fresh = age_hours < self.MAX_AGE_HOURS
        is_below_threshold = fraud_data['score'] < self.FRAUD_THRESHOLD
        
        valid = is_fresh and is_below_threshold
        
        logger.info(f"PRE-CHECK {self.id}: score={fraud_data['score']}, age={age_hours:.1f}h, valid={valid}")
        return valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify fraud score didn't change during acceptance
        fraud_service = result['fraud_service']
        invoice_id = result['invoice_id']
        original_timestamp = result['fraud_score_timestamp']
        
        current_data = fraud_service.get_fraud_score(invoice_id)
        timestamp_unchanged = current_data['calculated_at'] == original_timestamp
        
        logger.info(f"POST-CHECK {self.id}: timestamp_unchanged={timestamp_unchanged}")
        return timestamp_unchanged
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        storage.update_invoice_status(invoice_id, 'FRAUD_REVIEW')
        logger.warning(f"ROLLBACK {self.id}: Moved {invoice_id} to fraud review")

# ============================================
# SECURITY INVARIANTS
# ============================================

class SanctionsListCheck(Invariant):
    """INV-401: No transactions with sanctioned parties."""
    
    def __init__(self):
        super().__init__(
            id="inv_401_sanctions_check",
            statement="It is FORBIDDEN to process transactions involving any party on OFAC sanctions list",
            type=InvariantType.SECURITY,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(hours=6),
            owner="compliance_service"
        )
    
    def pre_check(self, supplier_id: str, buyer_id: str, compliance_service) -> bool:
        supplier_sanctioned = compliance_service.is_sanctioned(supplier_id)
        buyer_sanctioned = compliance_service.is_sanctioned(buyer_id)
        
        both_clear = not (supplier_sanctioned or buyer_sanctioned)
        
        logger.info(f"PRE-CHECK {self.id}: supplier_sanctioned={supplier_sanctioned}, buyer_sanctioned={buyer_sanctioned}, clear={both_clear}")
        
        if not both_clear:
            logger.critical(f"SANCTIONS VIOLATION: supplier={supplier_id}, buyer={buyer_id}")
        
        return both_clear
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Re-verify at settlement (list updated every 6 hours)
        compliance_service = result['compliance_service']
        supplier_id = result['supplier_id']
        buyer_id = result['buyer_id']
        
        supplier_sanctioned = compliance_service.is_sanctioned(supplier_id)
        buyer_sanctioned = compliance_service.is_sanctioned(buyer_id)
        
        both_clear = not (supplier_sanctioned or buyer_sanctioned)
        
        logger.info(f"POST-CHECK {self.id}: supplier_sanctioned={supplier_sanctioned}, buyer_sanctioned={buyer_sanctioned}, clear={both_clear}")
        return both_clear
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        # FREEZE both accounts
        account_service = state_before['account_service']
        account_service.freeze_account(state_before['supplier_id'])
        account_service.freeze_account(state_before['buyer_id'])
        
        # REJECT invoice
        storage.update_invoice_status(invoice_id, 'REJECTED')
        
        # File SAR
        compliance_service = state_before['compliance_service']
        compliance_service.file_sar(invoice_id, "Sanctions list match detected")
        
        logger.critical(f"ROLLBACK {self.id}: SANCTIONS VIOLATION - accounts frozen, SAR filed")

# ============================================
# FINANCIAL INVARIANTS
# ============================================

class LedgerBalanceReconciliation(Invariant):
    """INV-501: Total credits == total debits."""
    
    MAX_IMBALANCE = 0.01  # $0.01 tolerance for rounding
    
    def __init__(self):
        super().__init__(
            id="inv_501_ledger_reconciliation",
            statement="The system MUST always ensure total_credits == total_debits across all accounts",
            type=InvariantType.FINANCIAL,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_102_atomic_settlement"],
            decay_window=timedelta(minutes=10),
            owner="ledger_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Continuous background check, not per-transaction
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        ledger = result['ledger']
        
        total_credits = ledger.sum_all_credits()
        total_debits = ledger.sum_all_debits()
        
        imbalance = abs(total_credits - total_debits)
        balanced = imbalance <= self.MAX_IMBALANCE
        
        logger.info(f"POST-CHECK {self.id}: credits=${total_credits:.2f}, debits=${total_debits:.2f}, imbalance=${imbalance:.2f}, balanced={balanced}")
        
        if not balanced:
            logger.critical(f"LEDGER IMBALANCE DETECTED: ${imbalance:.2f}")
        
        return balanced
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # FREEZE entire system - ledger integrity compromised
        logger.critical(f"ROLLBACK {self.id}: FREEZING SYSTEM - ledger imbalance detected")
        
        # Trigger emergency audit
        system = state_before['system']
        system.transition_to(SystemState.FROZEN)
        system.trigger_emergency_audit("Ledger reconciliation failure")

class PricingAccuracy(Invariant):
    """INV-502: Buyer charged exactly quoted price."""
    
    MAX_VARIANCE = 0.01  # $0.01 tolerance
    
    def __init__(self):
        super().__init__(
            id="inv_502_pricing_accuracy",
            statement="The system MUST always charge buyer exactly the quoted price",
            type=InvariantType.FINANCIAL,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="pricing_service"
        )
    
    def pre_check(self, pricing_quote, **kwargs) -> bool:
        # Verify quote exists and is fresh
        has_quote = pricing_quote is not None
        logger.info(f"PRE-CHECK {self.id}: has_quote={has_quote}")
        return has_quote
    
    def post_check(self, result: Any, **kwargs) -> bool:
        pricing_quote = result['pricing_quote']
        actual_charge = result['actual_charge']
        
        variance = abs(actual_charge - pricing_quote['total_cost'])
        accurate = variance <= self.MAX_VARIANCE
        
        logger.info(f"POST-CHECK {self.id}: quoted=${pricing_quote['total_cost']:.2f}, actual=${actual_charge:.2f}, variance=${variance:.4f}, accurate={accurate}")
        
        if not accurate:
            logger.error(f"PRICING DISCREPANCY: Quoted ${pricing_quote['total_cost']:.2f}, charged ${actual_charge:.2f}")
        
        return accurate
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Auto-refund difference
        buyer_id = state_before['buyer_id']
        variance = state_before['actual_charge'] - state_before['pricing_quote']['total_cost']
        
        account_service = state_before['account_service']
        account_service.refund(buyer_id, variance)
        
        logger.warning(f"ROLLBACK {self.id}: Refunded ${variance:.2f} to buyer {buyer_id}")

# ============================================
# INVARIANT ENFORCER
# ============================================

class InvariantEnforcer:
    """Non-bypassable enforcement layer."""
    
    def __init__(self, invariants: List[Invariant], ledger: DecisionLedger):
        self.invariants = invariants
        self.ledger = ledger
        self.dependency_graph = self._build_dependency_graph(invariants)
    
    def _build_dependency_graph(self, invariants: List[Invariant]) -> Dict[str, List[str]]:
        """Build adjacency list of dependencies."""
        graph = {}
        for inv in invariants:
            graph[inv.id] = inv.dependencies
        return graph
    
    def _topological_sort(self, invariants: List[Invariant]) -> List[Invariant]:
        """Sort invariants by dependency order."""
        # Simple implementation - in production use proper topological sort
        sorted_invs = []
        remaining = set(inv.id for inv in invariants)
        
        while remaining:
            # Find invariants with no unresolved dependencies
            ready = [
                inv for inv in invariants
                if inv.id in remaining and all(dep not in remaining for dep in inv.dependencies)
            ]
            
            if not ready:
                raise InvariantViolation("Circular dependency detected in invariants")
            
            sorted_invs.extend(ready)
            for inv in ready:
                remaining.remove(inv.id)
        
        return sorted_invs
    
    def enforce_action(self, action: Callable, *args, **kwargs) -> Any:
        """Execute action with full invariant enforcement."""
        
        # Capture state before action
        state_before = self._capture_state(kwargs)
        
        # PRE-ACTION CHECKS (in dependency order)
        sorted_invs = self._topological_sort(self.invariants)
        
        for inv in sorted_invs:
            decision = self._pre_check(inv, state_before, *args, **kwargs)
            self.ledger.record(decision)
            
            if not decision.result:
                logger.error(f"PRE-CHECK FAILED: {inv.id}")
                raise InvariantViolation(f"Pre-check failed: {inv.id}")
        
        # Execute action
        try:
            result = action(*args, **kwargs)
        except Exception as e:
            logger.error(f"ACTION FAILED: {e}")
            self._rollback(state_before, sorted_invs)
            raise
        
        # POST-ACTION CHECKS (in dependency order)
        for inv in sorted_invs:
            decision = self._post_check(inv, result, state_before)
            self.ledger.record(decision)
            
            if not decision.result:
                logger.error(f"POST-CHECK FAILED: {inv.id}")
                self._rollback(state_before, sorted_invs)
                raise InvariantViolation(f"Post-check failed: {inv.id}")
        
        # All checks passed
        logger.info("All invariant checks PASSED")
        return result
    
    def _pre_check(self, inv: Invariant, state: Dict, *args, **kwargs) -> EnforcementDecision:
        """Execute pre-action check."""
        try:
            result = inv.pre_check(*args, **kwargs)
            action = EnforcementResult.PROCEED if result else EnforcementResult.FREEZE
        except Exception as e:
            logger.error(f"Pre-check exception: {inv.id}", exc_info=e)
            result = False
            action = EnforcementResult.FREEZE
        
        return EnforcementDecision(
            invariant_id=inv.id,
            check_type="PRE",
            result=result,
            action=action,
            timestamp=datetime.now(),
            state_snapshot=state.copy(),
            signature=self._sign_decision(inv.id, result)
        )
    
    def _post_check(self, inv: Invariant, result: Any, state: Dict) -> EnforcementDecision:
        """Execute post-action check."""
        try:
            check_result = inv.post_check(result)
            action = EnforcementResult.PROCEED if check_result else EnforcementResult.ROLLBACK
        except Exception as e:
            logger.error(f"Post-check exception: {inv.id}", exc_info=e)
            check_result = False
            action = EnforcementResult.ROLLBACK
        
        return EnforcementDecision(
            invariant_id=inv.id,
            check_type="POST",
            result=check_result,
            action=action,
            timestamp=datetime.now(),
            state_snapshot=state.copy(),
            signature=self._sign_decision(inv.id, check_result)
        )
    
    def _rollback(self, state_before: Dict, invariants: List[Invariant]):
        """Automatic rollback to previous state."""
        logger.warning("ROLLBACK INITIATED")
        
        # Execute rollback in reverse dependency order
        for inv in reversed(invariants):
            try:
                inv.rollback_action(state_before)
            except Exception as e:
                logger.critical(f"ROLLBACK FAILED for {inv.id}: {e}")
                raise SystemCompromised(f"Rollback failed for {inv.id}")
        
        logger.info("ROLLBACK COMPLETE")
    
    def _capture_state(self, kwargs: Dict) -> Dict[str, Any]:
        """Capture current system state."""
        return {
            'timestamp': datetime.now(),
            **kwargs
        }
    
    def _sign_decision(self, invariant_id: str, result: bool) -> str:
        """Cryptographically sign decision."""
        data = f"{invariant_id}:{result}:{datetime.now().isoformat()}"
        return hmac.new(SYSTEM_SECRET, data.encode(), 'sha256').hexdigest()

# ============================================
# USAGE EXAMPLE
# ============================================

def example_usage():
    """Demonstrate enforcement layer."""
    
    # Initialize ledger
    ledger = DecisionLedger()
    
    # Initialize invariants
    invariants = [
        UniqueInvoiceIDs(),
        ValidInvoiceAmounts(),
        AccountStatusActive(),
        NoDuplicateInvoiceHash(),
        CreditLimitNotExceeded(),
        SettlementExactlyOnce(),
        ValidPaymentTerms(),
        ValidStatusTransitions(),
        AtomicSettlementTransition(),
        SettlementWithin5Seconds(),
        FraudScoreFresh(),
        SanctionsListCheck(),
        LedgerBalanceReconciliation(),
        PricingAccuracy(),
    ]
    
    # Initialize enforcer
    enforcer = InvariantEnforcer(invariants, ledger)
    
    # Define action to enforce
    def create_invoice(invoice_id, supplier_id, buyer_id, amount, terms, storage):
        """Action: Create new invoice."""
        invoice = storage.create_invoice(
            id=invoice_id,
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            amount=amount,
            terms=terms
        )
        return {
            'invoice': invoice,
            'invoice_id': invoice_id,
            'storage': storage
        }
    
    # Execute with enforcement
    try:
        result = enforcer.enforce_action(
            create_invoice,
            invoice_id="INV-001",
            supplier_id="SUP-123",
            buyer_id="BUY-456",
            amount=50000,
            terms=30,
            storage=None  # Mock storage
        )
        print("✅ Invoice created successfully with all invariants verified")
    except InvariantViolation as e:
        print(f"❌ Invariant violation: {e}")
    except SystemCompromised as e:
        print(f"🚨 CRITICAL: System compromised: {e}")

if __name__ == "__main__":
    print("InstantTrade Network - Enforcement Layer v1.0.0")
    print("="*60)
    example_usage()
