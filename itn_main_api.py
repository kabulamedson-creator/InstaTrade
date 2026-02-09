"""
InstantTrade Network - FastAPI Application
Production API with full enforcement and observability
"""

from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import logging
from contextlib import asynccontextmanager

# Import services
from services.invoice_service import InvoiceCreationService, LineItem as ServiceLineItem
from services.settlement_service import SettlementService
from services.pricing_service import PricingService
from enforcement import (
    InvoiceStorage,
    AccountService,
    SettlementLedger,
    DecisionLedger,
    SettlementRailManager,
    BalanceService,
    InvariantViolation
)
from metrics import (
    metrics_registry,
    invoice_created_counter,
    settlement_completed_counter,
    settlement_duration_histogram,
    invariant_check_counter,
    system_health_gauge
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("itn.api")

# ============================================
# PYDANTIC MODELS (API DTOs)
# ============================================

class LineItemRequest(BaseModel):
    description: str = Field(..., min_length=1, max_length=500)
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., gt=0)
    
    class Config:
        json_schema_extra = {
            "example": {
                "description": "Widget Model A",
                "quantity": 100,
                "unit_price": 250.00
            }
        }

class InvoiceCreateRequest(BaseModel):
    supplier_id: str = Field(..., pattern=r'^SUP-\d{3}$')
    buyer_id: str = Field(..., pattern=r'^BUY-\d{3}$')
    line_items: List[LineItemRequest] = Field(..., min_length=1)
    terms: int = Field(..., ge=0, le=90)
    purchase_order_id: Optional[str] = None
    notes: Optional[str] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "supplier_id": "SUP-001",
                "buyer_id": "BUY-001",
                "line_items": [
                    {"description": "Widget Model A", "quantity": 100, "unit_price": 250.00}
                ],
                "terms": 30,
                "purchase_order_id": "PO-12345"
            }
        }

class InvoiceResponse(BaseModel):
    id: str
    supplier_id: str
    buyer_id: str
    amount: float
    terms: int
    status: str
    created_at: str
    invoice_hash: str
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "INV-ABC123",
                "supplier_id": "SUP-001",
                "buyer_id": "BUY-001",
                "amount": 50000.00,
                "terms": 30,
                "status": "PENDING",
                "created_at": "2026-02-08T21:00:00Z",
                "invoice_hash": "7c3f9a2e8d4b..."
            }
        }

class AcceptInvoiceRequest(BaseModel):
    buyer_id: str = Field(..., pattern=r'^BUY-\d{3}$')
    chosen_terms: Optional[int] = Field(None, ge=0, le=90)

class PricingQuoteResponse(BaseModel):
    invoice_id: str
    terms: int
    discount_rate: float
    total_cost: float
    expires_at: str

class SettlementResponse(BaseModel):
    id: str
    invoice_id: str
    status: str
    duration_seconds: float
    supplier_credited: float
    buyer_debited: float
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": "SET-INV-ABC123-1234567890",
                "invoice_id": "INV-ABC123",
                "status": "COMPLETED",
                "duration_seconds": 2.134,
                "supplier_credited": 50000.00,
                "buyer_debited": 52500.00
            }
        }

class HealthResponse(BaseModel):
    status: str
    version: str
    health_score: float
    total_invoices: int
    total_settlements: int
    ledger_balanced: bool
    ledger_integrity: bool

# ============================================
# APPLICATION LIFECYCLE
# ============================================

class AppState:
    """Global application state."""
    def __init__(self):
        self.invoice_storage = InvoiceStorage()
        self.account_service = AccountService()
        self.settlement_ledger = SettlementLedger()
        self.decision_ledger = DecisionLedger()
        self.rail_manager = SettlementRailManager()
        self.balance_service = BalanceService()
        self.pricing_service = PricingService()
        
        self.invoice_service = InvoiceCreationService(
            self.invoice_storage,
            self.account_service,
            self.decision_ledger
        )
        
        self.settlement_service = SettlementService(
            self.settlement_ledger,
            self.decision_ledger,
            self.rail_manager,
            self.balance_service
        )

