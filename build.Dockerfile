# hadolint ignore=DL3007
FROM nikolaik/python-nodejs:latest

ENV DEBIAN_FRONTEND=noninteractive

USER root
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
  mkvtoolnix \
  shellcheck \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN chown circleci:circleci /app
COPY --chown=circleci:circleci bin bin

USER circleci
COPY --chown=circleci:circleci pyproject.toml uv.lock package.json package-lock.json ./
RUN npm install

COPY --chown=circleci:circleci . .
RUN mkdir -p test-results dist

# Install
# hadolint ignore=DL3059
RUN uv install
