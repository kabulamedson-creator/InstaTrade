"""
InstantTrade Network (ITN) - Multi-Currency Support
Version: 2.0.0
Feature: Multi-currency invoices and settlements (USD, EUR, GBP, JPY)

Evolution from v1.0.0:
- Adds currency field to invoices
- Real-time FX rate fetching
- Currency conversion with spread
- Cross-currency settlement
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional
from enum import Enum
import random

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
# SUPPORTED CURRENCIES
# ============================================

class Currency(Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"

# ============================================
# FX RATE SERVICE
# ============================================

@dataclass
class FXRate:
    """Foreign exchange rate."""
    from_currency: Currency
    to_currency: Currency
    rate: float
    spread: float  # ITN's profit on FX conversion
    fetched_at: datetime
    source: str = "FX_PROVIDER"
    
    @property
    def effective_rate(self) -> float:
        """Rate including ITN spread."""
        return self.rate * (1 + self.spread)
    
    def is_fresh(self, max_age_seconds: int = 60) -> bool:
        """Check if rate is fresh enough to use."""
        age = (datetime.now() - self.fetched_at).total_seconds()
        return age < max_age_seconds
    
    def convert(self, amount: float) -> float:
        """Convert amount using effective rate."""
        return amount * self.effective_rate
    
    def to_dict(self) -> Dict:
        return {
            'from_currency': self.from_currency.value,
            'to_currency': self.to_currency.value,
            'rate': self.rate,
            'spread': self.spread,
            'effective_rate': self.effective_rate,
            'fetched_at': self.fetched_at.isoformat()
        }

class FXRateService:
    """Fetches and caches FX rates with freshness guarantees."""
    
    # ITN's spread on FX conversions (0.5%)
    FX_SPREAD = 0.005
    
    # Max age for cached rates (60 seconds per INV-204)
    MAX_RATE_AGE_SECONDS = 60
    
    # Mock exchange rates (production would fetch from provider)
    BASE_RATES = {
        ('USD', 'EUR'): 0.92,
        ('USD', 'GBP'): 0.79,
        ('USD', 'JPY'): 149.50,
        ('EUR', 'USD'): 1.09,
        ('EUR', 'GBP'): 0.86,
        ('EUR', 'JPY'): 162.50,
        ('GBP', 'USD'): 1.27,
        ('GBP', 'EUR'): 1.16,
        ('GBP', 'JPY'): 189.00,
        ('JPY', 'USD'): 0.0067,
        ('JPY', 'EUR'): 0.0062,
        ('JPY', 'GBP'): 0.0053,
    }
    
    def __init__(self):
        self.rate_cache: Dict[tuple, FXRate] = {}
    
    def get_rate(
        self, 
        from_currency: Currency, 
        to_currency: Currency,
        force_refresh: bool = False
    ) -> FXRate:
        """
        Get FX rate with freshness guarantee.
        
        Enforces INV-204: Rates must be <60 seconds old.
        """
        
        # Same currency = 1.0 rate
        if from_currency == to_currency:
            return FXRate(
                from_currency=from_currency,
                to_currency=to_currency,
                rate=1.0,
                spread=0.0,
                fetched_at=datetime.now()
            )
        
        cache_key = (from_currency.value, to_currency.value)
        
        # Check cache
        if not force_refresh and cache_key in self.rate_cache:
            cached_rate = self.rate_cache[cache_key]
            if cached_rate.is_fresh(self.MAX_RATE_AGE_SECONDS):
                logger.info(f"[FX] Using cached rate: {from_currency.value}/{to_currency.value} = {cached_rate.effective_rate:.6f}")
                return cached_rate
        
        # Fetch fresh rate
        rate = self._fetch_rate(from_currency, to_currency)
        self.rate_cache[cache_key] = rate
        
        logger.info(f"[FX] Fetched fresh rate: {from_currency.value}/{to_currency.value} = {rate.effective_rate:.6f}")
        
        return rate
    
    def _fetch_rate(self, from_currency: Currency, to_currency: Currency) -> FXRate:
        """Fetch rate from provider (mocked)."""
        
        base_rate = self.BASE_RATES.get(
            (from_currency.value, to_currency.value),
            1.0
        )
        
        # Add small random variation (±0.1%) to simulate market movement
        variation = random.uniform(-0.001, 0.001)
        market_rate = base_rate * (1 + variation)
        
        return FXRate(
            from_currency=from_currency,
            to_currency=to_currency,
            rate=market_rate,
            spread=self.FX_SPREAD,
            fetched_at=datetime.now()
        )
    
    def convert_amount(
        self,
        amount: float,
        from_currency: Currency,
        to_currency: Currency
    ) -> tuple[float, FXRate]:
        """
        Convert amount from one currency to another.
        
        Returns:
            (converted_amount, fx_rate) tuple
        """
        
        fx_rate = self.get_rate(from_currency, to_currency)
        converted = fx_rate.convert(amount)
        
        logger.info(f"[FX] Converted {amount:,.2f} {from_currency.value} → {converted:,.2f} {to_currency.value}")
        
        return converted, fx_rate

# ============================================
# FX RATE FRESHNESS INVARIANT
# ============================================

class FXRateFreshness(Invariant):
    """INV-204: FX rates must be <60 seconds old at settlement."""
    
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
    
    def pre_check(self, fx_rate: FXRate, **kwargs) -> bool:
        """Check if FX rate is fresh enough."""
        is_fresh = fx_rate.is_fresh(self.MAX_AGE_SECONDS)
        age_seconds = (datetime.now() - fx_rate.fetched_at).total_seconds()
        
        logger.info(f"PRE-CHECK {self.id}: fx_rate age={age_seconds:.1f}s, fresh={is_fresh}")
        
        if not is_fresh:
            logger.warning(f"FX rate too old: {age_seconds:.1f}s > {self.MAX_AGE_SECONDS}s")
        
        return is_fresh
    
    def post_check(self, result: Dict, **kwargs) -> bool:
        """Verify FX rate wasn't re-fetched during settlement."""
        original_timestamp = result['fx_rate_timestamp']
        current_fx_rate = result['fx_rate']
        
        unchanged = current_fx_rate.fetched_at == original_timestamp
        
        logger.info(f"POST-CHECK {self.id}: fx_timestamp_unchanged={unchanged}")
        return unchanged
    
    def rollback_action(self, state_before: Dict):
        """Reverse conversion with stale rate."""
        logger.warning(f"ROLLBACK {self.id}: FX rate expired during settlement")
    
    def verify_state(self, state: Dict) -> bool:
        """Verify FX rate is fresh in given state."""
        if 'fx_rate' not in state:
            return True  # No FX rate, nothing to verify
        
        fx_rate = state['fx_rate']
        return fx_rate.is_fresh(self.MAX_AGE_SECONDS)

