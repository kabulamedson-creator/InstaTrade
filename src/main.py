from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, constr
from typing import List
import uvicorn

app = FastAPI()

class Invoice(BaseModel):
    id: int
    amount: float
    currency: constr(min_length=3, max_length=3)

class Settlement(BaseModel):
    invoice_id: int
    status: str

class PricingQuote(BaseModel):
    currency_from: constr(min_length=3, max_length=3)
    currency_to: constr(min_length=3, max_length=3)
    amount: float

class HealthCheckResponse(BaseModel):
    status: str

# In-memory storage (for demonstration purposes)
Invoices = []
Settlements = []
PricingQuotes = []

@app.post("/invoices/", response_model=Invoice)
async def create_invoice(invoice: Invoice):
    Invoices.append(invoice)
    return invoice

@app.post("/settlements/", response_model=Settlement)
async def execute_settlement(settlement: Settlement):
    Settlements.append(settlement)
    return settlement

@app.post("/pricing_quotes/", response_model=PricingQuote)
async def create_pricing_quote(quote: PricingQuote):
    PricingQuotes.append(quote)
    return quote

@app.get("/health-check/", response_model=HealthCheckResponse)
async def health_check():
    return HealthCheckResponse(status="OK")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)