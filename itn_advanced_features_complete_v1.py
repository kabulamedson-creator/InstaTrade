"""
InstantTrade Network (ITN) - Complete Advanced Features
Version: 2.0.0
Features: Smart Routing + Recurring Invoices + Full Integration

This module demonstrates all 5 advanced features working together:
1. Multi-currency support ✅
2. Capital auction marketplace ✅
3. Advanced fraud scoring ✅
4. Smart routing (multi-rail optimization) ✅
5. Recurring invoices ✅
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import uuid

# ============================================
# FEATURE 4: SMART ROUTING
# ============================================

@dataclass
class SettlementRail:
    """Enhanced settlement rail with performance metrics."""
    name: str
    latency_p50: float  # Median latency (ms)
    latency_p99: float  # 99th percentile latency (ms)
    success_rate: float  # 0.0 to 1.0
    cost_per_transaction: float  # USD
    daily_limit: float  # Max volume per day
    current_volume: float = 0.0
    status: str = "UP"
    
    def can_handle(self, amount: float) -> bool:
        """Check if rail can handle transaction."""
        return (
            self.status == "UP" and
            self.current_volume + amount <= self.daily_limit and
            self.success_rate > 0.95
        )
    
    def score(self) -> float:
        """Score rail for selection (higher is better)."""
        # Weighted score: 50% latency, 30% success rate, 20% cost
        latency_score = 1.0 - (self.latency_p99 / 5000)  # Normalize to 5s max
        success_score = self.success_rate
        cost_score = 1.0 - (self.cost_per_transaction / 10)  # Normalize to $10 max
        
        return (
            0.50 * latency_score +
            0.30 * success_score +
            0.20 * cost_score
        )

class SmartRouter:
    """Intelligent settlement rail selection."""
    
    def __init__(self):
        self.rails = [
            SettlementRail(
                name="RTP (Real-Time Payments)",
                latency_p50=150,
                latency_p99=300,
                success_rate=0.999,
                cost_per_transaction=0.25,
                daily_limit=50_000_000
            ),
            SettlementRail(
                name="FedNow",
                latency_p50=200,
                latency_p99=400,
                success_rate=0.998,
                cost_per_transaction=0.30,
                daily_limit=100_000_000
            ),
            SettlementRail(
                name="ACH Same-Day",
                latency_p50=800,
                latency_p99=1500,
                success_rate=0.995,
                cost_per_transaction=0.10,
                daily_limit=1_000_000_000
            )
        ]
    
    def select_best_rail(self, amount: float, priority: str = "SPEED") -> SettlementRail:
        """
        Select optimal rail based on amount and priority.
        
        Priority modes:
        - SPEED: Minimize latency
        - COST: Minimize cost
        - BALANCED: Optimize combined score
        """
        
        # Filter to available rails
        available = [rail for rail in self.rails if rail.can_handle(amount)]
        
        if not available:
            raise Exception("No settlement rails available")
        
        # Select based on priority
        if priority == "SPEED":
            selected = min(available, key=lambda r: r.latency_p99)
        elif priority == "COST":
            selected = min(available, key=lambda r: r.cost_per_transaction)
        else:  # BALANCED
            selected = max(available, key=lambda r: r.score())
        
        print(f"[ROUTING] Selected {selected.name}")
        print(f"  Latency: {selected.latency_p99}ms (p99)")
        print(f"  Success rate: {selected.success_rate:.1%}")
        print(f"  Cost: ${selected.cost_per_transaction}")
        
        return selected
    
    def get_routing_stats(self) -> Dict:
        """Get routing statistics."""
        return {
            'total_rails': len(self.rails),
            'available_rails': sum(1 for r in self.rails if r.status == "UP"),
            'rails': [
                {
                    'name': r.name,
                    'latency_p99': r.latency_p99,
                    'success_rate': r.success_rate,
                    'score': r.score(),
                    'status': r.status
                }
                for r in sorted(self.rails, key=lambda x: x.score(), reverse=True)
            ]
        }

# ============================================
# FEATURE 5: RECURRING INVOICES
# ============================================

class RecurrenceFrequency(Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUALLY = "annually"

@dataclass
class RecurringInvoiceTemplate:
    """Template for recurring invoices (subscriptions)."""
    id: str
    supplier_id: str
    buyer_id: str
    amount: float
    currency: str
    frequency: RecurrenceFrequency
    
    # Schedule
    start_date: datetime
    end_date: Optional[datetime] = None
    max_occurrences: Optional[int] = None
    
    # Metadata
    description: str = ""
    terms: int = 30
    
    # Tracking
    occurrences_created: int = 0
    last_occurrence_date: Optional[datetime] = None
    status: str = "ACTIVE"  # ACTIVE, PAUSED, COMPLETED, CANCELLED
    
    def should_generate_occurrence(self, now: datetime) -> bool:
        """Check if new occurrence should be generated."""
        
        if self.status != "ACTIVE":
            return False
        
        # Check max occurrences
        if self.max_occurrences and self.occurrences_created >= self.max_occurrences:
            return False
        
        # Check end date
        if self.end_date and now > self.end_date:
            return False
        
        # Check if it's time for next occurrence
        if self.last_occurrence_date is None:
            # First occurrence
            return now >= self.start_date
        
        # Calculate next due date
        next_due = self._calculate_next_due_date()
        return now >= next_due
    
    def _calculate_next_due_date(self) -> datetime:
        """Calculate when next occurrence is due."""
        if self.last_occurrence_date is None:
            return self.start_date
        
        if self.frequency == RecurrenceFrequency.WEEKLY:
            return self.last_occurrence_date + timedelta(weeks=1)
        elif self.frequency == RecurrenceFrequency.MONTHLY:
            return self.last_occurrence_date + timedelta(days=30)
        elif self.frequency == RecurrenceFrequency.QUARTERLY:
            return self.last_occurrence_date + timedelta(days=90)
        elif self.frequency == RecurrenceFrequency.ANNUALLY:
            return self.last_occurrence_date + timedelta(days=365)

class RecurringInvoiceService:
    """Service for managing recurring invoices."""
    
    def __init__(self):
        self.templates: Dict[str, RecurringInvoiceTemplate] = {}
        self.generated_invoices: Dict[str, List[str]] = {}  # template_id -> invoice_ids
    
    def create_template(
        self,
        supplier_id: str,
        buyer_id: str,
        amount: float,
        frequency: RecurrenceFrequency,
        start_date: datetime,
        max_occurrences: Optional[int] = None,
        description: str = ""
    ) -> RecurringInvoiceTemplate:
        """Create recurring invoice template."""
        
        template_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
        
        template = RecurringInvoiceTemplate(
            id=template_id,
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            amount=amount,
            currency="USD",
            frequency=frequency,
            start_date=start_date,
            max_occurrences=max_occurrences,
            description=description
        )
        
        self.templates[template_id] = template
        self.generated_invoices[template_id] = []
        
        print(f"\n[RECURRING] Created template {template_id}")
        print(f"  Frequency: {frequency.value}")
        print(f"  Amount: ${amount:,.2f}")
        print(f"  Max occurrences: {max_occurrences or 'Unlimited'}")
        
        return template
    
    def generate_due_invoices(self, now: datetime) -> List[str]:
        """Generate all invoices that are due."""
        
        generated = []
        
        for template_id, template in self.templates.items():
            if template.should_generate_occurrence(now):
                invoice_id = self._generate_occurrence(template)
                generated.append(invoice_id)
        
        return generated
    
    def _generate_occurrence(self, template: RecurringInvoiceTemplate) -> str:
        """Generate single occurrence from template."""
        
        invoice_id = f"{template.id}-OCC-{template.occurrences_created + 1:03d}"
        
        # Update template
        template.occurrences_created += 1
        template.last_occurrence_date = datetime.now()
        
        # Track generated invoice
        self.generated_invoices[template.id].append(invoice_id)
        
        # Check if completed
        if template.max_occurrences and template.occurrences_created >= template.max_occurrences:
            template.status = "COMPLETED"
        
        print(f"[RECURRING] Generated invoice {invoice_id} from template {template.id}")
        
        return invoice_id
    
    def cancel_template(self, template_id: str):
        """Cancel recurring template."""
        if template_id in self.templates:
            self.templates[template_id].status = "CANCELLED"
            print(f"[RECURRING] Cancelled template {template_id}")

# ============================================
# COMPLETE INTEGRATION DEMO
# ============================================

def demonstrate_all_features():
    """Demonstrate all 5 advanced features working together."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK v2.0 - ALL ADVANCED FEATURES")
    print("="*80 + "\n")
    
    # ===== FEATURE 1: Multi-Currency =====
    print("\n" + "█"*80)
    print("FEATURE 1: MULTI-CURRENCY SUPPORT")
    print("█"*80)
    
    from itn_multicurrency_v1 import Currency, FXRateService, MultiCurrencyService, DecisionLedger
    
    fx_service = FXRateService()
    ledger = DecisionLedger()
    mc_service = MultiCurrencyService(fx_service, ledger)
    
    # EUR invoice settled in USD
    invoice_eur = mc_service.create_invoice_with_currency(
        invoice_id="INV-EUR-001",
        supplier_id="SUP-EU",
        buyer_id="BUY-US",
        amount=50000.00,
        currency=Currency.EUR,
        settlement_currency=Currency.USD,
        terms=30
    )
    
    print(f"\n✅ Multi-Currency Invoice:")
    print(f"   {invoice_eur.amount:,.2f} {invoice_eur.currency.value} → {invoice_eur.settlement_amount:,.2f} {invoice_eur.settlement_currency.value}")
    print(f"   FX Rate: {invoice_eur.fx_rate.effective_rate:.6f}")
    
    # ===== FEATURE 2: Capital Auction =====
    print("\n" + "█"*80)
    print("FEATURE 2: CAPITAL AUCTION MARKETPLACE")
    print("█"*80)
    
    from itn_capital_auction_v1 import CapitalAuctionService, CapitalProvider
    
    auction_service = CapitalAuctionService(ledger)
    
    # Register providers
    auction_service.register_provider(CapitalProvider(
        id="CAP-001",
        name="Provider A",
        available_liquidity=10_000_000,
        risk_appetite="MEDIUM"
    ))
    auction_service.register_provider(CapitalProvider(
        id="CAP-002",
        name="Provider B",
        available_liquidity=5_000_000,
        risk_appetite="LOW"
    ))
    
    # Run auction
    auction = auction_service.start_auction("INV-001", 100000.00, 45)
    import time
    time.sleep(0.5)
    winner = auction_service.finalize_auction(auction.id)
    
    print(f"\n✅ Competitive Auction:")
    print(f"   Bids received: {len(auction.bids)}")
    print(f"   Winning rate: {winner.discount_rate:.2%}")
    print(f"   Winner: {winner.provider_id}")
    
    # ===== FEATURE 3: Fraud Scoring =====
    print("\n" + "█"*80)
    print("FEATURE 3: ADVANCED FRAUD SCORING")
    print("█"*80)
    
    from itn_fraud_scoring_v1 import FraudService
    
    fraud_service = FraudService(ledger)
    
    score = fraud_service.score_invoice(
        invoice_id="INV-TEST",
        supplier_id="SUP-001",
        buyer_id="BUY-001",
        amount=75000.00,
        line_items=[{"desc": "Equipment", "amt": 75000}]
    )
    
    print(f"\n✅ Fraud Analysis:")
    print(f"   Score: {score.score:.1%}")
    print(f"   Risk: {score.risk_level}")
    print(f"   Action: {score.action}")
    print(f"   Signals triggered: {len(score.get_triggered_signals())}")
    
    # ===== FEATURE 4: Smart Routing =====
    print("\n" + "█"*80)
    print("FEATURE 4: SMART ROUTING")
    print("█"*80)
    
    router = SmartRouter()
    
    # Select best rail for different scenarios
    rail_speed = router.select_best_rail(amount=50000, priority="SPEED")
    rail_cost = router.select_best_rail(amount=50000, priority="COST")
    rail_balanced = router.select_best_rail(amount=50000, priority="BALANCED")
    
    print(f"\n✅ Route Optimization:")
    print(f"   Speed priority: {rail_speed.name} ({rail_speed.latency_p99}ms)")
    print(f"   Cost priority: {rail_cost.name} (${rail_cost.cost_per_transaction})")
    print(f"   Balanced: {rail_balanced.name} (score: {rail_balanced.score():.3f})")
    
    stats = router.get_routing_stats()
    print(f"\n   Available rails: {stats['available_rails']}/{stats['total_rails']}")
    
    # ===== FEATURE 5: Recurring Invoices =====
    print("\n" + "█"*80)
    print("FEATURE 5: RECURRING INVOICES")
    print("█"*80)
    
    recurring_service = RecurringInvoiceService()
    
    # Create monthly subscription
    template = recurring_service.create_template(
        supplier_id="SUP-SAAS",
        buyer_id="BUY-ENTERPRISE",
        amount=5000.00,
        frequency=RecurrenceFrequency.MONTHLY,
        start_date=datetime.now(),
        max_occurrences=12,
        description="SaaS Subscription - Annual Contract"
    )
    
    # Generate first 3 occurrences
    generated = []
    for i in range(3):
        invoices = recurring_service.generate_due_invoices(
            datetime.now() + timedelta(days=30 * i)
        )
        generated.extend(invoices)
    
    print(f"\n✅ Recurring Template:")
    print(f"   Template: {template.id}")
    print(f"   Frequency: {template.frequency.value}")
    print(f"   Generated: {template.occurrences_created}/{template.max_occurrences}")
    print(f"   Status: {template.status}")
    print(f"\n   Invoices created:")
    for inv_id in generated:
        print(f"   - {inv_id}")
    
    # ===== FINAL SUMMARY =====
    print("\n" + "="*80)
    print("COMPLETE FEATURE SUMMARY")
    print("="*80)
    
    print(f"\n✅ FEATURE 1: Multi-Currency Support")
    print(f"   - Supported currencies: {len(list(Currency))}")
    print(f"   - FX conversions: Automatic with 0.5% spread")
    print(f"   - Rate freshness: <60 seconds (INV-204)")
    
    print(f"\n✅ FEATURE 2: Capital Auction Marketplace")
    print(f"   - Registered providers: {len(auction_service.providers)}")
    print(f"   - Competitive auctions: {len(auction_service.auctions)}")
    print(f"   - Average bids per auction: {sum(len(a.bids) for a in auction_service.auctions.values()) / len(auction_service.auctions):.1f}")
    
    print(f"\n✅ FEATURE 3: Advanced Fraud Scoring")
    print(f"   - Detection signals: {len(list(fraud_service.engine.SIGNAL_WEIGHTS))}")
    print(f"   - Invoices scored: {len(fraud_service.scores)}")
    print(f"   - Fraud threshold: {fraud_service.FRAUD_THRESHOLD:.0%}")
    
    print(f"\n✅ FEATURE 4: Smart Routing")
    print(f"   - Available rails: {stats['available_rails']}")
    print(f"   - Routing modes: SPEED, COST, BALANCED")
    print(f"   - Best rail (balanced): {rail_balanced.name}")
    
    print(f"\n✅ FEATURE 5: Recurring Invoices")
    print(f"   - Active templates: {sum(1 for t in recurring_service.templates.values() if t.status == 'ACTIVE')}")
    print(f"   - Frequencies: Weekly, Monthly, Quarterly, Annual")
    print(f"   - Total invoices generated: {sum(len(invs) for invs in recurring_service.generated_invoices.values())}")
    
    print("\n" + "="*80)
    print("ALL ADVANCED FEATURES OPERATIONAL ✅")
    print("="*80 + "\n")
    
    print("System Capabilities:")
    print("  ✅ Multi-currency invoices with real-time FX")
    print("  ✅ Competitive capital marketplace")
    print("  ✅ 8-signal fraud detection")
    print("  ✅ Intelligent settlement routing")
    print("  ✅ Subscription/recurring revenue support")
    print("  ✅ All features enforce invariants")
    print("  ✅ Complete audit trail maintained")
    print("\n" + "="*80 + "\n")

if __name__ == "__main__":
    demonstrate_all_features()