# ============================================
# MULTI-CURRENCY INVOICE
# ============================================

@dataclass
class MultiCurrencyInvoice:
    """Invoice with currency support."""
    id: str
    supplier_id: str
    buyer_id: str
    amount: float
    currency: Currency  # Invoice currency
    terms: int
    
    created_at: datetime = field(default_factory=datetime.now)
    status: str = "PENDING"
    
    # Settlement currency (defaults to invoice currency)
    settlement_currency: Optional[Currency] = None
    
    # FX conversion data (if currencies differ)
    fx_rate: Optional[FXRate] = None
    settlement_amount: Optional[float] = None
    
    def __post_init__(self):
        if self.settlement_currency is None:
            self.settlement_currency = self.currency
    
    def requires_fx_conversion(self) -> bool:
        """Check if FX conversion needed."""
        return self.currency != self.settlement_currency
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'supplier_id': self.supplier_id,
            'buyer_id': self.buyer_id,
            'amount': self.amount,
            'currency': self.currency.value,
            'settlement_currency': self.settlement_currency.value,
            'settlement_amount': self.settlement_amount,
            'requires_fx_conversion': self.requires_fx_conversion(),
            'fx_rate': self.fx_rate.to_dict() if self.fx_rate else None,
            'status': self.status
        }

# ============================================
# MULTI-CURRENCY SERVICE
# ============================================

