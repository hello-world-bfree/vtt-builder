#!/usr/bin/env bash
set -e

COLOR_RESET='\033[0m'
COLOR_GREEN='\033[0;32m'
COLOR_BLUE='\033[0;34m'
COLOR_YELLOW='\033[0;33m'
COLOR_RED='\033[0;31m'

print_info() {
    echo -e "${COLOR_BLUE}ℹ${COLOR_RESET} $1"
}

print_success() {
    echo -e "${COLOR_GREEN}✓${COLOR_RESET} $1"
}

print_warning() {
    echo -e "${COLOR_YELLOW}⚠${COLOR_RESET} $1"
}

print_error() {
    echo -e "${COLOR_RED}✗${COLOR_RESET} $1"
}

echo ""
echo "==================================="
echo "  Pre-commit Hook Setup"
echo "==================================="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOK_SOURCE="$PROJECT_ROOT/.git/hooks/pre-commit"
GIT_HOOKS_DIR="$PROJECT_ROOT/.git/hooks"

if [ ! -d "$PROJECT_ROOT/.git" ]; then
    print_error "Not a git repository"
    exit 1
fi

print_info "Checking required tools..."

MISSING_TOOLS=0

if ! command -v uv &> /dev/null; then
    print_warning "uv is not installed"
    echo "  Install with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
else
    print_success "uv is installed"
fi

if ! command -v cargo &> /dev/null; then
    print_warning "cargo is not installed"
    echo "  Install with: curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
else
    print_success "cargo is installed"
fi

if ! command -v rustfmt &> /dev/null; then
    print_warning "rustfmt is not installed"
    echo "  Install with: rustup component add rustfmt"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
else
    print_success "rustfmt is installed"
fi

if ! command -v cargo-clippy &> /dev/null; then
    print_warning "clippy is not installed"
    echo "  Install with: rustup component add clippy"
    MISSING_TOOLS=$((MISSING_TOOLS + 1))
else
    print_success "clippy is installed"
fi

if ! uv tool list | grep -q "ruff" 2>/dev/null; then
    print_warning "ruff is not installed, installing now..."
    if uv tool install ruff; then
        print_success "ruff installed successfully"
    else
        print_error "Failed to install ruff"
        MISSING_TOOLS=$((MISSING_TOOLS + 1))
    fi
else
    print_success "ruff is installed"
fi

if [ $MISSING_TOOLS -ne 0 ]; then
    echo ""
    print_warning "$MISSING_TOOLS required tool(s) missing"
    echo "The pre-commit hook will be installed, but may not work until all tools are installed."
    echo ""
fi

print_info "Installing pre-commit hook..."

if [ ! -d "$GIT_HOOKS_DIR" ]; then
    mkdir -p "$GIT_HOOKS_DIR"
fi

if [ -f "$HOOK_SOURCE" ]; then
    chmod +x "$HOOK_SOURCE"
    print_success "Pre-commit hook is installed and executable"
else
    print_error "Pre-commit hook file not found at $HOOK_SOURCE"
    exit 1
fi

print_info "Testing pre-commit hook..."
if "$HOOK_SOURCE" &> /dev/null; then
    print_success "Pre-commit hook test passed"
else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        print_success "Pre-commit hook test passed"
    else
        print_warning "Pre-commit hook test completed with warnings (exit code: $EXIT_CODE)"
        echo "  This is normal if you have uncommitted changes"
    fi
fi

echo ""
echo "==================================="
echo ""
print_success "Setup complete!"
echo ""
echo "The pre-commit hook will now run automatically on every commit."
echo ""
echo "To bypass the hook (not recommended), use:"
echo "  git commit --no-verify"
echo ""
