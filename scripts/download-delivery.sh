#!/usr/bin/env bash
set -euo pipefail
mkdir -p .tools
curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 10 --max-time 120 \
  'https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-cab97a1/delivery-linux-amd64' \
  --output .tools/delivery-linux-amd64
printf '%s  %s\n' \
  '5ce0faf1428a0cca6e4a76d10f30ebdcfe892c10b82f5d60c3d1286c773a03cd' \
  '.tools/delivery-linux-amd64' | sha256sum --check --strict
chmod 0700 .tools/delivery-linux-amd64

curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 10 --max-time 120 \
  'https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-cab97a1/delivery-postgres-tests-linux-amd64' \
  --output .tools/delivery-postgres-tests-linux-amd64
printf '%s  %s\n' \
  '4db6068c6f6d4f7b3a52399b5fe88fddc08532b11f89343e14cf45a2346d4a94' \
  '.tools/delivery-postgres-tests-linux-amd64' | sha256sum --check --strict
chmod 0755 .tools/delivery-postgres-tests-linux-amd64
