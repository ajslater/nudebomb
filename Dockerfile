# hadolint ignore=DL3007
FROM nikolaik/python-nodejs:python3.14-nodejs24

ENV DEBIAN_FRONTEND=noninteractive

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        mkvtoolnix \
        shellcheck \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# hadolint ignore=DL4006
RUN curl -fsSL https://bun.com/install | bash

WORKDIR /app
COPY pyproject.toml uv.lock package.json package-lock.json ./
RUN bun install

COPY . .
RUN mkdir -p test-results dist

# Install
# hadolint ignore=DL3059
RUN uv sync