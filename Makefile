COMPOSE_DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: dev prod down logs

dev:
	$(COMPOSE_DEV) up --build

prod:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f hledger-dash
