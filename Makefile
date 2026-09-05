.PHONY: install install-dev test lint type-check dev clean

# Install production dependencies
install:
	pip install -r requirements.txt

# Install dev dependencies
install-dev: install
	pip install mypy ruff pytest pytest-cov pytest-asyncio

# Run tests with coverage
test:
	pytest --cov=app --cov-report=term-missing

# Lint check
lint:
	ruff check .

# Type check
type-check:
	mypy app/ --ignore-missing-imports

# Start dev server
dev:
	uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Clean cache files
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache .mypy_cache
