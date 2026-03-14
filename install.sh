#!/usr/bin/env sh
# issueclaw installer
# Usage: curl -fsSL https://raw.githubusercontent.com/aviadr1/issueclaw/main/install.sh | sh

set -e

GITHUB_REPO="https://github.com/aviadr1/issueclaw.git"

echo "Installing issueclaw from $GITHUB_REPO ..."

if ! command -v uv >/dev/null 2>&1; then
    echo "Error: 'uv' is required but not found." >&2
    echo "Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    exit 1
fi

uv tool install "git+$GITHUB_REPO"

echo ""
echo "issueclaw installed successfully."
echo "Run 'issueclaw --help' to get started."
echo "Run 'issueclaw self skill' to see the agent usage guide."