app_state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    logger.info("🚀 InstantTrade Network starting...")
    logger.info("✅ All services initialized")
    yield
    logger.info("🛑 InstantTrade Network shutting down...")

# ============================================
# FASTAPI APPLICATION
# ============================================

app = FastAPI(
    title="InstantTrade Network",
    description="B2B payment rails with embedded working capital",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# API ENDPOINTS
# ============================================

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint."""
    return {
        "service": "InstantTrade Network",
        "version": "1.0.0",
        "status": "operational"
    }

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """System health check."""
    total_invoices = len(app_state.invoice_storage.get_all_invoices())
    total_settlements = len(app_state.settlement_ledger.settlements)
    total_checks = len(app_state.decision_ledger.entries)
    
    passed_checks = sum(1 for e in app_state.decision_ledger.entries if e.result)
    health_score = passed_checks / total_checks if total_checks > 0 else 1.0
    
    ledger_balanced = abs(
        app_state.settlement_ledger.sum_all_credits() - 
        app_state.settlement_ledger.sum_all_debits()
    ) < 0.01
    
    # Update Prometheus metrics
    system_health_gauge.set(health_score)
    
    return HealthResponse(
        status="healthy" if health_score >= 0.95 else "degraded",
        version="1.0.0",
        health_score=health_score,
        total_invoices=total_invoices,
        total_settlements=total_settlements,
        ledger_balanced=ledger_balanced,
        ledger_integrity=app_state.decision_ledger.verify_chain_integrity()
    )

@app.post("/api/v1/invoices", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED, tags=["Invoices"])
async def create_invoice(request: InvoiceCreateRequest):
    """
    Create a new invoice.
    
    Enforces invariants:
    - INV-001: Unique invoice IDs
    - INV-002: Valid amounts ($100 - $10M)
    - INV-003: Active accounts
    - INV-004: No duplicate hashes
    - INV-007: Valid payment terms
    - INV-602: Line items sum correctly
    - INV-404: Rate limiting
    """
    try:
        # Convert Pydantic models to service models
        line_items = [
            ServiceLineItem(
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price
            )
            for item in request.line_items
        ]
        
        # Create invoice
        invoice = app_state.invoice_service.create_invoice(
            supplier_id=request.supplier_id,
            buyer_id=request.buyer_id,
            line_items=line_items,
            terms=request.terms,
            purchase_order_id=request.purchase_order_id,
            notes=request.notes
        )
        
        # Update metrics
        invoice_created_counter.labels(
            supplier_id=request.supplier_id,
            buyer_id=request.buyer_id
        ).inc()
        
        return InvoiceResponse(
            id=invoice.id,
            supplier_id=invoice.supplier_id,
            buyer_id=invoice.buyer_id,
            amount=invoice.amount,
            terms=invoice.terms,
            status=invoice.status,
            created_at=invoice.created_at.isoformat(),
            invoice_hash=invoice.invoice_hash
        )
        
    except InvariantViolation as e:
        logger.error(f"Invoice creation failed: {e}")
        invariant_check_counter.labels(result="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invariant violation: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error"
        )

@app.get("/api/v1/invoices/{invoice_id}", response_model=InvoiceResponse, tags=["Invoices"])
async def get_invoice(invoice_id: str):
    """Get invoice by ID."""
    invoice = app_state.invoice_storage.get_invoice(invoice_id)
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found"
        )
    
    return InvoiceResponse(
        id=invoice.id,
        supplier_id=invoice.supplier_id,
        buyer_id=invoice.buyer_id,
        amount=invoice.amount,
        terms=invoice.terms,
        status=invoice.status,
        created_at=invoice.created_at.isoformat(),
        invoice_hash=invoice.invoice_hash
    )

@app.post("/api/v1/invoices/{invoice_id}/accept", tags=["Invoices"])
async def accept_invoice(invoice_id: str, request: AcceptInvoiceRequest):
    """
    Buyer accepts invoice.
    
    Returns pricing quote for the chosen payment terms.
    """
    invoice = app_state.invoice_storage.get_invoice(invoice_id)
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found"
        )
    
    if invoice.buyer_id != request.buyer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to accept this invoice"
        )
    
    if invoice.status != "PENDING":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice is {invoice.status}, cannot accept"
        )
    
    # Use chosen terms or invoice default
    terms = request.chosen_terms if request.chosen_terms is not None else invoice.terms
    
    # Generate pricing quote
    quote = app_state.pricing_service.generate_quote(invoice_id, invoice.amount, terms)
    
    # Update invoice status
    invoice.status = "ACCEPTED"
    
    return PricingQuoteResponse(
        invoice_id=quote.invoice_id,
        terms=quote.terms,
        discount_rate=quote.discount_rate,
        total_cost=quote.total_cost,
        expires_at=quote.expires_at.isoformat()
    )

@app.post("/api/v1/settlements", response_model=SettlementResponse, status_code=status.HTTP_201_CREATED, tags=["Settlements"])
async def execute_settlement(
    invoice_id: str,
    capital_provider_id: str = "CAP-001"
):
    """
    Execute settlement for accepted invoice.
    
    Enforces invariants:
    - INV-006: Settlement exactly once
    - INV-102: Atomic settlement
    - INV-201: Settlement <5 seconds
    """
    invoice = app_state.invoice_storage.get_invoice(invoice_id)
    
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found"
        )
    
    if invoice.status != "ACCEPTED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invoice must be ACCEPTED to settle (current: {invoice.status})"
        )
    
    # Get pricing quote
    quote = app_state.pricing_service.get_quote(invoice_id)
    
    if not quote:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid pricing quote found"
        )
    
    try:
        # Execute settlement
        settlement = app_state.settlement_service.execute_settlement(
            invoice_id=invoice_id,
            supplier_id=invoice.supplier_id,
            buyer_id=invoice.buyer_id,
            capital_provider_id=capital_provider_id,
            amount=invoice.amount,
            discount_rate=quote.discount_rate
        )
        
        # Update metrics
        settlement_completed_counter.labels(
            supplier_id=invoice.supplier_id,
            buyer_id=invoice.buyer_id
        ).inc()
        
        settlement_duration_histogram.observe(settlement.duration_seconds())
        invariant_check_counter.labels(result="passed").inc()
        
        return SettlementResponse(
            id=settlement.id,
            invoice_id=settlement.invoice_id,
            status=settlement.status.value,
            duration_seconds=settlement.duration_seconds(),
            supplier_credited=settlement.supplier_credit.amount,
            buyer_debited=settlement.buyer_debit.amount
        )
        
    except InvariantViolation as e:
        logger.error(f"Settlement failed: {e}")
        invariant_check_counter.labels(result="failed").inc()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invariant violation: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Settlement error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Settlement failed"
        )

@app.get("/api/v1/invoices", tags=["Invoices"])
async def list_invoices(
    supplier_id: Optional[str] = None,
    buyer_id: Optional[str] = None,
    status: Optional[str] = None
):
    """List all invoices with optional filters."""
    invoices = app_state.invoice_storage.get_all_invoices()
    
    # Apply filters
    if supplier_id:
        invoices = [inv for inv in invoices if inv.supplier_id == supplier_id]
    if buyer_id:
        invoices = [inv for inv in invoices if inv.buyer_id == buyer_id]
    if status:
        invoices = [inv for inv in invoices if inv.status == status]
    
    return [
        InvoiceResponse(
            id=inv.id,
            supplier_id=inv.supplier_id,
            buyer_id=inv.buyer_id,
            amount=inv.amount,
            terms=inv.terms,
            status=inv.status,
            created_at=inv.created_at.isoformat(),
            invoice_hash=inv.invoice_hash
        )
        for inv in invoices
    ]

@app.get("/metrics", tags=["Observability"])
async def metrics():
    """Prometheus metrics endpoint."""
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response
    
    return Response(
        content=generate_latest(metrics_registry),
        media_type=CONTENT_TYPE_LATEST
    )

# ============================================
# ERROR HANDLERS
# ============================================

@app.exception_handler(InvariantViolation)
async def invariant_violation_handler(request, exc):
    logger.error(f"Invariant violation: {exc}")
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"System invariant violated: {str(exc)}"
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
