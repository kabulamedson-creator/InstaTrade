"""
InstantTrade Network (ITN) - Advanced Fraud Scoring
Version: 2.0.0
Feature: Multi-factor fraud detection with machine learning signals

Combines multiple signals to detect fraudulent invoices:
- Velocity checks (rapid invoice creation)
- Network analysis (new supplier-buyer relationships)
- Amount patterns (unusual invoice sizes)
- Behavioral anomalies (time of day, frequency)
- Historical fraud patterns
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from enum import Enum
import random
import hashlib

from itn_enforcement_v1 import (
    Invariant,
    InvariantType,
    Criticality,
    InvariantEnforcer,
    DecisionLedger,
    InvariantViolation,
    logger
)

# ============================================
# FRAUD SIGNALS
# ============================================

class FraudSignal(Enum):
    """Individual fraud indicators."""
    VELOCITY_SPIKE = "velocity_spike"  # Too many invoices too fast
    NEW_RELATIONSHIP = "new_relationship"  # First transaction between parties
    UNUSUAL_AMOUNT = "unusual_amount"  # Amount outside normal range
    OFF_HOURS = "off_hours"  # Created during unusual hours
    ROUND_AMOUNT = "round_amount"  # Suspiciously round number
    DUPLICATE_PATTERN = "duplicate_pattern"  # Similar to previous fraud
    GEOGRAPHIC_MISMATCH = "geographic_mismatch"  # Unusual geography
    RAPID_ACCEPTANCE = "rapid_acceptance"  # Accepted too quickly

@dataclass
class SignalScore:
    """Score for individual fraud signal."""
    signal: FraudSignal
    weight: float  # 0.0 to 1.0
    triggered: bool
    confidence: float  # 0.0 to 1.0
    reason: str
    
    @property
    def contribution(self) -> float:
        """How much this signal contributes to total score."""
        if not self.triggered:
            return 0.0
        return self.weight * self.confidence

# ============================================
# FRAUD SCORE
# ============================================

@dataclass
class FraudScore:
    """Complete fraud assessment for an invoice."""
    invoice_id: str
    score: float  # 0.0 (clean) to 1.0 (definitely fraud)
    signals: List[SignalScore]
    calculated_at: datetime = field(default_factory=datetime.now)
    
    # Classification
    risk_level: str = "UNKNOWN"  # LOW, MEDIUM, HIGH, CRITICAL
    action: str = "UNKNOWN"  # APPROVE, REVIEW, REJECT
    
    def __post_init__(self):
        """Classify risk level and recommended action."""
        if self.score < 0.25:
            self.risk_level = "LOW"
            self.action = "APPROVE"
        elif self.score < 0.50:
            self.risk_level = "MEDIUM"
            self.action = "REVIEW"
        elif self.score < 0.75:
            self.risk_level = "HIGH"
            self.action = "REVIEW"
        else:
            self.risk_level = "CRITICAL"
            self.action = "REJECT"
    
    def get_triggered_signals(self) -> List[SignalScore]:
        """Get signals that triggered."""
        return [s for s in self.signals if s.triggered]
    
    def to_dict(self) -> Dict:
        return {
            'invoice_id': self.invoice_id,
            'score': self.score,
            'score_percent': f"{self.score:.1%}",
            'risk_level': self.risk_level,
            'action': self.action,
            'calculated_at': self.calculated_at.isoformat(),
            'triggered_signals': [
                {
                    'signal': s.signal.value,
                    'weight': s.weight,
                    'confidence': s.confidence,
                    'contribution': s.contribution,
                    'reason': s.reason
                }
                for s in self.get_triggered_signals()
            ]
        }

# ============================================
# TRANSACTION HISTORY
# ============================================

@dataclass
class TransactionHistory:
    """Historical transaction data for fraud detection."""
    supplier_id: str
    buyer_id: str
    
    # Supplier history
    supplier_total_invoices: int = 0
    supplier_avg_amount: float = 0.0
    supplier_account_age_days: int = 0
    supplier_fraud_incidents: int = 0
    
    # Buyer history
    buyer_total_invoices: int = 0
    buyer_avg_amount: float = 0.0
    buyer_account_age_days: int = 0
    buyer_dispute_rate: float = 0.0
    
    # Relationship history
    relationship_invoice_count: int = 0
    relationship_first_transaction: Optional[datetime] = None
    
    # Recent activity
    supplier_invoices_last_hour: int = 0
    supplier_invoices_last_day: int = 0

# ============================================
# FRAUD DETECTION ENGINE
# ============================================

class FraudDetectionEngine:
    """Advanced fraud detection with multiple signals."""
    
    # Signal weights (sum to 1.0)
    SIGNAL_WEIGHTS = {
        FraudSignal.VELOCITY_SPIKE: 0.25,
        FraudSignal.NEW_RELATIONSHIP: 0.15,
        FraudSignal.UNUSUAL_AMOUNT: 0.20,
        FraudSignal.OFF_HOURS: 0.05,
        FraudSignal.ROUND_AMOUNT: 0.05,
        FraudSignal.DUPLICATE_PATTERN: 0.15,
        FraudSignal.GEOGRAPHIC_MISMATCH: 0.10,
        FraudSignal.RAPID_ACCEPTANCE: 0.05
    }
    
    def __init__(self):
        self.transaction_history: Dict[str, TransactionHistory] = {}
        self.fraud_patterns: List[Dict] = []
        self.known_fraud_hashes: set = set()
    
    def calculate_score(
        self,
        invoice_id: str,
        supplier_id: str,
        buyer_id: str,
        amount: float,
        line_items: List[Dict],
        created_at: datetime
    ) -> FraudScore:
        """
        Calculate comprehensive fraud score.
        
        Returns FraudScore with detailed signal breakdown.
        """
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[FRAUD] Calculating score for {invoice_id}")
        logger.info(f"  Supplier: {supplier_id}")
        logger.info(f"  Buyer: {buyer_id}")
        logger.info(f"  Amount: ${amount:,.2f}")
        logger.info(f"{'='*60}\n")
        
        # Get transaction history
        history = self._get_history(supplier_id, buyer_id)
        
        # Evaluate all signals
        signals = [
            self._check_velocity(supplier_id, history),
            self._check_new_relationship(history),
            self._check_unusual_amount(amount, history),
            self._check_off_hours(created_at),
            self._check_round_amount(amount),
            self._check_duplicate_pattern(supplier_id, buyer_id, amount, line_items),
            self._check_geographic_mismatch(supplier_id, buyer_id),
            self._check_rapid_acceptance(invoice_id)
        ]
        
        # Calculate weighted score
        total_score = sum(s.contribution for s in signals)
        
        fraud_score = FraudScore(
            invoice_id=invoice_id,
            score=min(1.0, total_score),  # Cap at 1.0
            signals=signals
        )
        
        logger.info(f"\n[FRAUD] Score calculated:")
        logger.info(f"  Total score: {fraud_score.score:.2%}")
        logger.info(f"  Risk level: {fraud_score.risk_level}")
        logger.info(f"  Action: {fraud_score.action}")
        logger.info(f"  Triggered signals: {len(fraud_score.get_triggered_signals())}")
        
        for signal in fraud_score.get_triggered_signals():
            logger.info(f"    - {signal.signal.value}: {signal.contribution:.2%} ({signal.reason})")
        
        return fraud_score
    
    def _check_velocity(self, supplier_id: str, history: TransactionHistory) -> SignalScore:
        """Check for velocity anomalies."""
        
        # Suspicious if >10 invoices in last hour OR >50 in last day
        triggered = (
            history.supplier_invoices_last_hour > 10 or
            history.supplier_invoices_last_day > 50
        )
        
        confidence = 0.0
        reason = "Normal velocity"
        
        if history.supplier_invoices_last_hour > 10:
            confidence = min(1.0, history.supplier_invoices_last_hour / 20)
            reason = f"{history.supplier_invoices_last_hour} invoices in last hour"
        elif history.supplier_invoices_last_day > 50:
            confidence = min(1.0, history.supplier_invoices_last_day / 100)
            reason = f"{history.supplier_invoices_last_day} invoices in last day"
        
        return SignalScore(
            signal=FraudSignal.VELOCITY_SPIKE,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.VELOCITY_SPIKE],
            triggered=triggered,
            confidence=confidence,
            reason=reason
        )
    
    def _check_new_relationship(self, history: TransactionHistory) -> SignalScore:
        """Check if this is a new buyer-supplier relationship."""
        
        is_new = history.relationship_invoice_count == 0
        
        # New relationships are slightly suspicious but not necessarily fraud
        confidence = 0.5 if is_new else 0.0
        reason = "First transaction between parties" if is_new else "Established relationship"
        
        return SignalScore(
            signal=FraudSignal.NEW_RELATIONSHIP,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.NEW_RELATIONSHIP],
            triggered=is_new,
            confidence=confidence,
            reason=reason
        )
    
    def _check_unusual_amount(self, amount: float, history: TransactionHistory) -> SignalScore:
        """Check if amount is unusual for this supplier."""
        
        if history.supplier_avg_amount == 0:
            return SignalScore(
                signal=FraudSignal.UNUSUAL_AMOUNT,
                weight=self.SIGNAL_WEIGHTS[FraudSignal.UNUSUAL_AMOUNT],
                triggered=False,
                confidence=0.0,
                reason="No historical average"
            )
        
        # Suspicious if >3x or <0.1x average
        ratio = amount / history.supplier_avg_amount
        triggered = ratio > 3.0 or ratio < 0.1
        
        confidence = 0.0
        reason = "Amount within normal range"
        
        if ratio > 3.0:
            confidence = min(1.0, (ratio - 3.0) / 7.0)  # Max confidence at 10x
            reason = f"${amount:,.0f} is {ratio:.1f}x higher than average ${history.supplier_avg_amount:,.0f}"
        elif ratio < 0.1:
            confidence = min(1.0, (0.1 - ratio) * 10)
            reason = f"${amount:,.0f} is {1/ratio:.1f}x lower than average ${history.supplier_avg_amount:,.0f}"
        
        return SignalScore(
            signal=FraudSignal.UNUSUAL_AMOUNT,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.UNUSUAL_AMOUNT],
            triggered=triggered,
            confidence=confidence,
            reason=reason
        )
    
    def _check_off_hours(self, created_at: datetime) -> SignalScore:
        """Check if invoice created during unusual hours."""
        
        hour = created_at.hour
        
        # Suspicious if created between 2 AM - 5 AM
        is_off_hours = 2 <= hour < 5
        confidence = 0.6 if is_off_hours else 0.0
        reason = f"Created at {hour}:00 (unusual)" if is_off_hours else "Normal business hours"
        
        return SignalScore(
            signal=FraudSignal.OFF_HOURS,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.OFF_HOURS],
            triggered=is_off_hours,
            confidence=confidence,
            reason=reason
        )
    
    def _check_round_amount(self, amount: float) -> SignalScore:
        """Check if amount is suspiciously round."""
        
        # Suspicious if exact multiple of $10,000
        is_round = amount % 10000 == 0 and amount >= 10000
        confidence = 0.3 if is_round else 0.0
        reason = f"Exact ${amount:,.0f} (suspiciously round)" if is_round else "Non-round amount"
        
        return SignalScore(
            signal=FraudSignal.ROUND_AMOUNT,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.ROUND_AMOUNT],
            triggered=is_round,
            confidence=confidence,
            reason=reason
        )
    
    def _check_duplicate_pattern(
        self,
        supplier_id: str,
        buyer_id: str,
        amount: float,
        line_items: List[Dict]
    ) -> SignalScore:
        """Check if invoice matches known fraud patterns."""
        
        # Create pattern hash
        pattern = f"{supplier_id}:{buyer_id}:{amount}:{len(line_items)}"
        pattern_hash = hashlib.md5(pattern.encode()).hexdigest()
        
        is_known_fraud = pattern_hash in self.known_fraud_hashes
        confidence = 1.0 if is_known_fraud else 0.0
        reason = "Matches known fraud pattern" if is_known_fraud else "No match to known fraud"
        
        return SignalScore(
            signal=FraudSignal.DUPLICATE_PATTERN,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.DUPLICATE_PATTERN],
            triggered=is_known_fraud,
            confidence=confidence,
            reason=reason
        )
    
    def _check_geographic_mismatch(self, supplier_id: str, buyer_id: str) -> SignalScore:
        """Check for geographic anomalies (simplified)."""
        
        # Mock: 10% chance of geographic mismatch
        is_mismatch = random.random() < 0.10
        confidence = 0.7 if is_mismatch else 0.0
        reason = "Geographic mismatch detected" if is_mismatch else "Normal geography"
        
        return SignalScore(
            signal=FraudSignal.GEOGRAPHIC_MISMATCH,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.GEOGRAPHIC_MISMATCH],
            triggered=is_mismatch,
            confidence=confidence,
            reason=reason
        )
    
    def _check_rapid_acceptance(self, invoice_id: str) -> SignalScore:
        """Check if invoice was accepted too quickly (would check in production)."""
        
        # This check happens at acceptance time, not creation
        return SignalScore(
            signal=FraudSignal.RAPID_ACCEPTANCE,
            weight=self.SIGNAL_WEIGHTS[FraudSignal.RAPID_ACCEPTANCE],
            triggered=False,
            confidence=0.0,
            reason="Not yet accepted"
        )
    
    def _get_history(self, supplier_id: str, buyer_id: str) -> TransactionHistory:
        """Get transaction history (mocked for demo)."""
        
        key = f"{supplier_id}:{buyer_id}"
        
        if key not in self.transaction_history:
            # Create mock history
            self.transaction_history[key] = TransactionHistory(
                supplier_id=supplier_id,
                buyer_id=buyer_id,
                supplier_total_invoices=random.randint(0, 100),
                supplier_avg_amount=random.uniform(10000, 100000),
                supplier_account_age_days=random.randint(1, 1000),
                relationship_invoice_count=random.randint(0, 50),
                supplier_invoices_last_hour=random.randint(0, 5),
                supplier_invoices_last_day=random.randint(0, 30)
            )
        
        return self.transaction_history[key]
    
    def report_fraud(self, invoice_id: str, pattern_hash: str):
        """Report confirmed fraud for pattern learning."""
        self.known_fraud_hashes.add(pattern_hash)
        logger.warning(f"[FRAUD] Reported fraud pattern: {pattern_hash}")

# ============================================
# FRAUD SERVICE WITH ENFORCEMENT
# ============================================

class FraudService:
    """Service for fraud detection with invariant enforcement."""
    
    FRAUD_THRESHOLD = 0.75
    
    def __init__(self, ledger: DecisionLedger):
        self.ledger = ledger
        self.engine = FraudDetectionEngine()
        self.scores: Dict[str, FraudScore] = {}
    
    def score_invoice(
        self,
        invoice_id: str,
        supplier_id: str,
        buyer_id: str,
        amount: float,
        line_items: List[Dict]
    ) -> FraudScore:
        """
        Score invoice for fraud.
        
        Enforces INV-302: All scores >0.75 must be blocked.
        """
        
        score = self.engine.calculate_score(
            invoice_id=invoice_id,
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            amount=amount,
            line_items=line_items,
            created_at=datetime.now()
        )
        
        # Store score
        self.scores[invoice_id] = score
        
        # Enforce fraud threshold
        if score.score >= self.FRAUD_THRESHOLD:
            logger.error(f"\n{'='*60}")
            logger.error(f"🚨 FRAUD DETECTED: {invoice_id}")
            logger.error(f"   Score: {score.score:.1%}")
            logger.error(f"   Action: REJECT")
            logger.error(f"{'='*60}\n")
            
            raise InvariantViolation(f"Fraud score {score.score:.1%} exceeds threshold {self.FRAUD_THRESHOLD:.1%}")
        
        return score
    
    def get_fraud_score(self, invoice_id: str) -> Optional[Dict]:
        """Get existing fraud score."""
        score = self.scores.get(invoice_id)
        
        if score is None:
            return None
        
        return {
            'score': score.score,
            'calculated_at': score.calculated_at
        }

# ============================================
# DEMONSTRATION
# ============================================

def demonstrate_fraud_scoring():
    """Demonstrate advanced fraud scoring."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - ADVANCED FRAUD SCORING")
    print("="*80 + "\n")
    
    # Initialize service
    ledger = DecisionLedger()
    fraud_service = FraudService(ledger)
    
    # ===== TEST 1: Clean Invoice =====
    print("\n" + "-"*80)
    print("TEST 1: Score clean invoice (expect LOW risk)")
    print("-"*80)
    
    score_1 = fraud_service.score_invoice(
        invoice_id="INV-CLEAN-001",
        supplier_id="SUP-001",
        buyer_id="BUY-001",
        amount=50000.00,
        line_items=[{"desc": "Widgets", "amt": 50000}]
    )
    
    print(f"\n✅ Clean Invoice:")
    print(f"   Score: {score_1.score:.1%}")
    print(f"   Risk: {score_1.risk_level}")
    print(f"   Action: {score_1.action}")
    
    # ===== TEST 2: Suspicious Invoice =====
    print("\n" + "-"*80)
    print("TEST 2: Score suspicious invoice (expect MEDIUM/HIGH risk)")
    print("-"*80)
    
    # Set up history to trigger signals
    fraud_service.engine.transaction_history["SUP-002:BUY-002"] = TransactionHistory(
        supplier_id="SUP-002",
        buyer_id="BUY-002",
        supplier_avg_amount=10000.00,  # Will trigger unusual amount
        supplier_invoices_last_hour=15,  # Will trigger velocity
        relationship_invoice_count=0  # Will trigger new relationship
    )
    
    score_2 = fraud_service.score_invoice(
        invoice_id="INV-SUSPECT-001",
        supplier_id="SUP-002",
        buyer_id="BUY-002",
        amount=100000.00,  # 10x average (unusual)
        line_items=[{"desc": "Equipment", "amt": 100000}]
    )
    
    print(f"\n⚠️ Suspicious Invoice:")
    print(f"   Score: {score_2.score:.1%}")
    print(f"   Risk: {score_2.risk_level}")
    print(f"   Action: {score_2.action}")
    print(f"\n   Triggered signals:")
    for signal in score_2.get_triggered_signals():
        print(f"   - {signal.signal.value}: {signal.contribution:.1%} ({signal.reason})")
    
    # ===== TEST 3: Fraudulent Invoice (Should Block) =====
    print("\n" + "-"*80)
    print("TEST 3: Score fraudulent invoice (expect CRITICAL risk + BLOCK)")
    print("-"*80)
    
    # Set up for maximum fraud signals
    fraud_service.engine.transaction_history["SUP-FRAUD:BUY-FRAUD"] = TransactionHistory(
        supplier_id="SUP-FRAUD",
        buyer_id="BUY-FRAUD",
        supplier_avg_amount=5000.00,
        supplier_invoices_last_hour=25,  # High velocity
        supplier_invoices_last_day=100,  # Very high velocity
        relationship_invoice_count=0  # New relationship
    )
    
    try:
        score_3 = fraud_service.score_invoice(
            invoice_id="INV-FRAUD-001",
            supplier_id="SUP-FRAUD",
            buyer_id="BUY-FRAUD",
            amount=500000.00,  # 100x average
            line_items=[{"desc": "Fraud", "amt": 500000}]
        )
        print(f"\n❌ TEST FAILED: Fraudulent invoice not blocked (score: {score_3.score:.1%})")
    except InvariantViolation as e:
        print(f"\n✅ TEST PASSED: Fraudulent invoice blocked")
        print(f"   Reason: {e}")
    
    # ===== SUMMARY =====
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    print(f"\nFraud Detection Signals:")
    for signal in FraudSignal:
        weight = FraudDetectionEngine.SIGNAL_WEIGHTS[signal]
        print(f"  - {signal.value}: {weight:.0%} weight")
    
    print(f"\nInvoices Scored:")
    for invoice_id, score in fraud_service.scores.items():
        print(f"  - {invoice_id}: {score.score:.1%} ({score.risk_level}) → {score.action}")
    
    print(f"\nThreshold Enforcement:")
    print(f"  Fraud threshold: {fraud_service.FRAUD_THRESHOLD:.0%}")
    print(f"  Invoices blocked: {sum(1 for s in fraud_service.scores.values() if s.score >= fraud_service.FRAUD_THRESHOLD)}")
    print(f"  Invoices approved: {sum(1 for s in fraud_service.scores.values() if s.score < fraud_service.FRAUD_THRESHOLD)}")
    
    print("\n" + "="*80)
    print("FRAUD SCORING SYSTEM COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    demonstrate_fraud_scoring()
