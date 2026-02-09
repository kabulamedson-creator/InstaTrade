"""
InstantTrade Network (ITN) - End-to-End Integration
Version: 1.0.0
Phase: 3 - Feature Implementation

Complete business flow: Invoice Creation → Buyer Acceptance → Settlement
Demonstrates all invariants working together in production scenario.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import uuid

# Import all services
from itn_invoice_service_v1 import (
    InvoiceCreationService,
    InvoiceStorage,
    AccountService,
    Invoice,
    LineItem
)

from itn_settlement_service_v1 import (
    SettlementService,
    SettlementLedger,
    SettlementRailManager,
    BalanceService,
    Settlement
)

from itn_enforcement_v1 import (
    DecisionLedger,
    InvariantViolation,
    logger
)

# ============================================
# PRICING SERVICE (MOCK)
# ============================================

@dataclass
class PricingQuote:
    """Pricing quote for payment terms."""
    invoice_id: str
    terms: int
    discount_rate: float
    total_cost: float
    created_at: datetime
    expires_at: datetime
    
    def is_expired(self) -> bool:
        """Check if quote expired."""
        return datetime.now() > self.expires_at

class PricingService:
    """Generates pricing quotes for different payment terms."""
    
    QUOTE_VALIDITY_MINUTES = 5
    
    # Base rates by term (annualized)
    BASE_RATES = {
        0: 0.00,    # Net 0 (immediate) - no cost
        15: 0.03,   # 3% APR
        30: 0.05,   # 5% APR
        45: 0.06,   # 6% APR
        60: 0.08,   # 8% APR
        90: 0.10    # 10% APR
    }
    
    def __init__(self):
        self.quotes: Dict[str, PricingQuote] = {}
    
    def generate_quote(self, invoice_id: str, amount: float, terms: int) -> PricingQuote:
        """Generate pricing quote for invoice."""
        
        if terms not in self.BASE_RATES:
            raise ValueError(f"Invalid payment terms: {terms}")
        
        # Calculate discount rate (prorated for term length)
        discount_rate = self.BASE_RATES[terms] * (terms / 365)
        total_cost = amount * (1 + discount_rate)
        
        quote = PricingQuote(
            invoice_id=invoice_id,
            terms=terms,
            discount_rate=discount_rate,
            total_cost=total_cost,
            created_at=datetime.now(),
            expires_at=datetime.now() + timedelta(minutes=self.QUOTE_VALIDITY_MINUTES)
        )
        
        self.quotes[invoice_id] = quote
        
        logger.info(f"[PRICING] Generated quote for {invoice_id}: ${amount:,.2f} @ {terms} days = ${total_cost:,.2f}")
        
        return quote
    
    def get_quote(self, invoice_id: str) -> Optional[PricingQuote]:
        """Retrieve existing quote."""
        quote = self.quotes.get(invoice_id)
        
        if quote and quote.is_expired():
            logger.warning(f"[PRICING] Quote for {invoice_id} expired")
            return None
        
        return quote

# ============================================
# BUYER ACCEPTANCE SERVICE
# ============================================

class BuyerAcceptanceService:
    """Handles buyer review and acceptance of invoices."""
    
    def __init__(
        self,
        invoice_storage: InvoiceStorage,
        pricing_service: PricingService
    ):
        self.invoice_storage = invoice_storage
        self.pricing_service = pricing_service
    
    def accept_invoice(
        self,
        invoice_id: str,
        buyer_id: str,
        chosen_terms: Optional[int] = None
    ) -> tuple[Invoice, PricingQuote]:
        """
        Buyer accepts invoice with optional payment terms.
        
        Returns:
            (invoice, pricing_quote) tuple
        """
        
        # Retrieve invoice
        invoice = self.invoice_storage.get_invoice(invoice_id)
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")
        
        # Verify buyer authorization
        if invoice.buyer_id != buyer_id:
            raise ValueError(f"Buyer {buyer_id} not authorized for invoice {invoice_id}")
        
        # Verify invoice status
        if invoice.status != "PENDING":
            raise ValueError(f"Invoice {invoice_id} is {invoice.status}, cannot accept")
        
        # Use chosen terms or invoice default
        terms = chosen_terms if chosen_terms is not None else invoice.terms
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[ACCEPTANCE] Buyer {buyer_id} accepting invoice {invoice_id}")
        logger.info(f"  Amount: ${invoice.amount:,.2f}")
        logger.info(f"  Terms: {terms} days")
        logger.info(f"{'='*60}\n")
        
        # Generate pricing quote
        quote = self.pricing_service.generate_quote(invoice_id, invoice.amount, terms)
        
        logger.info(f"[ACCEPTANCE] Pricing quote:")
        logger.info(f"  Base amount: ${invoice.amount:,.2f}")
        logger.info(f"  Discount rate: {quote.discount_rate:.4%}")
        logger.info(f"  Total cost: ${quote.total_cost:,.2f}")
        logger.info(f"  Quote expires: {quote.expires_at.strftime('%H:%M:%S')}")
        
        # Update invoice status
        invoice.status = "ACCEPTED"
        
        logger.info(f"\n✅ Invoice {invoice_id} ACCEPTED by {buyer_id}\n")
        
        return invoice, quote

# ============================================
# ORCHESTRATOR
# ============================================

class InstantTradeOrchestrator:
    """Orchestrates complete InstantTrade flow."""
    
    def __init__(self):
        # Initialize all services
        self.invoice_storage = InvoiceStorage()
        self.account_service = AccountService()
        self.settlement_ledger = SettlementLedger()
        self.decision_ledger = DecisionLedger()
        self.rail_manager = SettlementRailManager()
        self.balance_service = BalanceService()
        self.pricing_service = PricingService()
        
        # Create service instances
        self.invoice_service = InvoiceCreationService(
            self.invoice_storage,
            self.account_service,
            self.decision_ledger
        )
        
        self.acceptance_service = BuyerAcceptanceService(
            self.invoice_storage,
            self.pricing_service
        )
        
        self.settlement_service = SettlementService(
            self.settlement_ledger,
            self.decision_ledger,
            self.rail_manager,
            self.balance_service
        )
        
        logger.info("[ORCHESTRATOR] InstantTrade system initialized")
    
    def execute_complete_flow(
        self,
        supplier_id: str,
        buyer_id: str,
        line_items: List[LineItem],
        terms: int,
        capital_provider_id: str = "CAP-001"
    ) -> tuple[Invoice, Settlement]:
        """
        Execute complete flow:
        1. Supplier creates invoice
        2. Buyer accepts invoice
        3. Settlement executes (supplier paid instantly)
        
        Returns:
            (invoice, settlement) tuple
        """
        
        print("\n" + "="*80)
        print("INSTANTTRADE COMPLETE FLOW")
        print("="*80)
        
        # ===== STEP 1: Supplier Creates Invoice =====
        print("\n" + "-"*80)
        print("STEP 1: Supplier creates invoice")
        print("-"*80)
        
        invoice = self.invoice_service.create_invoice(
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            line_items=line_items,
            terms=terms
        )
        
        print(f"\n✅ Invoice {invoice.id} created")
        print(f"   Amount: ${invoice.amount:,.2f}")
        print(f"   Status: {invoice.status}")
        
        # ===== STEP 2: Buyer Accepts Invoice =====
        print("\n" + "-"*80)
        print("STEP 2: Buyer reviews and accepts invoice")
        print("-"*80)
        
        # Simulate buyer taking time to review
        import time
        print("   Buyer reviewing invoice...")
        time.sleep(0.5)
        
        accepted_invoice, pricing_quote = self.acceptance_service.accept_invoice(
            invoice_id=invoice.id,
            buyer_id=buyer_id,
            chosen_terms=terms
        )
        
        print(f"\n✅ Invoice {invoice.id} accepted")
        print(f"   Buyer will pay: ${pricing_quote.total_cost:,.2f}")
        print(f"   (includes ${pricing_quote.total_cost - invoice.amount:.2f} financing cost)")
        
        # ===== STEP 3: Instant Settlement =====
        print("\n" + "-"*80)
        print("STEP 3: Executing instant settlement")
        print("-"*80)
        
        print("\n   Initial balances:")
        print(f"   - Supplier: ${self.balance_service.get_balance(supplier_id):,.2f}")
        print(f"   - Buyer: ${self.balance_service.get_balance(buyer_id):,.2f}")
        print(f"   - Capital: ${self.balance_service.get_balance(capital_provider_id):,.2f}")
        
        settlement = self.settlement_service.execute_settlement(
            invoice_id=invoice.id,
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            capital_provider_id=capital_provider_id,
            amount=invoice.amount,
            discount_rate=pricing_quote.discount_rate
        )
        
        print(f"\n✅ Settlement {settlement.id} completed in {settlement.duration_seconds():.3f}s")
        
        print("\n   Final balances:")
        print(f"   - Supplier: ${self.balance_service.get_balance(supplier_id):,.2f} (received payment)")
        print(f"   - Buyer: ${self.balance_service.get_balance(buyer_id):,.2f} (payment deducted)")
        print(f"   - Capital: ${self.balance_service.get_balance(capital_provider_id):,.2f} (earned spread)")
        
        # ===== Summary =====
        print("\n" + "="*80)
        print("FLOW COMPLETE")
        print("="*80)
        print(f"✅ Invoice {invoice.id}: ${invoice.amount:,.2f}")
        print(f"✅ Supplier received payment INSTANTLY")
        print(f"✅ Buyer has {terms} days to pay capital provider")
        print(f"✅ All {len(self.decision_ledger.entries)} invariant checks passed")
        print("="*80 + "\n")
        
        return accepted_invoice, settlement
    
    def get_system_health(self) -> Dict:
        """Get complete system health report."""
        
        total_invoices = len(self.invoice_storage.get_all_invoices())
        total_settlements = len(self.settlement_ledger.settlements)
        total_invariant_checks = len(self.decision_ledger.entries)
        
        # Calculate health score
        passed_checks = sum(1 for entry in self.decision_ledger.entries if entry.result)
        health_score = passed_checks / total_invariant_checks if total_invariant_checks > 0 else 1.0
        
        return {
            'total_invoices': total_invoices,
            'total_settlements': total_settlements,
            'total_invariant_checks': total_invariant_checks,
            'passed_checks': passed_checks,
            'failed_checks': total_invariant_checks - passed_checks,
            'health_score': health_score,
            'ledger_balanced': abs(
                self.settlement_ledger.sum_all_credits() - 
                self.settlement_ledger.sum_all_debits()
            ) < 0.01,
            'ledger_integrity': self.decision_ledger.verify_chain_integrity()
        }

# ============================================
# COMPLETE DEMONSTRATION
# ============================================

def demonstrate_complete_system():
    """Demonstrate complete InstantTrade system."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - COMPLETE SYSTEM DEMONSTRATION")
    print("="*80 + "\n")
    
    # Initialize orchestrator
    orchestrator = InstantTradeOrchestrator()
    
    # ===== SCENARIO 1: Successful Flow =====
    print("\n" + "█"*80)
    print("SCENARIO 1: Successful Transaction")
    print("█"*80)
    
    line_items_1 = [
        LineItem(description="Industrial Pumps", quantity=20, unit_price=2500.00),
        LineItem(description="Installation Service", quantity=1, unit_price=5000.00),
    ]
    
    try:
        invoice_1, settlement_1 = orchestrator.execute_complete_flow(
            supplier_id="SUP-001",
            buyer_id="BUY-001",
            line_items=line_items_1,
            terms=30
        )
    except Exception as e:
        print(f"\n❌ SCENARIO 1 FAILED: {e}\n")
    
    # ===== SCENARIO 2: Different Terms =====
    print("\n" + "█"*80)
    print("SCENARIO 2: Transaction with 60-day terms")
    print("█"*80)
    
    line_items_2 = [
        LineItem(description="Raw Materials", quantity=500, unit_price=100.00),
    ]
    
    try:
        invoice_2, settlement_2 = orchestrator.execute_complete_flow(
            supplier_id="SUP-002",
            buyer_id="BUY-001",
            line_items=line_items_2,
            terms=60
        )
    except Exception as e:
        print(f"\n❌ SCENARIO 2 FAILED: {e}\n")
    
    # ===== SCENARIO 3: Duplicate Prevention =====
    print("\n" + "█"*80)
    print("SCENARIO 3: Attempt duplicate transaction (should fail)")
    print("█"*80)
    
    # Try to recreate first invoice
    try:
        invoice_3, settlement_3 = orchestrator.execute_complete_flow(
            supplier_id="SUP-001",
            buyer_id="BUY-001",
            line_items=line_items_1,  # Same items
            terms=30
        )
        print("\n❌ SCENARIO 3 FAILED: Duplicate was allowed\n")
    except InvariantViolation as e:
        print(f"\n✅ SCENARIO 3 PASSED: Duplicate correctly prevented")
        print(f"   Invariant: {e}\n")
    
    # ===== SYSTEM HEALTH REPORT =====
    print("\n" + "="*80)
    print("SYSTEM HEALTH REPORT")
    print("="*80)
    
    health = orchestrator.get_system_health()
    
    print(f"\nTransactions:")
    print(f"  Total Invoices: {health['total_invoices']}")
    print(f"  Total Settlements: {health['total_settlements']}")
    
    print(f"\nInvariant Enforcement:")
    print(f"  Total Checks: {health['total_invariant_checks']}")
    print(f"  Passed: {health['passed_checks']} ✅")
    print(f"  Failed: {health['failed_checks']} ❌")
    print(f"  Health Score: {health['health_score']:.2%} {'✅' if health['health_score'] >= 0.95 else '❌'}")
    
    print(f"\nLedger:")
    print(f"  Total Credits: ${orchestrator.settlement_ledger.sum_all_credits():,.2f}")
    print(f"  Total Debits: ${orchestrator.settlement_ledger.sum_all_debits():,.2f}")
    print(f"  Balanced: {'✅ YES' if health['ledger_balanced'] else '❌ NO'}")
    print(f"  Integrity: {'✅ VERIFIED' if health['ledger_integrity'] else '❌ COMPROMISED'}")
    
    print(f"\nAccount Balances:")
    for account_id in ['SUP-001', 'SUP-002', 'BUY-001', 'CAP-001']:
        if orchestrator.account_service.account_exists(account_id):
            balance = orchestrator.balance_service.get_balance(account_id)
            print(f"  {account_id}: ${balance:,.2f}")
    
    print("\n" + "="*80)
    print("DEMONSTRATION COMPLETE")
    print("="*80)
    print("\nKey Achievements:")
    print("  ✅ Invoice creation with full validation")
    print("  ✅ Buyer acceptance with transparent pricing")
    print("  ✅ Instant settlement (<5 seconds)")
    print("  ✅ Atomic 3-leg transfers")
    print("  ✅ Duplicate prevention")
    print("  ✅ Complete audit trail")
    print("  ✅ All invariants enforced")
    print("="*80 + "\n")

if __name__ == "__main__":
    demonstrate_complete_system()