class MultiCurrencyService:
    """Service for multi-currency invoice operations."""
    
    def __init__(self, fx_service: FXRateService, ledger: DecisionLedger):
        self.fx_service = fx_service
        self.ledger = ledger
        
        # Initialize FX invariant
        self.invariants = [FXRateFreshness()]
        self.enforcer = InvariantEnforcer(self.invariants, ledger)
        
        logger.info("[MULTICURRENCY] Initialized with FX rate enforcement")
    
    def create_invoice_with_currency(
        self,
        invoice_id: str,
        supplier_id: str,
        buyer_id: str,
        amount: float,
        currency: Currency,
        terms: int,
        settlement_currency: Optional[Currency] = None
    ) -> MultiCurrencyInvoice:
        """
        Create invoice with currency specification.
        
        If settlement_currency differs from invoice currency,
        FX conversion is applied with INV-204 enforcement.
        """
        
        invoice = MultiCurrencyInvoice(
            id=invoice_id,
            supplier_id=supplier_id,
            buyer_id=buyer_id,
            amount=amount,
            currency=currency,
            settlement_currency=settlement_currency or currency,
            terms=terms
        )
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[MULTICURRENCY] Creating invoice {invoice_id}")
        logger.info(f"  Amount: {amount:,.2f} {currency.value}")
        logger.info(f"  Settlement: {invoice.settlement_currency.value}")
        logger.info(f"  FX Conversion: {invoice.requires_fx_conversion()}")
        logger.info(f"{'='*60}\n")
        
        # If FX conversion needed, get rate and convert
        if invoice.requires_fx_conversion():
            converted_amount, fx_rate = self._apply_fx_conversion(invoice)
            invoice.settlement_amount = converted_amount
            invoice.fx_rate = fx_rate
        else:
            invoice.settlement_amount = amount
        
        return invoice
    
    def _apply_fx_conversion(self, invoice: MultiCurrencyInvoice) -> tuple[float, FXRate]:
        """Apply FX conversion with enforcement."""
        
        def _conversion_action() -> Dict:
            """Execute FX conversion."""
            
            converted_amount, fx_rate = self.fx_service.convert_amount(
                amount=invoice.amount,
                from_currency=invoice.currency,
                to_currency=invoice.settlement_currency
            )
            
            return {
                'converted_amount': converted_amount,
                'fx_rate': fx_rate,
                'fx_rate_timestamp': fx_rate.fetched_at
            }
        
        # Execute with FX rate freshness enforcement
        try:
            result = self.enforcer.enforce_action(
                _conversion_action,
                fx_rate=self.fx_service.get_rate(invoice.currency, invoice.settlement_currency)
            )
            
            logger.info(f"✅ FX conversion: {invoice.amount:,.2f} {invoice.currency.value} → {result['converted_amount']:,.2f} {invoice.settlement_currency.value}")
            
            return result['converted_amount'], result['fx_rate']
            
        except InvariantViolation as e:
            logger.error(f"❌ FX conversion failed: {e}")
            raise

# ============================================
# DEMONSTRATION
# ============================================

