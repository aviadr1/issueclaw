# Shared tools only. Repository dependencies and test services belong to adapters.
FROM node:24-bookworm-slim AS node
FROM python:3.14-slim-bookworm
ARG GH_VERSION=2.102.0
ARG CLAUDE_VERSION=2.1.308
ARG BUN_VERSION=1.3.14
ARG UV_VERSION=0.9.6
ENV DEBIAN_FRONTEND=noninteractive \
    DISABLE_AUTOUPDATER=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    REPAIR_NODE=/opt/ci-repair-node
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update \
 && apt-get install -y --no-install-recommends bash ca-certificates curl git jq ripgrep zip unzip openssh-client build-essential pkg-config \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" -o /tmp/gh.tgz \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" -o /tmp/gh-checksums \
 && mv /tmp/gh.tgz "/tmp/gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && cd /tmp && grep " gh_${GH_VERSION}_linux_amd64.tar.gz$" gh-checksums | sha256sum -c - \
 && tar -xzf "gh_${GH_VERSION}_linux_amd64.tar.gz" \
 && cp "gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
 && rm -rf /tmp/gh*
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" "bun@${BUN_VERSION}" \
 && npm install --prefix "$REPAIR_NODE" --ignore-scripts --no-audit --no-fund @actions/artifact@6.3.1 \
 && pip install --no-cache-dir "uv==${UV_VERSION}"
COPY pyproject.toml README.md LICENSE /opt/issueclaw/
COPY src /opt/issueclaw/src
RUN pip install --no-cache-dir /opt/issueclaw \
 && python -c 'import sys; assert sys.version_info[:2] == (3, 14)' \
 && claude --version && gh --version && node --version && bun --version
WORKDIR /workspace
CMD ["bash"]
