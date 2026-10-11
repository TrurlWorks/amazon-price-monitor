SHELL = /bin/sh
COMPOSE = docker compose
BACKEND_TESTS = tests

.PHONY: help config up down status logs test-backend test-frontend verify

help:
	@printf '%s\n' \
		'make config         Validate Compose without printing configuration' \
		'make up             Build and start the application' \
		'make down           Stop services without deleting data' \
		'make status         Show service status' \
		'make logs           Follow the last 100 lines of service logs' \
		'make test-backend   Run pytest (BACKEND_TESTS=tests/path.py)' \
		'make test-frontend  Rebuild frontend: lint, tests and build' \
		'make verify         Config, all tests, frontend build, diff check' \
		'Requires Docker Compose v2 and Make; run from repository root.' \
		'Tests use fresh builds; frontend dependency installation needs network.'

config:
	$(COMPOSE) config --quiet

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

status:
	$(COMPOSE) ps -a

logs:
	$(COMPOSE) logs --tail=100 -f

test-backend:
	$(COMPOSE) build api
	$(COMPOSE) run --rm --no-deps -T -e PRODUCT_PROVIDER=mock -e MONITOR_DATA_DIR=/tmp/monitor-test api python -m pytest -p no:cacheprovider $(BACKEND_TESTS)

test-frontend:
	$(COMPOSE) build --no-cache web

verify:
	$(MAKE) config
	$(MAKE) test-backend BACKEND_TESTS=tests
	$(MAKE) test-frontend
	git diff --check
