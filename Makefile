# SQL Analytics Workbench — developer entry points.
# Every target must work from a clean checkout after `cp .env.example .env`.

SHELL := /bin/bash
COMPOSE := docker compose
-include .env
export

.DEFAULT_GOAL := help

.PHONY: help up down restart reset logs ps psql-museum psql-dvd seed restore-dvd test lint fmt verify tools bench

help: ## показати перелік команд
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

up: ## підняти стек і розгорнути обидві бази
	$(COMPOSE) up -d --build
	@echo "API:     http://localhost:$(API_PORT)"
	@echo "Swagger: http://localhost:$(API_PORT)/docs"

tools: ## додатково підняти pgAdmin
	$(COMPOSE) --profile tools up -d
	@echo "pgAdmin: http://localhost:$(PGADMIN_PORT)"

down: ## зупинити контейнери (дані зберігаються)
	$(COMPOSE) down

restart: ## перезапустити api
	$(COMPOSE) restart api

reset: ## ПОВНІСТЮ перебудувати бази з нуля (видаляє том з даними!)
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build
	@echo "Бази перебудовано з нуля."

logs: ## логи api
	$(COMPOSE) logs -f api

ps: ## стан контейнерів
	$(COMPOSE) ps

psql-museum: ## psql до бази museum під saw_admin
	$(COMPOSE) exec -e PGPASSWORD=$(SAW_ADMIN_PASSWORD) postgres \
	  psql -U $(SAW_ADMIN_USER) -d $(MUSEUM_DB)

psql-dvd: ## psql до бази dvdrental під saw_admin
	$(COMPOSE) exec -e PGPASSWORD=$(SAW_ADMIN_PASSWORD) postgres \
	  psql -U $(SAW_ADMIN_USER) -d $(DVDRENTAL_DB)

seed: ## перегенерувати тестові дані museum (без перебудови схеми)
	$(COMPOSE) exec -e PGPASSWORD=$(SAW_ADMIN_PASSWORD) postgres \
	  psql -v ON_ERROR_STOP=1 -U $(SAW_ADMIN_USER) -d $(MUSEUM_DB) \
	  -f /db/museum/07_generate_data.sql

restore-dvd: ## перевідновити dvdrental з db/dvdrental/dvdrental.tar (не чіпає museum)
	$(COMPOSE) exec postgres sh -c 'psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$$DVDRENTAL_DB\" WITH (FORCE)"'
	$(COMPOSE) exec postgres bash /docker-entrypoint-initdb.d/20_databases.sh
	$(COMPOSE) exec postgres bash /docker-entrypoint-initdb.d/30_restore_dvdrental.sh
	$(COMPOSE) exec postgres bash /docker-entrypoint-initdb.d/50_grants.sh
	$(COMPOSE) restart api
	@echo "dvdrental перевідновлено. make psql-dvd -> SELECT count(*) FROM rental; має повернути 16044."

test: ## прогнати тести
	$(COMPOSE) exec api pytest -q

lint: ## перевірка стилю
	$(COMPOSE) exec api ruff check app tests
	$(COMPOSE) exec api ruff format --check app tests

fmt: ## автоформатування
	$(COMPOSE) exec api ruff format app tests
	$(COMPOSE) exec api ruff check --fix app tests

bench: ## прогнати всі бенчмарки і записати reports/benchmarks.csv
	$(COMPOSE) exec api python -m scripts.run_all_benchmarks

verify: ## перевірка критеріїв приймання (SPEC.md §7)
	$(COMPOSE) exec api python -m scripts.verify
