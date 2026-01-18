.PHONY: help version build test clean install dev lint format

# Default target
help:
	@echo "Available commands:"
	@echo "  make version VERSION=x.y.z  - Update version in all files"
	@echo "  make build                  - Build release wheel"
	@echo "  make dev                    - Build development wheel"
	@echo "  make test                   - Run all tests"
	@echo "  make lint                   - Run linters"
	@echo "  make format                 - Format code"
	@echo "  make clean                  - Clean build artifacts"
	@echo "  make install                - Install package in dev mode"

# Update version in all files
version:
	@if [ -z "$(VERSION)" ]; then \
		echo "Error: VERSION is required. Usage: make version VERSION=0.6.0"; \
		exit 1; \
	fi
	@echo "Updating version to $(VERSION)..."
	@# Update Cargo.toml
	@sed -i.bak 's/^version = ".*"/version = "$(VERSION)"/' Cargo.toml && rm Cargo.toml.bak
	@# Update pyproject.toml
	@sed -i.bak 's/^version = ".*"/version = "$(VERSION)"/' pyproject.toml && rm pyproject.toml.bak
	@# Update __init__.py
	@sed -i.bak 's/__version__ = ".*"/__version__ = "$(VERSION)"/' python/vtt_builder/__init__.py && rm python/vtt_builder/__init__.py.bak
	@echo "✓ Updated Cargo.toml to $(VERSION)"
	@echo "✓ Updated pyproject.toml to $(VERSION)"
	@echo "✓ Updated python/vtt_builder/__init__.py to $(VERSION)"
	@echo ""
	@echo "Next steps:"
	@echo "  1. Review changes: git diff"
	@echo "  2. Commit: git add -A && git commit -m 'bump: version $(VERSION)'"
	@echo "  3. Tag: git tag v$(VERSION)"
	@echo "  4. Push: git push && git push origin v$(VERSION)"

# Build release wheel
build:
	@echo "Building release wheel..."
	uv run maturin build --release

# Build and install in development mode
dev:
	@echo "Building and installing in development mode..."
	uv run maturin develop

# Run all tests
test:
	@echo "Running tests..."
	uv run pytest tests/ -v

# Run linters
lint:
	@echo "Running Python linters..."
	uv tool run ruff check python/ tests/
	@echo "Running Rust linter..."
	cargo clippy --all-targets -- -D warnings

# Format code
format:
	@echo "Formatting Python code..."
	uv tool run ruff format python/ tests/
	@echo "Formatting Rust code..."
	cargo fmt

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf target/
	rm -rf dist/
	rm -rf *.so
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true

# Install package in development mode
install: dev
