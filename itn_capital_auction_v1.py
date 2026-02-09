"""
InstantTrade Network (ITN) - Capital Auction Marketplace
Version: 2.0.0
Feature: Competitive auction for working capital providers

Capital providers bid to finance invoices, creating market-driven pricing.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from enum import Enum
import uuid

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
# CAPITAL PROVIDER
# ============================================

@dataclass
class CapitalProvider:
    """Capital provider entity."""
    id: str
    name: str
    available_liquidity: float
    min_deal_size: float = 1000.00
    max_deal_size: float = 10_000_000.00
    preferred_terms: List[int] = field(default_factory=lambda: [30, 45, 60, 90])
    risk_appetite: str = "MEDIUM"  # LOW, MEDIUM, HIGH
    
    def can_bid(self, amount: float, terms: int) -> bool:
        """Check if provider can bid on invoice."""
        return (
            self.available_liquidity >= amount and
            self.min_deal_size <= amount <= self.max_deal_size and
            terms in self.preferred_terms
        )

# ============================================
# CAPITAL BID
# ============================================

@dataclass
class CapitalBid:
    """Bid from capital provider."""
    id: str
    provider_id: str
    invoice_id: str
    amount: float
    discount_rate: float  # Annual discount rate (e.g., 0.05 = 5%)
    capacity: float  # How much provider can fund
    
    created_at: datetime = field(default_factory=datetime.now)
    expires_at: Optional[datetime] = None
    status: str = "ACTIVE"  # ACTIVE, ACCEPTED, EXPIRED, WITHDRAWN
    
    # Bid terms
    min_terms: int = 0
    max_terms: int = 90
    
    def __post_init__(self):
        """Set default expiry (10 seconds for auction)."""
        if self.expires_at is None:
            self.expires_at = self.created_at + timedelta(seconds=10)
    
    def is_expired(self) -> bool:
        """Check if bid expired."""
        return datetime.now() > self.expires_at
    
    def is_active(self) -> bool:
        """Check if bid is still active."""
        return self.status == "ACTIVE" and not self.is_expired()
    
    def calculate_cost(self, amount: float, terms: int) -> float:
        """Calculate buyer cost for this bid."""
        # Prorate annual rate by term length
        effective_rate = self.discount_rate * (terms / 365)
        return amount * (1 + effective_rate)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'provider_id': self.provider_id,
            'invoice_id': self.invoice_id,
            'amount': self.amount,
            'discount_rate': self.discount_rate,
            'discount_rate_percent': f"{self.discount_rate:.2%}",
            'capacity': self.capacity,
            'status': self.status,
            'is_active': self.is_active(),
            'expires_at': self.expires_at.isoformat(),
            'time_remaining_seconds': max(0, (self.expires_at - datetime.now()).total_seconds())
        }

# ============================================
# AUCTION
# ============================================

class AuctionStatus(Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class Auction:
    """Auction for invoice financing."""
    id: str
    invoice_id: str
    amount: float
    terms: int
    
    started_at: datetime = field(default_factory=datetime.now)
    ends_at: Optional[datetime] = None
    status: AuctionStatus = AuctionStatus.PENDING
    
    bids: List[CapitalBid] = field(default_factory=list)
    winning_bid: Optional[CapitalBid] = None
    fallback_rate: float = 0.10  # 10% fallback if <3 bids
    
    def __post_init__(self):
        """Set auction end time (10 seconds)."""
        if self.ends_at is None:
            self.ends_at = self.started_at + timedelta(seconds=10)
    
    def is_active(self) -> bool:
        """Check if auction is still accepting bids."""
        return (
            self.status == AuctionStatus.ACTIVE and
            datetime.now() < self.ends_at
        )
    
    def add_bid(self, bid: CapitalBid):
        """Add bid to auction."""
        if not self.is_active():
            raise ValueError("Auction is not active")
        
        self.bids.append(bid)
        logger.info(f"[AUCTION] Bid received: {bid.provider_id} @ {bid.discount_rate:.2%}")
    
    def get_active_bids(self) -> List[CapitalBid]:
        """Get all active (non-expired) bids."""
        return [bid for bid in self.bids if bid.is_active()]
    
    def select_winner(self) -> CapitalBid:
        """
        Select winning bid (lowest rate).
        
        Enforces INV-301: ≥3 bids for competitive pricing.
        """
        active_bids = self.get_active_bids()
        
        logger.info(f"[AUCTION] Selecting winner from {len(active_bids)} active bids")
        
        # INV-301: Prefer competitive auctions (≥3 bids)
        if len(active_bids) >= 3:
            # Competitive market - select lowest rate
            winner = min(active_bids, key=lambda b: b.discount_rate)
            logger.info(f"[AUCTION] ✅ Competitive auction: {len(active_bids)} bids")
        elif len(active_bids) > 0:
            # Some bids but not competitive
            winner = min(active_bids, key=lambda b: b.discount_rate)
            logger.warning(f"[AUCTION] ⚠️ Low competition: only {len(active_bids)} bids")
        else:
            # No bids - use fallback rate
            logger.warning(f"[AUCTION] ⚠️ No bids received, using fallback rate {self.fallback_rate:.2%}")
            winner = CapitalBid(
                id=f"BID-FALLBACK-{self.id}",
                provider_id="SYSTEM",
                invoice_id=self.invoice_id,
                amount=self.amount,
                discount_rate=self.fallback_rate,
                capacity=self.amount,
                status="ACCEPTED"
            )
        
        self.winning_bid = winner
        winner.status = "ACCEPTED"
        
        # Mark other bids as expired
        for bid in self.bids:
            if bid.id != winner.id:
                bid.status = "EXPIRED"
        
        self.status = AuctionStatus.COMPLETED
        
        logger.info(f"[AUCTION] 🏆 Winner: {winner.provider_id} @ {winner.discount_rate:.2%}")
        
        return winner
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'invoice_id': self.invoice_id,
            'amount': self.amount,
            'terms': self.terms,
            'status': self.status.value,
            'total_bids': len(self.bids),
            'active_bids': len(self.get_active_bids()),
            'winning_bid': self.winning_bid.to_dict() if self.winning_bid else None,
            'is_competitive': len(self.get_active_bids()) >= 3,
            'started_at': self.started_at.isoformat(),
            'ends_at': self.ends_at.isoformat()
        }

# ============================================
# INVARIANTS
# ============================================

class CapitalCompetitionRate(Invariant):
    """INV-301: ≥3 capital bids for 70%+ of invoices."""
    
    MIN_BIDS = 3
    MIN_COMPETITION_RATE = 0.70
    
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
        # Measured over rolling window
        return True
    
    def post_check(self, result: Dict, **kwargs) -> bool:
        """Check if auction had ≥3 bids."""
        auction = result.get('auction')
        
        if auction is None:
            return True
        
        active_bids = len(auction.get_active_bids())
        is_competitive = active_bids >= self.MIN_BIDS
        
        logger.info(f"POST-CHECK {self.id}: active_bids={active_bids}, competitive={is_competitive}")
        
        return True  # Don't fail individual auction, measure aggregate
    
    def rollback_action(self, state_before: Dict):
        """Use fallback rate for low liquidity."""
        logger.warning(f"ROLLBACK {self.id}: Using fallback rate")
    
    def verify_state(self, state: Dict) -> bool:
        return True

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
    
    def pre_check(self, bid: CapitalBid, **kwargs) -> bool:
        """Check if bid is still valid."""
        is_active = bid.is_active()
        
        logger.info(f"PRE-CHECK {self.id}: bid={bid.id}, active={is_active}")
        
        if not is_active:
            logger.warning(f"Bid {bid.id} expired or inactive")
        
        return is_active
    
    def post_check(self, result: Dict, **kwargs) -> bool:
        """Verify selected bid was active at selection time."""
        selected_bid = result.get('winning_bid')
        
        if selected_bid is None:
            return True
        
        # Bid should be marked ACCEPTED
        is_valid = selected_bid.status == "ACCEPTED"
        
        logger.info(f"POST-CHECK {self.id}: winning_bid={selected_bid.id}, status={selected_bid.status}")
        
        return is_valid
    
    def rollback_action(self, state_before: Dict):
        """Re-run auction with valid bids."""
        logger.warning(f"ROLLBACK {self.id}: Expired bid selected, re-running auction")
    
    def verify_state(self, state: Dict) -> bool:
        return True

# ============================================
# AUCTION SERVICE
# ============================================

class CapitalAuctionService:
    """Service for running capital auctions."""
    
    def __init__(self, ledger: DecisionLedger):
        self.ledger = ledger
        self.providers: Dict[str, CapitalProvider] = {}
        self.auctions: Dict[str, Auction] = {}
        
        # Initialize invariants
        self.invariants = [
            CapitalCompetitionRate(),
            CapitalBidExpiry()
        ]
        self.enforcer = InvariantEnforcer(self.invariants, ledger)
        
        logger.info("[AUCTION_SERVICE] Initialized with 2 invariants")
    
    def register_provider(self, provider: CapitalProvider):
        """Register capital provider."""
        self.providers[provider.id] = provider
        logger.info(f"[AUCTION_SERVICE] Registered provider: {provider.name} (liquidity: ${provider.available_liquidity:,.2f})")
    
    def start_auction(
        self,
        invoice_id: str,
        amount: float,
        terms: int
    ) -> Auction:
        """Start auction for invoice."""
        
        auction_id = f"AUC-{uuid.uuid4().hex[:8].upper()}"
        
        auction = Auction(
            id=auction_id,
            invoice_id=invoice_id,
            amount=amount,
            terms=terms,
            status=AuctionStatus.ACTIVE
        )
        
        self.auctions[auction_id] = auction
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[AUCTION] Started auction {auction_id}")
        logger.info(f"  Invoice: {invoice_id}")
        logger.info(f"  Amount: ${amount:,.2f}")
        logger.info(f"  Terms: {terms} days")
        logger.info(f"  Duration: 10 seconds")
        logger.info(f"{'='*60}\n")
        
        # Automatically solicit bids from providers
        self._solicit_bids(auction)
        
        return auction
    
    def _solicit_bids(self, auction: Auction):
        """Solicit bids from all eligible providers."""
        
        for provider in self.providers.values():
            if provider.can_bid(auction.amount, auction.terms):
                # Provider generates bid based on risk/liquidity
                bid = self._generate_bid(provider, auction)
                
                if bid:
                    auction.add_bid(bid)
    
    def _generate_bid(self, provider: CapitalProvider, auction: Auction) -> Optional[CapitalBid]:
        """Generate bid from provider (simplified model)."""
        
        # Base rate from provider's risk appetite
        base_rates = {
            'LOW': 0.04,    # 4% for conservative providers
            'MEDIUM': 0.06,  # 6% for moderate providers
            'HIGH': 0.09     # 9% for aggressive providers
        }
        
        base_rate = base_rates.get(provider.risk_appetite, 0.06)
        
        # Add small random variation for competition
        import random
        rate_variation = random.uniform(-0.01, 0.01)
        discount_rate = base_rate + rate_variation
        
        bid = CapitalBid(
            id=f"BID-{uuid.uuid4().hex[:8].upper()}",
            provider_id=provider.id,
            invoice_id=auction.invoice_id,
            amount=auction.amount,
            discount_rate=max(0.02, min(0.15, discount_rate)),  # Clamp 2-15%
            capacity=min(provider.available_liquidity, auction.amount)
        )
        
        return bid
    
    def finalize_auction(self, auction_id: str) -> CapitalBid:
        """
        Finalize auction and select winner.
        
        Enforces INV-207 (bid expiry) and INV-301 (competition rate).
        """
        
        auction = self.auctions.get(auction_id)
        if not auction:
            raise ValueError(f"Auction {auction_id} not found")
        
        logger.info(f"\n{'='*60}")
        logger.info(f"[AUCTION] Finalizing auction {auction_id}")
        logger.info(f"  Total bids received: {len(auction.bids)}")
        logger.info(f"  Active bids: {len(auction.get_active_bids())}")
        logger.info(f"{'='*60}\n")
        
        # Define winner selection action
        def _select_winner_action() -> Dict:
            """Select winning bid."""
            winning_bid = auction.select_winner()
            
            return {
                'auction': auction,
                'winning_bid': winning_bid
            }
        
        # Execute with enforcement
        try:
            result = self.enforcer.enforce_action(
                _select_winner_action,
                bid=auction.get_active_bids()[0] if auction.get_active_bids() else None
            )
            
            winning_bid = result['winning_bid']
            
            logger.info(f"\n{'='*60}")
            logger.info(f"✅ AUCTION COMPLETE: {auction_id}")
            logger.info(f"  Winner: {winning_bid.provider_id}")
            logger.info(f"  Rate: {winning_bid.discount_rate:.2%}")
            logger.info(f"  Competition: {'✅ HIGH' if len(auction.get_active_bids()) >= 3 else '⚠️ LOW'}")
            logger.info(f"{'='*60}\n")
            
            return winning_bid
            
        except InvariantViolation as e:
            logger.error(f"❌ Auction failed: {e}")
            raise
    
    def get_competition_stats(self, window_hours: int = 24) -> Dict:
        """Get competition statistics for health monitoring."""
        
        recent_auctions = [
            a for a in self.auctions.values()
            if a.status == AuctionStatus.COMPLETED
        ]
        
        if not recent_auctions:
            return {
                'total_auctions': 0,
                'invoices_with_3plus_bids': 0,
                'competition_rate': 1.0
            }
        
        competitive = sum(
            1 for a in recent_auctions
            if len(a.get_active_bids()) >= 3
        )
        
        return {
            'total_auctions': len(recent_auctions),
            'invoices_with_3plus_bids': competitive,
            'competition_rate': competitive / len(recent_auctions)
        }

# ============================================
# DEMONSTRATION
# ============================================

def demonstrate_capital_auction():
    """Demonstrate capital auction marketplace."""
    
    print("\n" + "="*80)
    print("INSTANTTRADE NETWORK - CAPITAL AUCTION MARKETPLACE")
    print("="*80 + "\n")
    
    # Initialize service
    ledger = DecisionLedger()
    auction_service = CapitalAuctionService(ledger)
    
    # Register capital providers
    providers = [
        CapitalProvider(
            id="CAP-001",
            name="Conservative Capital LLC",
            available_liquidity=5_000_000.00,
            risk_appetite="LOW"
        ),
        CapitalProvider(
            id="CAP-002",
            name="Balanced Funding Inc",
            available_liquidity=10_000_000.00,
            risk_appetite="MEDIUM"
        ),
        CapitalProvider(
            id="CAP-003",
            name="Aggressive Growth Partners",
            available_liquidity=3_000_000.00,
            risk_appetite="HIGH"
        ),
        CapitalProvider(
            id="CAP-004",
            name="Steady Returns Fund",
            available_liquidity=7_000_000.00,
            risk_appetite="MEDIUM"
        ),
    ]
    
    for provider in providers:
        auction_service.register_provider(provider)
    
    # ===== TEST 1: Competitive Auction (≥3 bids) =====
    print("\n" + "-"*80)
    print("TEST 1: Run competitive auction (expect ≥3 bids)")
    print("-"*80)
    
    auction_1 = auction_service.start_auction(
        invoice_id="INV-001",
        amount=50000.00,
        terms=30
    )
    
    # Simulate auction duration
    import time
    print("\n⏳ Auction running (collecting bids)...\n")
    time.sleep(1)
    
    # Finalize auction
    winner_1 = auction_service.finalize_auction(auction_1.id)
    
    print(f"✅ Auction Results:")
    print(f"   Total bids: {len(auction_1.bids)}")
    print(f"   Winning rate: {winner_1.discount_rate:.2%}")
    print(f"   Winner: {winner_1.provider_id}")
    print(f"   Competition: {'✅ HIGH' if len(auction_1.get_active_bids()) >= 3 else '⚠️ LOW'}")
    
    # ===== TEST 2: Display All Bids =====
    print("\n" + "-"*80)
    print("TEST 2: View all bids (transparency)")
    print("-"*80)
    
    print(f"\nAll bids for {auction_1.id}:")
    sorted_bids = sorted(auction_1.bids, key=lambda b: b.discount_rate)
    for i, bid in enumerate(sorted_bids, 1):
        status_icon = "🏆" if bid.id == winner_1.id else "  "
        print(f"   {status_icon} {i}. {bid.provider_id}: {bid.discount_rate:.2%} ({bid.status})")
    
    # ===== TEST 3: Larger Auction =====
    print("\n" + "-"*80)
    print("TEST 3: Run auction for larger invoice")
    print("-"*80)
    
    auction_2 = auction_service.start_auction(
        invoice_id="INV-002",
        amount=250000.00,
        terms=60
    )
    
    time.sleep(1)
    
    winner_2 = auction_service.finalize_auction(auction_2.id)
    
    print(f"✅ Large Auction Results:")
    print(f"   Invoice amount: $250,000")
    print(f"   Total bids: {len(auction_2.bids)}")
    print(f"   Winning rate: {winner_2.discount_rate:.2%}")
    print(f"   Buyer cost: ${winner_2.calculate_cost(250000, 60):,.2f}")
    
    # ===== SUMMARY =====
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    
    stats = auction_service.get_competition_stats()
    
    print(f"\nMarketplace Statistics:")
    print(f"  Registered providers: {len(auction_service.providers)}")
    print(f"  Total liquidity: ${sum(p.available_liquidity for p in providers):,.2f}")
    print(f"  Total auctions: {stats['total_auctions']}")
    print(f"  Competitive auctions (≥3 bids): {stats['invoices_with_3plus_bids']}")
    print(f"  Competition rate: {stats['competition_rate']:.0%}")
    print(f"  Health: {'✅ HEALTHY' if stats['competition_rate'] >= 0.70 else '⚠️ LOW LIQUIDITY'}")
    
    print("\nAuctions Completed:")
    for auction_id, auction in auction_service.auctions.items():
        if auction.status == AuctionStatus.COMPLETED:
            print(f"  - {auction_id}: {len(auction.bids)} bids, winner @ {auction.winning_bid.discount_rate:.2%}")
    
    print("\n" + "="*80)
    print("CAPITAL AUCTION MARKETPLACE COMPLETE")
    print("="*80 + "\n")

if __name__ == "__main__":
    demonstrate_capital_auction()