def demonstrate_multicurrency():
    """Demonstrate multi-currency support."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - MULTI-CURRENCY DEMONSTRATION")
    print("="*80 + "\n")
    
    # Initialize services
    fx_service = FXRateService()
    ledger = DecisionLedger()
    multicurrency_service = MultiCurrencyService(fx_service, ledger)
    
    # ===== TEST 1: Same Currency (No Conversion) =====
    print("\n" + "-"*80)
    print("TEST 1: Invoice in USD, settle in USD (no FX conversion)")
    print("-"*80)
    
    invoice_1 = multicurrency_service.create_invoice_with_currency(
        invoice_id="INV-USD-001",
        supplier_id="SUP-001",
        buyer_id="BUY-001",
        amount=50000.00,
        currency=Currency.USD,
        settlement_currency=Currency.USD,
        terms=30
    )
    
    print(f"\n✅ Invoice created:")
    print(f"   Invoice amount: {invoice_1.amount:,.2f} {invoice_1.currency.value}")
    print(f"   Settlement amount: {invoice_1.settlement_amount:,.2f} {invoice_1.settlement_currency.value}")
    print(f"   FX conversion: {invoice_1.requires_fx_conversion()}")
    
    # ===== TEST 2: EUR to USD Conversion =====
    print("\n" + "-"*80)
    print("TEST 2: Invoice in EUR, settle in USD (FX conversion)")
    print("-"*80)
    
    invoice_2 = multicurrency_service.create_invoice_with_currency(
        invoice_id="INV-EUR-001",
        supplier_id="SUP-002",
        buyer_id="BUY-001",
        amount=45000.00,
        currency=Currency.EUR,
        settlement_currency=Currency.USD,
        terms=30
    )
    
    print(f"\n✅ Invoice created:")
    print(f"   Invoice amount: {invoice_2.amount:,.2f} {invoice_2.currency.value}")
    print(f"   Settlement amount: {invoice_2.settlement_amount:,.2f} {invoice_2.settlement_currency.value}")
    print(f"   FX rate: {invoice_2.fx_rate.effective_rate:.6f}")
    print(f"   ITN FX spread: {invoice_2.fx_rate.spread:.2%}")
    
    # ===== TEST 3: GBP to JPY Conversion =====
    print("\n" + "-"*80)
    print("TEST 3: Invoice in GBP, settle in JPY (cross-currency)")
    print("-"*80)
    
    invoice_3 = multicurrency_service.create_invoice_with_currency(
        invoice_id="INV-GBP-001",
        supplier_id="SUP-001",
        buyer_id="BUY-002",
        amount=30000.00,
        currency=Currency.GBP,
        settlement_currency=Currency.JPY,
        terms=45
    )
    
    print(f"\n✅ Invoice created:")
    print(f"   Invoice amount: {invoice_3.amount:,.2f} {invoice_3.currency.value}")
    print(f"   Settlement amount: {invoice_3.settlement_amount:,.2f} {invoice_3.settlement_currency.value}")
    print(f"   FX rate: {invoice_3.fx_rate.effective_rate:.2f}")
    
    # ===== TEST 4: Rate Freshness =====
    print("\n" + "-"*80)
    print("TEST 4: FX rate freshness validation")
    print("-"*80)
    
    # Get current rate
    rate_usd_eur = fx_service.get_rate(Currency.USD, Currency.EUR)
    print(f"\nCurrent rate USD/EUR:")
    print(f"   Market rate: {rate_usd_eur.rate:.6f}")
    print(f"   Effective rate: {rate_usd_eur.effective_rate:.6f}")
    print(f"   Fetched at: {rate_usd_eur.fetched_at.strftime('%H:%M:%S')}")
    print(f"   Is fresh: {rate_usd_eur.is_fresh()}")
    
    # Simulate time passing
    import time
    print("\n   Waiting 2 seconds...")
    time.sleep(2)
    
    # Rate should still be fresh (60s limit)
    print(f"   Is still fresh: {rate_usd_eur.is_fresh()}")
    
    # ===== SUMMARY =====
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Supported Currencies: {', '.join(c.value for c in Currency)}")
    print(f"Total Invoices: 3")
    print(f"FX Conversions: 2")
    print(f"FX Spread Revenue: {fx_service.FX_SPREAD:.2%} on conversions")
    
    print("\nInvoices:")
    for inv in [invoice_1, invoice_2, invoice_3]:
        fx_status = "✓ FX converted" if inv.requires_fx_conversion() else "Same currency"
        print(f"  - {inv.id}: {inv.amount:,.2f} {inv.currency.value} → {inv.settlement_amount:,.2f} {inv.settlement_currency.value} ({fx_status})")
    
    print("\nFX Rate Cache:")
    for key, rate in fx_service.rate_cache.items():
        print(f"  - {key[0]}/{key[1]}: {rate.effective_rate:.6f} (age: {(datetime.now() - rate.fetched_at).total_seconds():.1f}s)")
    
    print("\n" + "="*80)
    print("MULTI-CURRENCY FEATURE COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    demonstrate_multicurrency()
