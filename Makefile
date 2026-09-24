.PHONY: install lint format typecheck test test-cov run-api run-job-worker run-vector-worker run-reconciliation-worker compose-up compose-down build

install:
	poetry install
	poetry run pre-commit install

lint:
	poetry run ruff check src tests

format:
	poetry run black src tests
	poetry run ruff check --fix src tests

typecheck:
	poetry run mypy src

test:
	poetry run pytest tests/unit tests/contract

test-cov:
	poetry run pytest --cov=src/label_agent --cov-report=html

run-api:
	poetry run python -m label_agent.main --mode api

run-job-worker:
	poetry run python -m label_agent.main --mode job_worker

run-vector-worker:
	poetry run python -m label_agent.main --mode vector_worker

run-reconciliation-worker:
	poetry run python -m label_agent.main --mode reconciliation_worker

compose-up:
	docker compose -f deploy/docker-compose.yml up -d

compose-down:
	docker compose -f deploy/docker-compose.yml down -v

build:
	docker build -t label-agent:local .
