COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml
APP_VERSION := $(shell git describe --tags --always --dirty 2>/dev/null || echo unknown)

.PHONY: dev dev-native prod down logs test

dev:
	APP_VERSION=$(APP_VERSION) $(COMPOSE_DEV) up --build

# Native dev loop against the synthetic test journal — no Docker, no
# bind-mount hot-reload flakiness. Point HLEDGER_FILE elsewhere to develop
# against different data. `make dev` (Docker) is still available and is the
# only way to develop against the real journal, which lives only in the
# journal-sync volume.
dev-native:
	HLEDGER_FILE=$$LEDGER_FILE uv run uvicorn app.main:app --reload

prod:
	APP_VERSION=$(APP_VERSION) docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f hledger-dash

test:
	HLEDGER_FILE=testdata/synthetic.journal uv run pytest
