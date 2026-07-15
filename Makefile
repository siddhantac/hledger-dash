COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: dev dev-native prod down logs test

dev:
	$(COMPOSE_DEV) up --build

# Native dev loop against the synthetic test journal — no Docker, no
# bind-mount hot-reload flakiness. Point HLEDGER_FILE elsewhere to develop
# against different data. `make dev` (Docker) is still available and is the
# only way to develop against the real journal, which lives only in the
# journal-sync volume.
dev-native:
	HLEDGER_FILE=testdata/synthetic.journal uv run uvicorn app.main:app --reload

prod:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f hledger-dash

test:
	HLEDGER_FILE=testdata/synthetic.journal uv run pytest
