# GitHub Actions infrastructure PoC

An independently authored, public-safe fixture for evaluating an ephemeral GitHub-hosted CI workflow. It contains no application source imported from another project.

The new bounded PR acceptance route is documented in [PR_ACCEPTANCE.md](PR_ACCEPTANCE.md).
It separates candidate builds from trusted default-branch acceptance, restricts
execution to approved synthetic fixture changes, manages runtime resources through
environments, and produces advisory evidence/Agent feedback. It does not enforce
SCM merge rules. Its Release pins must be enabled before a real run can pass.

## Execution evidence

[Hosted baseline run 40191050924](https://github.com/phodal/ci-poc/actions/runs/40191050924) passed with release `delivery-poc-20261025-cab97a1`, including real Chrome, PostgreSQL adapter integration, and the three Delivery CLI cases. That result applies to the baseline binary only.

The current pins select `delivery-poc-20261025-8e08380`. A completed Actions run must show these exact hashes; the previous green run does not validate a replacement binary.

## What the workflow checks

One Ubuntu 24.04 hosted job, triggered by a push to `master` or a manual run:

1. Formats, unit-tests, race-tests, vets, and builds the Go HTTP demo (now also supporting the optional PostgreSQL-backed order fixture).
2. Starts that demo on loopback and polls a real health endpoint with a bounded timeout.
3. Uses a real, preinstalled Google Chrome browser through locked Playwright Core to load the page, fetch the version, click a counter twice, and fetch health. Browser script errors fail the check.
4. Runs SQL against a real disposable PostgreSQL container, asserting committed data persists and rolled-back data does not.
5. Uploads narrowly scoped logs, version output, a success result, and a public-fixture screenshot for three days, including diagnostic files when earlier steps fail.

The SQL test is an infrastructure check, not an application/database integration test. The demo app itself does not use PostgreSQL. A green run demonstrates these fixture checks only. It does not establish delivery or acceptance of any real product module. Module-level acceptance, deployment validation, and real business contracts remain out of scope and pending separate work.

## Real Delivery binary interoperability checks

A separate workflow step downloads only fixed assets from the public release:

- [delivery-poc-20261025-8e08380 / delivery-linux-amd64](https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-8e08380/delivery-linux-amd64)
- Expected SHA-256: `83044cfebcafa6ea47775ab31893052f4bb9ff5d090a48b52253edef398e8135`

The checksum is checked before execution; neither `latest` nor user-supplied download URLs are accepted. The source for this release binary is not included here.

The demo's `/artifact` endpoint hashes its actual executable bytes. A fresh standard-library Go adapter independently reads that endpoint and `/quote`, whose two units at 1,250 cents total 2,500 cents. It implements only the required JSON interoperability interface.

Three real CLI cases must return completed receipts with confirmed cleanup, matching request/artifact/profile/target identities, nonempty fingerprints, and these conclusions and exit codes:

1. Correct expected quote total and matching executable digest: `PASS`, exit 0.
2. Deliberate negative control expecting 2,501 cents instead of the actual 2,500: `FAIL`, exit 1. This proves rejection of a failed assertion; it is not a claim that a broken application was deployed.
3. Correct quote but a deliberately wrong requested artifact digest: `ERROR`, exit 2, specifically for an observed digest mismatch.

The service and demo are separate loopback processes, launched with a PATH-only environment. The adapter path and working directory are absolute. Each run has an isolated state directory and a public disposable fixture token stored with mode 0600. The token and service state directory are not uploaded. Only fixture receipts and logs are evidence artifacts.

These checks exercise the published binary's local execution boundary and receipt behavior. They are not deployment proof or complete product-module acceptance. PostgreSQL and Chrome checks remain separately labeled infrastructure checks, not implied features of the Delivery adapter.

## Real PostgreSQL adapter integration

The same fixed release supplies a separately compiled functional integration-test binary, without publishing its private source:

- [delivery-postgres-tests-linux-amd64](https://github.com/phodal/ci-poc/releases/download/delivery-poc-20261025-8e08380/delivery-postgres-tests-linux-amd64)
- Expected SHA-256: `3c80d20820bab5435109b90c8ce0978353f7a2025c43b2c714b18a1b0a4ad424`

After checksum verification, the workflow copies it into the existing disposable PostgreSQL container and runs only `TestPostgresIntegration`, as OS user `postgres`, through the container's local Unix socket. It does not connect to an external database, expose a port, or introduce additional credentials or containers. The binary is bounded by a 90-second test timeout and a three-minute step timeout.

This suite is intended to exercise the actual adapter's concurrent unique creation, compare-and-swap behavior, immutable ownership, and terminal-state behavior. The workflow requires the top-level integration test to pass and explicitly rejects skipped tests. Actual coverage evidence is the named tests in the run artifact, not merely the binary's presence. This static binary is not race-detector enabled: it tests functional concurrency, not race instrumentation.

The earlier SQL commit/rollback fixture remains a separate infrastructure smoke check. Neither check establishes remote deployment or full module acceptance.

## Security and execution boundary

- All external Actions use immutable commit SHAs; PostgreSQL uses an immutable image digest. npm uses a committed integrity lockfile with lifecycle scripts disabled.
- The only token permission is `contents: read`; checkout does not persist credentials. No repository secrets, cloud credentials, new secret stores, token writes, remote deployment, or self-hosted runners are needed.
- The original infrastructure smoke workflow has no pull-request trigger. The separate PR acceptance workflows described above add unprivileged candidate builds and trusted, fixture-only acceptance. There is no `pull_request_target` workflow.
- PostgreSQL has no host port published. Its public fixture password is not a secret and must never be reused elsewhere. SQL runs inside its disposable container.
- The app binds to `127.0.0.1` only. The browser test refuses to run outside GitHub-hosted Actions, only visits the loopback fixture, and blocks requests to other origins.
- Chrome's sandbox is explicitly enabled. No `--no-sandbox`, web-security bypass, or host security setting change is used. If runner restrictions prevent sandboxed Chrome startup, the job must fail rather than silently disable security.
- Runtime and artifact retention are bounded. No source archives, environment dumps, credentials, database dumps, or private pages are uploaded.

The hosted runner image and its preinstalled Chrome/Node may change. Their actual versions are recorded in artifacts; this deliberately checks the hosted environment rather than claiming fully hermetic browser reproducibility.

## Run the app locally

With Go 1.23 or newer installed:

```sh
go test -race -count=1 ./...
go vet ./...
go run .
```

Open `http://127.0.0.1:8080`. `GET /healthz` returns `{"status":"ok"}` and `GET /version` returns `{"version":"demo-v1"}`. The hosted-only browser script is not intended to run on a personal computer.

## Permissions and network prerequisites

Publishing requires write access to this repository and permission to create workflow files. The workflow must be enabled by repository/organization Actions policy, with the pinned official Actions allowed and GitHub-hosted runners available. No repository administration changes are performed by the workflow.

The runner needs outbound access to GitHub Actions/package endpoints, the official Go distribution, the npm registry, and Docker Hub. It uses Docker already supplied by GitHub's hosted runner, not an additional privileged installation step. This workflow does not need inbound access or credentials for an external deployment.

## Verified dependency sources

Pins were checked against official metadata on 2026-10-25:

- [actions/checkout v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1): `3d3c42e5aac5ba805825da76410c181273ba90b1`
- [actions/setup-go v7.0.0](https://github.com/actions/setup-go/releases/tag/v7.0.0): `b7ad1dad31e06c5925ef5d2fc7ad053ef454303e`
- [actions/upload-artifact v7.0.2](https://github.com/actions/upload-artifact/releases/tag/v7.0.2): `cf430e030ddbb5b0abf93d22962f4752f3646cd9`
- [Official Go downloads metadata](https://go.dev/dl/?mode=json): Go 1.27.3.
- [Official npm metadata](https://registry.npmjs.org/playwright-core/1.64.1): Playwright Core 1.64.1; tarball integrity is recorded in `package-lock.json`.
- [Docker Official Images metadata](https://github.com/docker-library/repo-info/blob/master/repos/postgres/remote/17-bookworm.md): `postgres:17-bookworm` index digest `sha256:858bb5e98eed02eb8cafbcdc007f9a65d1b613972028944a8ec2133ccaf80d27`.

Actual execution evidence must come from a completed Actions run, not from the presence of these workflow files.
