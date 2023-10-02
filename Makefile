PROJECT = remotelib
PACKAGES = remotelib tests
VENV = .venv
activate = source $(VENV)/bin/activate

all: lint test

venv: pyproject.toml
	@[[ -d $(VENV) ]] || \
	(echo "Installing venv..."; python3 -m venv $(VENV); $(activate); \
	pip install --quiet . .[doc] .[lint] .[test] 2>/dev/null || exit 1; \
	rm -rf $(PROJECT).egg-info; rm -rf build)

test: venv
	@$(activate); pytest -vv tests/

lint: black isort mypy pylint

black: venv
	@$(activate); black --check $(PACKAGES)
isort: venv
	@$(activate); isort --check $(PACKAGES)
mypy: venv
	@$(activate); mypy $(PACKAGES)
pylint: venv
	@$(activate); pylint $(PACKAGES)

fix: venv
	@$(activate); black $(PACKAGES)
	@$(activate); isort $(PACKAGES)

clean:
	@rm -rf $(VENV)
	@rm -rf docs/build

.PHONY: all venv test lint black isort mypy pylint fix clean
