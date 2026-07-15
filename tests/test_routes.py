"""Route smoke tests (PLAN.md V2): every route must return 200 against the synthetic journal."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ROUTES = ["/", "/spending", "/income", "/networth", "/investments", "/annual-review", "/transactions", "/accounts"]


@pytest.mark.parametrize("path", ROUTES)
def test_route_returns_200(path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("path", ROUTES)
def test_no_route_renders_error_banner(path):
    # base.html only renders this class when the router caught an exception
    # and passed `error` to the template — a 200 with this banner present
    # means the route degraded to its empty-state fallback silently.
    resp = client.get(path)
    assert "bg-red-900/40" not in resp.text


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.parametrize("path", ["/", "/annual-review"])
def test_sankey_panel_renders_with_data(path):
    resp = client.get(path)
    assert "sankeyChart(" in resp.text


def test_budget_panel_renders_with_data():
    resp = client.get("/spending")
    assert "budgetChart(" in resp.text
