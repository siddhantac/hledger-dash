import logging

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.routers import accounts, annual_review, dashboard, income, investments, networth, spending, transactions

app = FastAPI(title="hledger-dash")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.get("/health")
def health():
    return JSONResponse({"status": "ok"})

app.include_router(accounts.router)
app.include_router(annual_review.router)
app.include_router(dashboard.router)
app.include_router(income.router)
app.include_router(investments.router)
app.include_router(networth.router)
app.include_router(spending.router)
app.include_router(transactions.router)
