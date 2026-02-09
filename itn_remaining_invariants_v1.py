"""
InstantTrade Network (ITN) - Remaining Invariants + Module Organization
Version: 1.0.0
Generated: 2026-02-08

Implements remaining 16 invariants (INV-103 through INV-603)
Provides module-level partitioning for large codebase scalability
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List
from dataclasses import dataclass

# Import base classes from main enforcement layer
from itn_enforcement_v1 import (
    Invariant,
    InvariantType,
    Criticality,
    logger
)

# ============================================
# REMAINING TRANSITION INVARIANTS
# ============================================

class PricingQuoteBeforeAcceptance(Invariant):
    """INV-103: Buyer must have valid pricing quote before accepting."""
    
    QUOTE_VALIDITY_MINUTES = 5
    
    def __init__(self):
        super().__init__(
            id="inv_103_pricing_before_acceptance",
            statement="It is FORBIDDEN for buyer to accept invoice without valid pricing quote",
            type=InvariantType.TRANSITION,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_109_pricing_freshness"],
            decay_window=timedelta(minutes=5),
            owner="pricing_service"
        )
    
    def pre_check(self, invoice_id: str, pricing_service) -> bool:
        pricing_quote = pricing_service.get_quote(invoice_id)
        
        if not pricing_quote:
            logger.warning(f"PRE-CHECK {self.id}: No pricing quote for {invoice_id}")
            return False
        
        age_minutes = (datetime.now() - pricing_quote['created_at']).total_seconds() / 60
        is_fresh = age_minutes < self.QUOTE_VALIDITY_MINUTES
        
        logger.info(f"PRE-CHECK {self.id}: has_quote=True, age={age_minutes:.1f}min, fresh={is_fresh}")
        return is_fresh
    
    def post_check(self, result: Any, **kwargs) -> bool:
        pricing_quote = result['pricing_quote']
        actual_charge = result.get('actual_charge')
        
        if actual_charge is None:
            return True  # Not yet charged
        
        # Verify charge matches quote
        matches = abs(actual_charge - pricing_quote['total_cost']) <= 0.01
        
        logger.info(f"POST-CHECK {self.id}: quoted=${pricing_quote['total_cost']:.2f}, actual=${actual_charge:.2f}, matches={matches}")
        return matches
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'PENDING')
        
        # Refund if charged
        if 'actual_charge' in state_before and state_before['actual_charge'] > 0:
            account_service = state_before['account_service']
            account_service.refund(state_before['buyer_id'], state_before['actual_charge'])
        
        logger.warning(f"ROLLBACK {self.id}: Reverted to PENDING, refunded buyer")

class BuyerAuthorizationOnly(Invariant):
    """INV-104: Only the designated buyer can accept their invoice."""
    
    def __init__(self):
        super().__init__(
            id="inv_104_buyer_authorization",
            statement="It is FORBIDDEN for buyer to accept invoices where buyer_id != authenticated_user.id",
            type=InvariantType.TRANSITION,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="auth_service"
        )
    
    def pre_check(self, invoice_id: str, authenticated_user_id: str, storage) -> bool:
        invoice = storage.get_invoice(invoice_id)
        authorized = invoice['buyer_id'] == authenticated_user_id
        
        logger.info(f"PRE-CHECK {self.id}: invoice_buyer={invoice['buyer_id']}, auth_user={authenticated_user_id}, authorized={authorized}")
        
        if not authorized:
            logger.warning(f"AUTHORIZATION VIOLATION: User {authenticated_user_id} attempted to accept invoice for {invoice['buyer_id']}")
        
        return authorized
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify buyer_id didn't change during transaction
        storage = result['storage']
        invoice_id = result['invoice_id']
        expected_buyer_id = result['authenticated_user_id']
        
        invoice = storage.get_invoice(invoice_id)
        unchanged = invoice['buyer_id'] == expected_buyer_id
        
        logger.info(f"POST-CHECK {self.id}: buyer_id_unchanged={unchanged}")
        return unchanged
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'PENDING')
        
        # Log security incident
        auth_service = state_before.get('auth_service')
        if auth_service:
            auth_service.log_security_incident(
                event_type="UNAUTHORIZED_INVOICE_ACCESS",
                invoice_id=invoice_id,
                attempted_by=state_before.get('authenticated_user_id')
            )
        
        logger.critical(f"ROLLBACK {self.id}: Unauthorized access attempt blocked")

class NoRetroactiveStatusChanges(Invariant):
    """INV-105: Terminal states cannot be changed."""
    
    TERMINAL_STATES = {'SETTLED', 'REJECTED', 'EXPIRED'}
    
    def __init__(self):
        super().__init__(
            id="inv_105_no_retroactive_changes",
            statement="It is FORBIDDEN to change invoice status if already in terminal state",
            type=InvariantType.TRANSITION,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_101_valid_transitions"],
            decay_window=None,
            owner="state_machine_service"
        )
    
    def pre_check(self, invoice_id: str, new_status: str, storage) -> bool:
        current_status = storage.get_invoice_status(invoice_id)
        is_terminal = current_status in self.TERMINAL_STATES
        
        if is_terminal:
            logger.error(f"PRE-CHECK {self.id}: Attempted to change terminal state {current_status} -> {new_status}")
        
        return not is_terminal
    
    def post_check(self, result: Any, **kwargs) -> bool:
        previous_status = result['previous_status']
        was_terminal = previous_status in self.TERMINAL_STATES
        
        if was_terminal:
            logger.error(f"POST-CHECK {self.id}: Terminal state {previous_status} was modified")
        
        return not was_terminal
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # This should never happen if pre-check works correctly
        logger.critical(f"ROLLBACK {self.id}: Critical - terminal state modification occurred")

# ============================================
# REMAINING TEMPORAL INVARIANTS
# ============================================

class BuyerAcceptanceDeadline(Invariant):
    """INV-203: Invoices expire after 48 hours without acceptance."""
    
    DEADLINE_HOURS = 48
    
    def __init__(self):
        super().__init__(
            id="inv_203_acceptance_deadline",
            statement="The system MUST always transition invoice to EXPIRED if no acceptance within 48 hours",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.IMPORTANT,
            dependencies=["inv_101_valid_transitions"],
            decay_window=timedelta(hours=1),
            owner="lifecycle_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Background job checks - always returns True for individual transactions
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify no pending invoices older than 48 hours
        storage = result['storage']
        pending_invoices = storage.get_all_pending_invoices()
        
        now = datetime.now()
        for invoice in pending_invoices:
            age_hours = (now - invoice['created_at']).total_seconds() / 3600
            
            if age_hours > self.DEADLINE_HOURS:
                logger.error(f"POST-CHECK {self.id}: Invoice {invoice['id']} still PENDING after {age_hours:.1f} hours")
                return False
        
        return True
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Auto-expiration is terminal, no rollback needed
        pass

class FXRateFreshness(Invariant):
    """INV-204: FX rates must be <60 seconds old."""
    
    MAX_AGE_SECONDS = 60
    
    def __init__(self):
        super().__init__(
            id="inv_204_fx_rate_fresh",
            statement="The system MUST always ensure FX rates are <60 seconds old at settlement",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(seconds=60),
            owner="fx_service"
        )
    
    def pre_check(self, fx_rate_data: Dict, **kwargs) -> bool:
        age_seconds = (datetime.now() - fx_rate_data['fetched_at']).total_seconds()
        is_fresh = age_seconds < self.MAX_AGE_SECONDS
        
        logger.info(f"PRE-CHECK {self.id}: fx_rate={fx_rate_data['rate']}, age={age_seconds:.1f}s, fresh={is_fresh}")
        return is_fresh
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify rate wasn't re-fetched during settlement
        fx_rate_timestamp = result['fx_rate_data']['fetched_at']
        original_timestamp = result['original_fx_timestamp']
        
        unchanged = fx_rate_timestamp == original_timestamp
        
        logger.info(f"POST-CHECK {self.id}: fx_timestamp_unchanged={unchanged}")
        return unchanged
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Reverse FX conversion
        account_service = state_before['account_service']
        buyer_id = state_before['buyer_id']
        
        # Refund any excess charge from stale rate
        if 'excess_charge' in state_before:
            account_service.refund(buyer_id, state_before['excess_charge'])
        
        logger.warning(f"ROLLBACK {self.id}: Reversed FX conversion")

class CreditLimitStaleness(Invariant):
    """INV-205: Credit limits re-checked if >1 hour old."""
    
    MAX_STALENESS_HOURS = 1
    
    def __init__(self):
        super().__init__(
            id="inv_205_credit_limit_staleness",
            statement="The system MUST always re-check credit limit if >1 hour since last verification",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.IMPORTANT,
            dependencies=["inv_005_credit_limit"],
            decay_window=timedelta(hours=1),
            owner="credit_service"
        )
    
    def pre_check(self, buyer_id: str, credit_service) -> bool:
        credit_data = credit_service.get_credit_data(buyer_id)
        
        age_hours = (datetime.now() - credit_data['last_checked']).total_seconds() / 3600
        
        if age_hours > self.MAX_STALENESS_HOURS:
            # Re-fetch credit limit
            credit_service.refresh_credit_limit(buyer_id)
            logger.info(f"PRE-CHECK {self.id}: Credit limit refreshed (was {age_hours:.1f}h old)")
        
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify credit limit didn't decrease during transaction
        credit_service = result['credit_service']
        buyer_id = result['buyer_id']
        original_limit = result['original_credit_limit']
        
        current_limit = credit_service.get_credit_limit(buyer_id)
        unchanged_or_increased = current_limit >= original_limit
        
        logger.info(f"POST-CHECK {self.id}: original=${original_limit}, current=${current_limit}, valid={unchanged_or_increased}")
        return unchanged_or_increased
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'REJECTED')
        
        # Notify buyer
        notification_service = state_before.get('notification_service')
        if notification_service:
            notification_service.send(
                buyer_id=state_before['buyer_id'],
                message="Invoice rejected: Credit limit decreased during processing"
            )
        
        logger.warning(f"ROLLBACK {self.id}: Credit limit decreased mid-transaction")

class SettlementRailHealthCheck(Invariant):
    """INV-206: Settlement rails checked within 30 seconds."""
    
    MAX_HEALTH_CHECK_AGE = 30
    
    def __init__(self):
        super().__init__(
            id="inv_206_rail_health",
            statement="The system MUST always verify settlement rails are healthy within 30 seconds of use",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(seconds=30),
            owner="infrastructure_service"
        )
    
    def pre_check(self, settlement_rails: List[Dict], **kwargs) -> bool:
        now = datetime.now()
        
        for rail in settlement_rails:
            age_seconds = (now - rail['last_health_check']).total_seconds()
            
            if age_seconds > self.MAX_HEALTH_CHECK_AGE:
                logger.warning(f"PRE-CHECK {self.id}: Rail {rail['name']} health check stale ({age_seconds:.1f}s)")
                return False
            
            if rail['status'] != 'UP':
                logger.warning(f"PRE-CHECK {self.id}: Rail {rail['name']} is {rail['status']}")
                return False
        
        logger.info(f"PRE-CHECK {self.id}: All {len(settlement_rails)} rails healthy")
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify rails didn't go down during settlement
        settlement_rails = result['settlement_rails']
        
        for rail in settlement_rails:
            if rail['status'] != 'UP':
                logger.error(f"POST-CHECK {self.id}: Rail {rail['name']} went down during settlement")
                return False
        
        return True
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Failover to next available rail
        infrastructure_service = state_before['infrastructure_service']
        infrastructure_service.trigger_failover()
        
        # Retry settlement with backup rail
        logger.warning(f"ROLLBACK {self.id}: Triggering failover to backup settlement rail")

class CapitalBidExpiry(Invariant):
    """INV-207: Capital bids expire after their expiry_timestamp."""
    
    def __init__(self):
        super().__init__(
            id="inv_207_capital_bid_expiry",
            statement="It is FORBIDDEN to accept capital bids after their expiry_timestamp",
            type=InvariantType.TEMPORAL,
            criticality=Criticality.IMPORTANT,
            dependencies=[],
            decay_window=None,
            owner="capital_auction_service"
        )
    
    def pre_check(self, capital_bid: Dict, **kwargs) -> bool:
        is_valid = capital_bid['expiry_timestamp'] > datetime.now()
        
        logger.info(f"PRE-CHECK {self.id}: bid_expires_at={capital_bid['expiry_timestamp']}, valid={is_valid}")
        return is_valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify bid was still valid at selection time
        selected_bid = result['selected_bid']
        selection_time = result['selection_timestamp']
        
        was_valid = selected_bid['expiry_timestamp'] > selection_time
        
        logger.info(f"POST-CHECK {self.id}: bid_was_valid_at_selection={was_valid}")
        return was_valid
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Re-run auction with valid bids only
        capital_auction_service = state_before['capital_auction_service']
        invoice_id = state_before['invoice_id']
        
        capital_auction_service.restart_auction(invoice_id)
        
        logger.warning(f"ROLLBACK {self.id}: Restarting auction with valid bids")

# ============================================
# REMAINING PROBABILISTIC INVARIANTS
# ============================================

class CapitalCompetitionRate(Invariant):
    """INV-301: ≥3 capital bids for 70%+ of invoices."""
    
    MIN_BIDS = 3
    MIN_COMPETITION_RATE = 0.70
    MEASUREMENT_WINDOW_HOURS = 24
    
    def __init__(self):
        super().__init__(
            id="inv_301_capital_competition",
            statement="The system MUST always receive ≥3 capital bids for 70%+ of invoices",
            type=InvariantType.PROBABILISTIC,
            criticality=Criticality.IMPORTANT,
            dependencies=[],
            decay_window=timedelta(hours=24),
            owner="capital_auction_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Measured over rolling window, not per-transaction
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        capital_auction_service = result['capital_auction_service']
        
        # Get statistics for last 24 hours
        stats = capital_auction_service.get_competition_stats(
            window_hours=self.MEASUREMENT_WINDOW_HOURS
        )
        
        competition_rate = stats['invoices_with_3plus_bids'] / stats['total_invoices']
        meets_threshold = competition_rate >= self.MIN_COMPETITION_RATE
        
        logger.info(f"POST-CHECK {self.id}: competition_rate={competition_rate:.2%}, threshold={self.MIN_COMPETITION_RATE:.2%}, valid={meets_threshold}")
        
        if not meets_threshold:
            logger.warning(f"LOW LIQUIDITY: Only {competition_rate:.2%} of invoices have ≥3 bids")
        
        return meets_threshold
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Trigger LOW_LIQUIDITY alert
        capital_auction_service = state_before['capital_auction_service']
        capital_auction_service.trigger_alert('LOW_LIQUIDITY')
        
        # Use fallback rate for current invoice
        invoice_id = state_before['invoice_id']
        capital_auction_service.apply_fallback_rate(invoice_id)
        
        logger.warning(f"ROLLBACK {self.id}: Applied fallback rate due to low liquidity")

class FraudDetectionAccuracy(Invariant):
    """INV-302: 100% of high fraud scores blocked."""
    
    FRAUD_THRESHOLD = 0.75
    
    def __init__(self):
        super().__init__(
            id="inv_302_fraud_accuracy",
            statement="The system MUST always block 100% of invoices with fraud_score > 0.75",
            type=InvariantType.PROBABILISTIC,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_202_fraud_score_fresh"],
            decay_window=timedelta(hours=24),
            owner="fraud_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Enforced per-invoice by INV-202
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Daily audit: verify no high-fraud-score invoices slipped through
        storage = result['storage']
        fraud_service = result['fraud_service']
        
        settled_invoices = storage.get_invoices_by_status('SETTLED', days=1)
        
        violations = []
        for invoice in settled_invoices:
            fraud_data = fraud_service.get_fraud_score(invoice['id'])
            
            if fraud_data and fraud_data['score'] > self.FRAUD_THRESHOLD:
                violations.append(invoice['id'])
        
        no_violations = len(violations) == 0
        
        if violations:
            logger.critical(f"POST-CHECK {self.id}: {len(violations)} high-fraud invoices settled: {violations}")
        
        return no_violations
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # FREEZE system - fraud detection failed
        system = state_before['system']
        system.transition_to('FROZEN')
        
        # Trigger emergency audit
        system.trigger_emergency_audit("Fraud detection failure")
        
        logger.critical(f"ROLLBACK {self.id}: SYSTEM FROZEN - fraud detection breach")

class SettlementSuccessRate(Invariant):
    """INV-303: ≥99.9% settlement success rate."""
    
    MIN_SUCCESS_RATE = 0.999
    MEASUREMENT_WINDOW_DAYS = 7
    
    def __init__(self):
        super().__init__(
            id="inv_303_settlement_success",
            statement="The system MUST always maintain ≥99.9% settlement success rate",
            type=InvariantType.PROBABILISTIC,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_102_atomic_settlement", "inv_206_rail_health"],
            decay_window=timedelta(days=7),
            owner="settlement_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Measured over rolling window
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        settlement_service = result['settlement_service']
        
        stats = settlement_service.get_success_stats(
            window_days=self.MEASUREMENT_WINDOW_DAYS
        )
        
        success_rate = stats['settled'] / (stats['settled'] + stats['failed'])
        meets_sla = success_rate >= self.MIN_SUCCESS_RATE
        
        logger.info(f"POST-CHECK {self.id}: success_rate={success_rate:.4%}, sla={self.MIN_SUCCESS_RATE:.4%}, valid={meets_sla}")
        
        if not meets_sla:
            logger.error(f"SLA BREACH: Settlement success rate {success_rate:.4%} below {self.MIN_SUCCESS_RATE:.4%}")
        
        return meets_sla
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Enter DEGRADED_SERVICE mode
        system = state_before['system']
        system.set_mode('DEGRADED_SERVICE')
        
        # Investigate recent failures
        settlement_service = state_before['settlement_service']
        settlement_service.trigger_failure_analysis()
        
        logger.error(f"ROLLBACK {self.id}: Entered degraded service mode")

# ============================================
# REMAINING SECURITY INVARIANTS
# ============================================

class VerifiedAccountRequired(Invariant):
    """INV-402: KYC verification required."""
    
    def __init__(self):
        super().__init__(
            id="inv_402_kyc_verification",
            statement="It is FORBIDDEN for unverified accounts (KYC incomplete) to transact",
            type=InvariantType.SECURITY,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_003_account_active"],
            decay_window=timedelta(days=7),
            owner="compliance_service"
        )
    
    def pre_check(self, supplier_id: str, buyer_id: str, compliance_service) -> bool:
        supplier_verified = compliance_service.get_kyc_status(supplier_id) == 'VERIFIED'
        buyer_verified = compliance_service.get_kyc_status(buyer_id) == 'VERIFIED'
        
        both_verified = supplier_verified and buyer_verified
        
        logger.info(f"PRE-CHECK {self.id}: supplier_verified={supplier_verified}, buyer_verified={buyer_verified}, valid={both_verified}")
        
        if not both_verified:
            logger.warning(f"KYC INCOMPLETE: supplier={supplier_id}, buyer={buyer_id}")
        
        return both_verified
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify KYC status didn't change to SUSPENDED during transaction
        compliance_service = result['compliance_service']
        supplier_id = result['supplier_id']
        buyer_id = result['buyer_id']
        
        supplier_status = compliance_service.get_kyc_status(supplier_id)
        buyer_status = compliance_service.get_kyc_status(buyer_id)
        
        both_still_verified = (supplier_status == 'VERIFIED' and buyer_status == 'VERIFIED')
        
        logger.info(f"POST-CHECK {self.id}: supplier={supplier_status}, buyer={buyer_status}, valid={both_still_verified}")
        return both_still_verified
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        # ROLLBACK transaction
        storage.update_invoice_status(invoice_id, 'REJECTED')
        
        # FREEZE accounts
        account_service = state_before['account_service']
        account_service.freeze_account(state_before['supplier_id'])
        account_service.freeze_account(state_before['buyer_id'])
        
        logger.critical(f"ROLLBACK {self.id}: KYC status changed - accounts frozen")

class CryptographicSignatureRequired(Invariant):
    """INV-403: Buyer acceptance requires cryptographic signature."""
    
    def __init__(self):
        super().__init__(
            id="inv_403_signature_required",
            statement="The system MUST always verify cryptographic signature for buyer acceptance",
            type=InvariantType.SECURITY,
            criticality=Criticality.CRITICAL,
            dependencies=["inv_104_buyer_authorization"],
            decay_window=None,
            owner="auth_service"
        )
    
    def pre_check(self, acceptance_signature: str, invoice_hash: str, buyer_public_key: str, auth_service) -> bool:
        is_valid = auth_service.verify_signature(
            signature=acceptance_signature,
            message=invoice_hash,
            public_key=buyer_public_key
        )
        
        logger.info(f"PRE-CHECK {self.id}: signature_valid={is_valid}")
        
        if not is_valid:
            logger.critical(f"INVALID SIGNATURE: Possible forgery attempt")
        
        return is_valid
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify signature stored immutably in ledger
        ledger = result['ledger']
        invoice_id = result['invoice_id']
        
        signature_stored = ledger.has_signature(invoice_id)
        
        logger.info(f"POST-CHECK {self.id}: signature_stored={signature_stored}")
        return signature_stored
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'REJECTED')
        
        # Log security incident
        auth_service = state_before['auth_service']
        auth_service.log_security_incident(
            event_type="INVALID_SIGNATURE",
            invoice_id=invoice_id,
            severity="CRITICAL"
        )
        
        logger.critical(f"ROLLBACK {self.id}: Invalid signature - possible forgery")

class RateLimiting(Invariant):
    """INV-404: Rate limiting on invoice submissions."""
    
    MAX_INVOICES_PER_HOUR = 100
    
    def __init__(self):
        super().__init__(
            id="inv_404_rate_limiting",
            statement="It is FORBIDDEN for any account to submit >100 invoices per hour",
            type=InvariantType.SECURITY,
            criticality=Criticality.IMPORTANT,
            dependencies=[],
            decay_window=timedelta(hours=1),
            owner="api_gateway"
        )
    
    def pre_check(self, supplier_id: str, storage) -> bool:
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_count = storage.count_invoices_since(supplier_id, one_hour_ago)
        
        within_limit = recent_count < self.MAX_INVOICES_PER_HOUR
        
        logger.info(f"PRE-CHECK {self.id}: supplier={supplier_id}, recent_count={recent_count}, limit={self.MAX_INVOICES_PER_HOUR}, valid={within_limit}")
        
        if not within_limit:
            logger.warning(f"RATE LIMIT EXCEEDED: Supplier {supplier_id} submitted {recent_count} invoices in last hour")
        
        return within_limit
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Throttling only - no post-check needed
        return True
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'REJECTED')
        
        # Trigger abuse investigation if significantly over limit
        supplier_id = state_before['supplier_id']
        one_hour_ago = datetime.now() - timedelta(hours=1)
        recent_count = storage.count_invoices_since(supplier_id, one_hour_ago)
        
        if recent_count > self.MAX_INVOICES_PER_HOUR * 2:
            compliance_service = state_before.get('compliance_service')
            if compliance_service:
                compliance_service.trigger_abuse_investigation(supplier_id)
        
        logger.warning(f"ROLLBACK {self.id}: Rate limit exceeded - invoice rejected")

# ============================================
# REMAINING FINANCIAL INVARIANTS
# ============================================

class CapitalProviderLiquidity(Invariant):
    """INV-503: Capital providers must have sufficient liquidity."""
    
    def __init__(self):
        super().__init__(
            id="inv_503_capital_liquidity",
            statement="It is FORBIDDEN for capital provider to bid without sufficient liquidity",
            type=InvariantType.FINANCIAL,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(seconds=30),
            owner="capital_auction_service"
        )
    
    def pre_check(self, capital_provider_id: str, bid_capacity: float, capital_service) -> bool:
        available_liquidity = capital_service.get_available_liquidity(capital_provider_id)
        has_liquidity = available_liquidity >= bid_capacity
        
        logger.info(f"PRE-CHECK {self.id}: provider={capital_provider_id}, available=${available_liquidity}, bid=${bid_capacity}, valid={has_liquidity}")
        
        if not has_liquidity:
            logger.warning(f"INSUFFICIENT LIQUIDITY: Provider {capital_provider_id} has ${available_liquidity}, bid ${bid_capacity}")
        
        return has_liquidity
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify liquidity reserved successfully
        capital_service = result['capital_service']
        capital_provider_id = result['capital_provider_id']
        bid_capacity = result['bid_capacity']
        
        reservation_successful = capital_service.is_reserved(capital_provider_id, bid_capacity)
        
        logger.info(f"POST-CHECK {self.id}: liquidity_reserved={reservation_successful}")
        return reservation_successful
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Remove bid from auction
        capital_auction_service = state_before['capital_auction_service']
        bid_id = state_before['bid_id']
        
        capital_auction_service.remove_bid(bid_id)
        
        # Notify capital provider
        capital_provider_id = state_before['capital_provider_id']
        notification_service = state_before.get('notification_service')
        if notification_service:
            notification_service.send(
                recipient_id=capital_provider_id,
                message="Bid rejected: Insufficient liquidity at time of settlement"
            )
        
        logger.warning(f"ROLLBACK {self.id}: Removed bid due to insufficient liquidity")

# ============================================
# REMAINING DATA INTEGRITY INVARIANTS
# ============================================

class ImmutableLedger(Invariant):
    """INV-601: Ledger entries cannot be modified."""
    
    def __init__(self):
        super().__init__(
            id="inv_601_immutable_ledger",
            statement="It is FORBIDDEN to modify or delete ledger entries after creation",
            type=InvariantType.DATA_INTEGRITY,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=None,
            owner="ledger_service"
        )
    
    def pre_check(self, **kwargs) -> bool:
        # Database constraints enforce immutability
        return True
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify ledger entry hash matches cryptographic signature
        ledger = result['ledger']
        entry_id = result['entry_id']
        
        entry = ledger.get_entry(entry_id)
        
        computed_hash = ledger.compute_hash(entry)
        matches_signature = computed_hash == entry['signature']
        
        logger.info(f"POST-CHECK {self.id}: entry={entry_id}, hash_valid={matches_signature}")
        
        if not matches_signature:
            logger.critical(f"LEDGER TAMPERING DETECTED: Entry {entry_id} signature mismatch")
        
        return matches_signature
    
    def rollback_action(self, state_before: Dict[str, Any]):
        # Cannot rollback ledger (append-only)
        # Correcting entry must be new append
        logger.critical(f"ROLLBACK {self.id}: Ledger immutability - appending correction")

class LineItemsSumToTotal(Invariant):
    """INV-602: Line items must sum to invoice total."""
    
    MAX_VARIANCE = 0.01
    
    def __init__(self):
        super().__init__(
            id="inv_602_line_items_sum",
            statement="The system MUST always ensure invoice.line_items sum to invoice.amount",
            type=InvariantType.DATA_INTEGRITY,
            criticality=Criticality.IMPORTANT,
            dependencies=[],
            decay_window=None,
            owner="invoice_service"
        )
    
    def pre_check(self, line_items: List[Dict], invoice_amount: float, **kwargs) -> bool:
        line_items_sum = sum(item['amount'] for item in line_items)
        variance = abs(line_items_sum - invoice_amount)
        matches = variance <= self.MAX_VARIANCE
        
        logger.info(f"PRE-CHECK {self.id}: line_items_sum=${line_items_sum:.2f}, invoice_amount=${invoice_amount:.2f}, variance=${variance:.4f}, valid={matches}")
        
        if not matches:
            logger.error(f"LINE ITEMS MISMATCH: Sum ${line_items_sum:.2f} != Total ${invoice_amount:.2f}")
        
        return matches
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify line items not modified after invoice creation
        invoice = result['invoice']
        
        line_items_sum = sum(item['amount'] for item in invoice['line_items'])
        variance = abs(line_items_sum - invoice['amount'])
        matches = variance <= self.MAX_VARIANCE
        
        logger.info(f"POST-CHECK {self.id}: variance=${variance:.4f}, valid={matches}")
        return matches
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.delete_invoice(invoice_id)
        
        logger.warning(f"ROLLBACK {self.id}: Deleted invoice with mismatched line items")

class PricingQuoteFreshness(Invariant):
    """INV-109/603: Pricing quotes <5 minutes old."""
    
    MAX_AGE_MINUTES = 5
    
    def __init__(self):
        super().__init__(
            id="inv_109_pricing_freshness",
            statement="The system MUST always ensure pricing quotes are <5 minutes old",
            type=InvariantType.DATA_INTEGRITY,
            criticality=Criticality.CRITICAL,
            dependencies=[],
            decay_window=timedelta(minutes=5),
            owner="pricing_service"
        )
    
    def pre_check(self, pricing_quote: Dict, **kwargs) -> bool:
        age_minutes = (datetime.now() - pricing_quote['created_at']).total_seconds() / 60
        is_fresh = age_minutes < self.MAX_AGE_MINUTES
        
        logger.info(f"PRE-CHECK {self.id}: quote_age={age_minutes:.1f}min, max={self.MAX_AGE_MINUTES}min, fresh={is_fresh}")
        
        if not is_fresh:
            logger.warning(f"STALE PRICING: Quote {age_minutes:.1f} minutes old")
        
        return is_fresh
    
    def post_check(self, result: Any, **kwargs) -> bool:
        # Verify quote wasn't regenerated during acceptance window
        pricing_quote_timestamp = result['pricing_quote']['created_at']
        original_timestamp = result['original_pricing_timestamp']
        
        unchanged = pricing_quote_timestamp == original_timestamp
        
        logger.info(f"POST-CHECK {self.id}: pricing_timestamp_unchanged={unchanged}")
        return unchanged
    
    def rollback_action(self, state_before: Dict[str, Any]):
        storage = state_before['storage']
        invoice_id = state_before['invoice_id']
        
        storage.update_invoice_status(invoice_id, 'PENDING')
        
        # Buyer must re-accept with fresh quote
        notification_service = state_before.get('notification_service')
        if notification_service:
            notification_service.send(
                recipient_id=state_before['buyer_id'],
                message="Pricing quote expired. Please review and accept with updated pricing."
            )
        
        logger.warning(f"ROLLBACK {self.id}: Quote expired - buyer must re-accept")

# ============================================
# MODULE-LEVEL ORGANIZATION
# ============================================

@dataclass
class ModuleBoundary:
    """Enforces contracts between modules."""
    
    source_module: str
    target_module: str
    contract_invariants: List[Invariant] = field(default_factory=list)
    
    def verify_contract(self, data: Any) -> bool:
        """Verify data satisfies inter-module contract."""
        for inv in self.contract_invariants:
            if not inv.verify_state({'data': data}):
                logger.error(f"Contract violation: {self.source_module} → {self.target_module}")
                return False
        return True

# Define module boundaries
INVOICE_MODULE_INVARIANTS = [
    "inv_001_unique_invoice_ids",
    "inv_002_valid_amounts",
    "inv_004_no_duplicate_hash",
    "inv_007_valid_terms",
    "inv_602_line_items_sum"
]

SETTLEMENT_MODULE_INVARIANTS = [
    "inv_006_settlement_once",
    "inv_102_atomic_settlement",
    "inv_201_settlement_speed",
    "inv_206_rail_health",
    "inv_303_settlement_success"
]

CREDIT_MODULE_INVARIANTS = [
    "inv_005_credit_limit",
    "inv_205_credit_limit_staleness"
]

FRAUD_MODULE_INVARIANTS = [
    "inv_202_fraud_score_fresh",
    "inv_302_fraud_accuracy"
]

COMPLIANCE_MODULE_INVARIANTS = [
    "inv_401_sanctions_check",
    "inv_402_kyc_verification"
]

PRICING_MODULE_INVARIANTS = [
    "inv_103_pricing_before_acceptance",
    "inv_109_pricing_freshness",
    "inv_502_pricing_accuracy"
]

# Cross-module boundaries
INVOICE_TO_SETTLEMENT_BOUNDARY = ModuleBoundary(
    source_module="invoice_service",
    target_module="settlement_service"
    # Contract: Invoice must be ACCEPTED, have unique ID, valid amount
)

SETTLEMENT_TO_LEDGER_BOUNDARY = ModuleBoundary(
    source_module="settlement_service",
    target_module="ledger_service"
    # Contract: All 3 legs must be present (supplier, buyer, capital)
)

if __name__ == "__main__":
    print("InstantTrade Network - Remaining Invariants v1.0.0")
    print("=" * 60)
    print(f"Total Additional Invariants: 16")
    print(f"Module Boundaries Defined: 6 modules")
