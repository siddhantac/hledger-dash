import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

from app.routers import dashboard, expenses, income, reports

app = FastAPI(title="hledger-dash")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(dashboard.router)
app.include_router(expenses.router)
app.include_router(income.router)
app.include_router(reports.router)
