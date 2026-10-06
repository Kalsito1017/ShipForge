.PHONY: install test lint format typecheck dev dev-down cluster cluster-delete \
        build deploy undeploy logs status migrate migration clean help

PY ?= python3
COMPOSE ?= docker compose
HELM_RELEASE ?= shipment-platform
HELM_CHART := infrastructure/helm/shipment-platform
KIND_CLUSTER ?= shipment-platform

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e "apps/api[dev]" -e "apps/worker[dev]"

test: ## Run the test suite
	$(PY) -m pytest

lint: ## Lint with ruff
	$(PY) -m ruff check .

format: ## Format code with ruff
	$(PY) -m ruff format .

typecheck: ## Type check with mypy
	$(PY) -m mypy apps

dev: ## Start development environment (Docker Compose)
	$(COMPOSE) up -d

dev-down: ## Stop development environment
	$(COMPOSE) down

cluster: ## Create local kind cluster
	./scripts/cluster-create.sh

cluster-delete: ## Delete local kind cluster
	./scripts/cluster-delete.sh

build: ## Build Docker images
	$(COMPOSE) build

deploy: ## Deploy to local Kubernetes (Helm)
	helm upgrade --install $(HELM_RELEASE) $(HELM_CHART) --values $(HELM_CHART)/values-local.yaml

undeploy: ## Remove the Helm deployment
	helm uninstall $(HELM_RELEASE)

logs: ## Tail service logs
	$(COMPOSE) logs -f

status: ## Show service status
	$(COMPOSE) ps
	@kubectl get pods 2>/dev/null || true

migrate: ## Apply database migrations
	alembic upgrade head

migration: ## Create a new migration (usage: make migration m="description")
	alembic revision --autogenerate -m "$(m)"

clean: ## Remove build/test artifacts
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov coverage.xml .coverage
