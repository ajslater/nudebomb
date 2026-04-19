# hadolint ignore=DL3007
FROM oven/bun:latest AS bun-source
FROM nikolaik/python-nodejs:python3.14-nodejs24

ENV DEBIAN_FRONTEND=noninteractive

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        mkvtoolnix \
        shellcheck \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY --from=bun-source /usr/local/bin/bun /usr/local/bin/bun
COPY --from=bun-source /usr/local/bin/bunx /usr/local/bin/bunx

WORKDIR /app
COPY bun.lock package.json ./
RUN bun install

COPY . .
RUN mkdir -p test-results dist

# Install
# hadolint ignore=DL3059
RUN uv sync
