#!/usr/bin/env bash
set -euo pipefail
mkdir -p .tools
curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 10 --max-time 120 \
  'https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-8e08380/delivery-linux-amd64' \
  --output .tools/delivery-linux-amd64
printf '%s  %s\n' \
  '83044cfebcafa6ea47775ab31893052f4bb9ff5d090a48b52253edef398e8135' \
  '.tools/delivery-linux-amd64' | sha256sum --check --strict
chmod 0700 .tools/delivery-linux-amd64

curl --fail --location --silent --show-error \
  --proto '=https' --proto-redir '=https' --tlsv1.2 --connect-timeout 10 --max-time 120 \
  'https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-8e08380/delivery-postgres-tests-linux-amd64' \
  --output .tools/delivery-postgres-tests-linux-amd64
printf '%s  %s\n' \
  '3c80d20820bab5435109b90c8ce0978353f7a2025c43b2c714b18a1b0a4ad424' \
  '.tools/delivery-postgres-tests-linux-amd64' | sha256sum --check --strict
chmod 0755 .tools/delivery-postgres-tests-linux-amd64
