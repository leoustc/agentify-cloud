PYTHON ?= python3
UV ?= uv
PORT ?= 8000
API_KEY ?=
API_KEY_FILE ?=
PUBLISH_REPOSITORY ?= pypi
PUBLISH_REPOSITORY_URL ?=
PYPIRC ?= $(HOME)/.pypirc
RUNTIME_DIR ?= runtime
PROJECT_DIR := $(CURDIR)

SERVER_ARGS := --port $(PORT)
ifneq ($(strip $(API_KEY)),)
SERVER_ARGS += -api_key $(API_KEY)
endif
ifneq ($(strip $(API_KEY_FILE)),)
SERVER_ARGS += -api_key_file $(API_KEY_FILE)
endif

ifneq ($(strip $(PUBLISH_REPOSITORY_URL)),)
PUBLISH_ARGS := --repository-url $(PUBLISH_REPOSITORY_URL)
PUBLISH_TARGET := URL '$(PUBLISH_REPOSITORY_URL)'
else
PUBLISH_ARGS := --config-file $(PYPIRC) --repository $(PUBLISH_REPOSITORY)
PUBLISH_TARGET := .pypirc repository '$(PUBLISH_REPOSITORY)' using '$(PYPIRC)'
endif

.PHONY: help install dev build run test compile installed-artifact-check publish publish-artifacts publish-check clean

help:
	@echo "Agentify Cloud targets:"
	@echo "  make install              Install package with uv"
	@echo "  make dev                  Install package with dev/test dependencies"
	@echo "  make build                Build package artifacts"
	@echo "  make run [PORT=8000]      Run agentify server"
	@echo "  make test                 Run tests and syntax checks"
	@echo "  make installed-artifact-check"
	@echo "                             Build/install wheel and start embedded Pi bridge"
	@echo "  make publish              Build and publish to PyPI with uv"
	@echo "  make publish-check        Build fresh artifacts and print the upload command"
	@echo "  make clean                Remove build/test caches"
	@echo ""
	@echo "Optional run args: API_KEY=abc,def API_KEY_FILE=path/to/keys"
	@echo "Runtime cwd: RUNTIME_DIR=runtime; default AGENTS.md is read from there"
	@echo "Optional publish args: PUBLISH_REPOSITORY=pypi PYPIRC=~/.pypirc"
	@echo "Custom repository URL: PUBLISH_REPOSITORY_URL=https://upload.example/simple"
	@echo "PUBLISH_REPOSITORY is a .pypirc section name; URLs must use PUBLISH_REPOSITORY_URL."
	@echo "Publish uses twine. Credentials come from PYPIRC or TWINE_USERNAME/TWINE_PASSWORD."
	@echo "For PyPI API tokens, use username __token__ and the token as the password."
	@echo "An upload 403 means repository or credential authorization failed after a successful build."

install:
	$(UV) pip install -e .

dev:
	$(UV) pip install -e ".[dev]"

build:
	$(UV) build

run:
	mkdir -p $(RUNTIME_DIR)
	cd $(RUNTIME_DIR) && $(UV) run --project $(PROJECT_DIR) agentify server $(SERVER_ARGS)

test:
	$(UV) run --extra dev pytest
	$(UV) run $(PYTHON) -m compileall src

compile:
	$(UV) run $(PYTHON) -m compileall src

installed-artifact-check:
	rm -rf dist
	$(UV) build
	$(PYTHON) scripts/check_installed_artifact.py

publish-artifacts: test
	rm -rf dist
	$(UV) build

publish: publish-artifacts
	@echo "Publishing fresh artifacts from dist/ to $(PUBLISH_TARGET)."
	@echo "If upload fails with 403, check repository permissions and token credentials."
	$(UV) run --with twine twine upload $(PUBLISH_ARGS) dist/*

publish-check: publish-artifacts
	@echo "Fresh artifacts selected by dist/*:"
	@find dist -maxdepth 1 -type f ! -name '.*' -printf '  %p\n' | sort
	@echo "Upload command not run:"
	@echo "  $(UV) run --with twine twine upload $(PUBLISH_ARGS) dist/*"

release: publish

clean:
	rm -rf build dist *.egg-info .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
