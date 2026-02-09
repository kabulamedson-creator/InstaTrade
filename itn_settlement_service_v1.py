"""
InstantTrade Network (ITN) - Settlement Execution Service
Version: 1.0.0
Phase: 3 - Feature Implementation

Complete settlement with atomic 3-leg transfers and full enforcement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum
import time

# Import enforcement layer
from itn_enforcement_v1 import (
    InvariantEnforcer,
    DecisionLedger,
    SettlementExactlyOnce,
    InvariantViolation,
    logger
)

from itn_remaining_invariants_v1 import (
    AtomicSettlementTransition,
    SettlementWithin5Seconds
)

# ============================================
# DATA MODELS
# ============================================

class SettlementStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"

@dataclass
class SettlementLeg:
    """Individual leg of settlement (credit, debit, or advance)."""
    leg_type: str  # "CREDIT" | "DEBIT" | "ADVANCE"
    account_id: str
    amount: float
    timestamp: Optional[datetime] = None
    transaction_id: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            'leg_type': self.leg_type,
            'account_id': self.account_id,
            'amount': self.amount,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'transaction_id': self.transaction_id
        }

@dataclass
class Settlement:
    """Settlement record with atomic 3-leg transfer."""
    id: str
    invoice_id: str
    
    # The 3 legs
    supplier_credit: SettlementLeg
    buyer_debit: SettlementLeg
    capital_advance: SettlementLeg
    
    # Metadata
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    status: SettlementStatus = SettlementStatus.PENDING
    
    # Pricing
    discount_rate: float = 0.0
    buyer_cost: float = 0.0
    
    def duration_seconds(self) -> Optional[float]:
        """Calculate settlement duration."""
        if self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'supplier_credit': self.supplier_credit.to_dict(),
            'buyer_debit': self.buyer_debit.to_dict(),
            'capital_advance': self.capital_advance.to_dict(),
            'started_at': self.started_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'status': self.status.value,
            'discount_rate': self.discount_rate,
            'buyer_cost': self.buyer_cost,
            'duration_seconds': self.duration_seconds()
        }

# ============================================
# SETTLEMENT LEDGER
# ============================================

class SettlementLedger:
    """Immutable ledger of all settlements."""
    
    def __init__(self):
        self.settlements: List[Settlement] = []
        self.credits: List[Dict] = []
        self.debits: List[Dict] = []
        self.advances: List[Dict] = []
    
    def count_settlements(self, invoice_id: str) -> int:
        """Count settlements for invoice."""
        return len([s for s in self.settlements if s.invoice_id == invoice_id])
    
    def add_settlement(self, settlement: Settlement):
        """Record settlement (append-only)."""
        self.settlements.append(settlement)
        
        # Record individual legs
        self.credits.append({
            'invoice_id': settlement.invoice_id,
            'account_id': settlement.supplier_credit.account_id,
            'amount': settlement.supplier_credit.amount,
            'timestamp': settlement.supplier_credit.timestamp
        })
        
        self.debits.append({
            'invoice_id': settlement.invoice_id,
            'account_id': settlement.buyer_debit.account_id,
            'amount': settlement.buyer_debit.amount,
            'timestamp': settlement.buyer_debit.timestamp
        })
        
        self.advances.append({
            'invoice_id': settlement.invoice_id,
            'account_id': settlement.capital_advance.account_id,
            'amount': settlement.capital_advance.amount,
            'timestamp': settlement.capital_advance.timestamp
        })
        
        logger.info(f"[LEDGER] Recorded settlement {settlement.id} for invoice {settlement.invoice_id}")
    
    def has_credit(self, invoice_id: str, account_id: str) -> bool:
        """Check if credit leg exists."""
        return any(
            c['invoice_id'] == invoice_id and c['account_id'] == account_id
            for c in self.credits
        )
    
    def has_debit(self, invoice_id: str, account_id: str) -> bool:
        """Check if debit leg exists."""
        return any(
            d['invoice_id'] == invoice_id and d['account_id'] == account_id
            for d in self.debits
        )
    
    def has_advance(self, invoice_id: str, account_id: str) -> bool:
        """Check if advance leg exists."""
        return any(
            a['invoice_id'] == invoice_id and a['account_id'] == account_id
            for a in self.advances
        )
    
    def add_correction_entry(self, invoice_id: str, reason: str):
        """Add correction entry (for rollback)."""
        correction = {
            'invoice_id': invoice_id,
            'type': 'CORRECTION',
            'reason': reason,
            'timestamp': datetime.now()
        }
        self.settlements.append(correction)
        logger.warning(f"[LEDGER] Added correction for invoice {invoice_id}: {reason}")
    
    def sum_all_credits(self) -> float:
        """Sum all credits (for reconciliation)."""
        return sum(c.get('amount', 0) for c in self.credits)
    
    def sum_all_debits(self) -> float:
        """Sum all debits (for reconciliation)."""
        return sum(d.get('amount', 0) for d in self.debits)

# ============================================
# SETTLEMENT RAILS (MOCK)
# ============================================

@dataclass
class SettlementRail:
    """Mock settlement rail (RTP, FedNow, ACH, etc.)."""
    name: str
    status: str = "UP"
    latency_ms: int = 500
    last_health_check: datetime = field(default_factory=datetime.now)
    
    def execute_transfer(self, from_account: str, to_account: str, amount: float) -> str:
        """Execute transfer and return transaction ID."""
        # Simulate network latency
        time.sleep(self.latency_ms / 1000)
        
        transaction_id = f"TXN-{from_account}-{to_account}-{int(time.time()*1000)}"
        logger.info(f"[{self.name}] Transfer: {from_account} → {to_account} ${amount:,.2f} (txn: {transaction_id})")
        
        return transaction_id
    
    def health_check(self) -> bool:
        """Check rail health."""
        self.last_health_check = datetime.now()
        return self.status == "UP"

class SettlementRailManager:
    """Manages multiple settlement rails with failover."""
    
    def __init__(self):
        self.rails = [
            SettlementRail(name="RTP", latency_ms=200),
            SettlementRail(name="FedNow", latency_ms=300),
            SettlementRail(name="ACH", latency_ms=1000)
        ]
    
    def get_primary_rail(self) -> SettlementRail:
        """Get fastest available rail."""
        for rail in sorted(self.rails, key=lambda r: r.latency_ms):
            if rail.health_check():
                return rail
        raise Exception("No settlement rails available")
    
    def get_all_rails(self) -> List[Dict]:
        """Get all rails with health status."""
        return [
            {
                'name': rail.name,
                'status': rail.status,
                'latency_ms': rail.latency_ms,
                'last_health_check': rail.last_health_check
            }
            for rail in self.rails
        ]

# ============================================
# ACCOUNT BALANCES (MOCK)
# ============================================

class BalanceService:
    """Mock balance management."""
    
    def __init__(self):
        self.balances = {
            'SUP-001': 50000.00,
            'BUY-001': 500000.00,
            'CAP-001': 10000000.00  # Capital provider
        }
        self.snapshots = []
    
    def get_balance(self, account_id: str) -> float:
        """Get current balance."""
        return self.balances.get(account_id, 0.0)
    
    def can_receive(self, account_id: str, amount: float) -> bool:
        """Check if account can receive funds."""
        return account_id in self.balances
    
    def can_pay(self, account_id: str, amount: float) -> bool:
        """Check if account has sufficient balance."""
        return self.get_balance(account_id) >= amount
    
    def can_advance(self, account_id: str, amount: float) -> bool:
        """Check if capital provider has liquidity."""
        return self.get_balance(account_id) >= amount
    
    def credit(self, account_id: str, amount: float):
        """Add funds to account."""
        if account_id in self.balances:
            self.balances[account_id] += amount
            logger.info(f"[BALANCE] Credited {account_id}: +${amount:,.2f} (new balance: ${self.balances[account_id]:,.2f})")
    
    def debit(self, account_id: str, amount: float):
        """Remove funds from account."""
        if account_id in self.balances:
            if self.balances[account_id] >= amount:
                self.balances[account_id] -= amount
                logger.info(f"[BALANCE] Debited {account_id}: -${amount:,.2f} (new balance: ${self.balances[account_id]:,.2f})")
            else:
                raise Exception(f"Insufficient balance for {account_id}")
    
    def snapshot(self) -> Dict[str, float]:
        """Capture balance snapshot (for rollback)."""
        snapshot = self.balances.copy()
        self.snapshots.append(snapshot)
        return snapshot
    
    def restore_balances(self, snapshot: Dict[str, float]):
        """Restore balances from snapshot."""
        self.balances = snapshot.copy()
        logger.warning(f"[BALANCE] Restored balances from snapshot")

# ============================================
# SETTLEMENT SERVICE
# ============================================

class SettlementService:
    """Service for executing settlements with atomic guarantees."""
    
    def __init__(
        self,
        ledger: SettlementLedger,
        decision_ledger: DecisionLedger,
        rail_manager: SettlementRailManager,
        balance_service: BalanceService
    ):
        self.ledger = ledger
        self.decision_ledger = decision_ledger
        self.rail_manager = rail_manager
        self.balance_service = balance_service
        
        # Initialize invariants for settlement
        self.invariants = [
            SettlementExactlyOnce(),
            AtomicSettlementTransition(),
            SettlementWithin5Seconds()
        ]
        
        # Initialize enforcer
        self.enforcer = InvariantEnforcer(self.invariants, decision_ledger)
        
        logger.info("[SETTLEMENT_SERVICE] Initialized with 3 invariants")
    
    def execute_settlement(
        self,
        invoice_id: str,
        supplier_id: str,
        buyer_id: str,
        capital_provider_id: str,
        amount: float,
        discount_rate: float = 0.05  # 5% annualized
    ) -> Settlement:
        """
        Execute atomic settlement with 3 legs:
        1. Credit supplier (instant payment)
        2. Debit buyer (or record obligation)
        3. Capital provider advances funds
        
        All 3 legs must succeed or all rollback.
        """
        
        settlement_id = f"SET-{invoice_id}-{int(time.time())}"
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[SETTLEMENT] Executing settlement {settlement_id}")
        logger.info(f"  Invoice: {invoice_id}")
        logger.info(f"  Supplier: {supplier_id}")
        logger.info(f"  Buyer: {buyer_id}")
        logger.info(f"  Capital: {capital_provider_id}")
        logger.info(f"  Amount: ${amount:,.2f}")
        logger.info(f"  Rate: {discount_rate:.2%}")
        logger.info(f"{'='*60}\n")
        
        # Calculate buyer cost (amount + financing cost)
        buyer_cost = amount * (1 + discount_rate)
        
        # Get settlement rail
        rail = self.rail_manager.get_primary_rail()
        logger.info(f"[SETTLEMENT] Using rail: {rail.name} (latency: {rail.latency_ms}ms)")
        
        # Record acceptance timestamp (for latency check)
        acceptance_timestamp = datetime.now()
        
        # Snapshot balances before settlement
        balances_snapshot = self.balance_service.snapshot()
        
        # Define settlement action
        def _execute_settlement_action() -> Dict[str, Any]:
            """Execute the 3-leg atomic settlement."""
            
            settlement = Settlement(
                id=settlement_id,
                invoice_id=invoice_id,
                supplier_credit=SettlementLeg(
                    leg_type="CREDIT",
                    account_id=supplier_id,
                    amount=amount
                ),
                buyer_debit=SettlementLeg(
                    leg_type="DEBIT",
                    account_id=buyer_id,
                    amount=buyer_cost
                ),
                capital_advance=SettlementLeg(
                    leg_type="ADVANCE",
                    account_id=capital_provider_id,
                    amount=amount
                ),
                discount_rate=discount_rate,
                buyer_cost=buyer_cost,
                status=SettlementStatus.IN_PROGRESS
            )
            
            # ===== LEG 1: Credit Supplier =====
            logger.info(f"[SETTLEMENT] Leg 1/3: Crediting supplier {supplier_id}")
            
            txn_1 = rail.execute_transfer(
                from_account=capital_provider_id,
                to_account=supplier_id,
                amount=amount
            )
            
            self.balance_service.credit(supplier_id, amount)
            self.balance_service.debit(capital_provider_id, amount)
            
            settlement.supplier_credit.timestamp = datetime.now()
            settlement.supplier_credit.transaction_id = txn_1
            
            logger.info(f"[SETTLEMENT] ✅ Leg 1 complete")
            
            # ===== LEG 2: Debit Buyer =====
            logger.info(f"[SETTLEMENT] Leg 2/3: Debiting buyer {buyer_id}")
            
            txn_2 = rail.execute_transfer(
                from_account=buyer_id,
                to_account=capital_provider_id,
                amount=buyer_cost
            )
            
            self.balance_service.debit(buyer_id, buyer_cost)
            self.balance_service.credit(capital_provider_id, buyer_cost)
            
            settlement.buyer_debit.timestamp = datetime.now()
            settlement.buyer_debit.transaction_id = txn_2
            
            logger.info(f"[SETTLEMENT] ✅ Leg 2 complete")
            
            # ===== LEG 3: Record Capital Advance =====
            logger.info(f"[SETTLEMENT] Leg 3/3: Recording capital advance")
            
            settlement.capital_advance.timestamp = datetime.now()
            settlement.capital_advance.transaction_id = f"ADV-{settlement_id}"
            
            logger.info(f"[SETTLEMENT] ✅ Leg 3 complete")
            
            # ===== Finalize Settlement =====
            settlement.completed_at = datetime.now()
            settlement.status = SettlementStatus.COMPLETED
            
            # Record in ledger
            self.ledger.add_settlement(settlement)
            
            # Return state for post-checks
            return {
                'settlement': settlement,
                'invoice_id': invoice_id,
                'supplier_id': supplier_id,
                'buyer_id': buyer_id,
                'capital_provider_id': capital_provider_id,
                'ledger': self.ledger,
                'acceptance_timestamp': acceptance_timestamp,
                'settlement_timestamp': settlement.completed_at,
                'balances_snapshot': balances_snapshot,
                'account_service': self.balance_service
            }
        
        # Execute with enforcement
        try:
            result = self.enforcer.enforce_action(
                _execute_settlement_action,
                # Pre-check arguments
                invoice_id=invoice_id,
                supplier_id=supplier_id,
                buyer_id=buyer_id,
                capital_provider_id=capital_provider_id,
                amount=amount,
                ledger=self.ledger,
                account_service=self.balance_service,
                settlement_rails=self.rail_manager.get_all_rails()
            )
            
            settlement = result['settlement']
            duration = settlement.duration_seconds()
            
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ SETTLEMENT COMPLETED: {settlement_id}")
            logger.info(f"  Duration: {duration:.3f}s")
            logger.info(f"  Status: {settlement.status.value}")
            logger.info(f"  All 3 legs executed atomically ✅")
            logger.info(f"{'='*60}\n")
            
            return settlement
            
        except InvariantViolation as e:
            logger.error(f"\n{'='*60}")
            logger.error(f"❌ SETTLEMENT FAILED: {e}")
            logger.error(f"  All legs automatically rolled back")
            logger.error(f"  Balances restored to pre-settlement state")
            logger.error(f"{'='*60}\n")
            raise

# ============================================
# DEMONSTRATION
# ============================================

def demonstrate_settlement():
    """Demonstrate settlement execution with enforcement."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - SETTLEMENT EXECUTION DEMONSTRATION")
    print("="*80 + "\n")
    
    # Initialize services
    settlement_ledger = SettlementLedger()
    decision_ledger = DecisionLedger()
    rail_manager = SettlementRailManager()
    balance_service = BalanceService()
    
    settlement_service = SettlementService(
        settlement_ledger,
        decision_ledger,
        rail_manager,
        balance_service
    )
    
    # Show initial balances
    print("INITIAL BALANCES:")
    print(f"  Supplier (SUP-001): ${balance_service.get_balance('SUP-001'):,.2f}")
    print(f"  Buyer (BUY-001): ${balance_service.get_balance('BUY-001'):,.2f}")
    print(f"  Capital (CAP-001): ${balance_service.get_balance('CAP-001'):,.2f}")
    print()
    
    # ===== TEST 1: Successful Settlement =====
    print("\n" + "-"*80)
    print("TEST 1: Execute successful settlement")
    print("-"*80)
    
    try:
        settlement_1 = settlement_service.execute_settlement(
            invoice_id="INV-001",
            supplier_id="SUP-001",
            buyer_id="BUY-001",
            capital_provider_id="CAP-001",
            amount=50000.00,
            discount_rate=0.05
        )
        print(f"✅ Test 1 PASSED: Settlement completed in {settlement_1.duration_seconds():.3f}s")
    except Exception as e:
        print(f"❌ Test 1 FAILED: {e}")
    
    # Show updated balances
    print("\nBALANCES AFTER SETTLEMENT:")
    print(f"  Supplier (SUP-001): ${balance_service.get_balance('SUP-001'):,.2f} (+$50,000)")
    print(f"  Buyer (BUY-001): ${balance_service.get_balance('BUY-001'):,.2f} (-$52,500)")
    print(f"  Capital (CAP-001): ${balance_service.get_balance('CAP-001'):,.2f} (+$2,500 profit)")
    print()
    
    # ===== TEST 2: Duplicate Settlement (Should Fail) =====
    print("\n" + "-"*80)
    print("TEST 2: Attempt duplicate settlement for same invoice")
    print("-"*80)
    
    try:
        settlement_2 = settlement_service.execute_settlement(
            invoice_id="INV-001",  # Same invoice
            supplier_id="SUP-001",
            buyer_id="BUY-001",
            capital_provider_id="CAP-001",
            amount=50000.00,
            discount_rate=0.05
        )
        print(f"❌ Test 2 FAILED: Duplicate settlement allowed")
    except InvariantViolation as e:
        print(f"✅ Test 2 PASSED: Duplicate correctly blocked (INV-006)")
    
    # Balances should be unchanged
    print("\nBALANCES (Should be unchanged):")
    print(f"  Supplier (SUP-001): ${balance_service.get_balance('SUP-001'):,.2f}")
    print(f"  Buyer (BUY-001): ${balance_service.get_balance('BUY-001'):,.2f}")
    print(f"  Capital (CAP-001): ${balance_service.get_balance('CAP-001'):,.2f}")
    print()
    
    # ===== TEST 3: Insufficient Buyer Balance (Should Fail) =====
    print("\n" + "-"*80)
    print("TEST 3: Attempt settlement with insufficient buyer balance")
    print("-"*80)
    
    # Reduce buyer balance
    original_balance = balance_service.get_balance('BUY-001')
    balance_service.balances['BUY-001'] = 10000.00  # Not enough for $50k settlement
    
    try:
        settlement_3 = settlement_service.execute_settlement(
            invoice_id="INV-002",
            supplier_id="SUP-001",
            buyer_id="BUY-001",
            capital_provider_id="CAP-001",
            amount=50000.00,
            discount_rate=0.05
        )
        print(f"❌ Test 3 FAILED: Insufficient balance allowed")
    except Exception as e:
        print(f"✅ Test 3 PASSED: Insufficient balance correctly blocked")
    
    # Restore balance
    balance_service.balances['BUY-001'] = original_balance
    
    # ===== SUMMARY =====
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Total Settlements: {len(settlement_ledger.settlements)}")
    print(f"Total Credits: ${settlement_ledger.sum_all_credits():,.2f}")
    print(f"Total Debits: ${settlement_ledger.sum_all_debits():,.2f}")
    print(f"Ledger Balanced: {'✅ YES' if abs(settlement_ledger.sum_all_credits() - settlement_ledger.sum_all_debits()) < 0.01 else '❌ NO'}")
    
    print("\nSettlements:")
    for settlement in settlement_ledger.settlements:
        if isinstance(settlement, Settlement):
            print(f"  - {settlement.id}: {settlement.status.value} ({settlement.duration_seconds():.3f}s)")
    
    print("\nFinal Balances:")
    print(f"  Supplier (SUP-001): ${balance_service.get_balance('SUP-001'):,.2f}")
    print(f"  Buyer (BUY-001): ${balance_service.get_balance('BUY-001'):,.2f}")
    print(f"  Capital (CAP-001): ${balance_service.get_balance('CAP-001'):,.2f}")
    
    print("\n" + "="*80)
    print("DEMONSTRATION COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    demonstrate_settlement()
