# PR candidate acceptance slice

This repository is an independently authored public fixture. Private Point
source is never copied here. The trusted acceptance/runtime/gate implementations
are supplied only as reviewed, immutable Release binaries.

## Runtime ownership

CI compiles the candidate without running it. The candidate is packaged as a
fixed, non-root scratch image. The private acceptance harness uses environments
to provision and own the candidate application, disposable PostgreSQL and the
trusted browser executor. The CI workflow does not start a separate application,
database or browser process outside that lifecycle.

The public app keeps the old counter/quote infrastructure smoke when no database
is configured. With `DATABASE_URL` set, `/` and `/shop` show the order form.
The fixed acceptance recipe seeds SKU-1 with inventory 10. Quantity 2 has a quote
of 4,498 cents (1,999 cents each plus 500 cents shipping). The browser deliberately
double-submits the same checkout key; independent API and SQL readback must prove
one order, matching totals, the leased identity and stock decremented once.
`X-Test-Identity` is a disposable test identity, **not production authentication**.

This first runtime is restricted to the two approved, same-repository synthetic
fixture PRs below. The resolver checks each changes only its exact boolean flag;
forks, other branches and additional code changes are rejected. The trusted
configuration records `executionScope: disposable-synthetic-ci` and the exact
fixture repository. Browser request routing and Chromium's sandbox do not amount
to complete hostile-code network isolation. This is not a production or arbitrary
untrusted-PR browser sandbox.

## Trust and candidate identity

- `pr-candidate.yml` runs on the actual PR test-merge SHA with read-only repository
  permission and no persisted checkout credential. Candidate tests run in a
  separate hosted runner from candidate compilation and artifact capture.
- Capture runs with isolated Python imports before compilation. CGO is disabled;
  candidate programs/tests are not run in the build job. Outputs and the Docker
  context use a fresh runner temporary directory, not candidate-controlled paths.
- `pr-acceptance.yml` runs from the default-branch revision on `workflow_run`.
  It never checks out or executes candidate scripts. The resolver independently
  compares current PR head/base, current test-merge ref, ordered merge parents,
  build run and captured checkout. Unresolved, stale or conflicting facts BLOCK.
  This first slice accepts only PRs targeting the default branch and requires
  that branch to remain at the trusted workflow revision. The late resolver
  repeats the check after evidence upload, so a changed default policy/base
  cannot be mislabeled as the currently trusted policy.
- The build workflow, capture script and Dockerfile blobs must exactly match the
  trusted default-branch revision. A PR cannot change these and have its own
  altered build metadata accepted. Artifact claims alone are not authority.
- GitHub archive bytes are checked against the API digest. The single fixed
  scratch image is inspected without extraction: tag, non-root user, entrypoint,
  environment, layer/config digests and executable bytes must match. Only then
  is it imported, and its Docker image-config identity is checked again.

## Evidence and advisory decision

The trusted policy requires the Web evidence, SQL readback, environment receipt,
screenshot and browser trace for this particular business case. Required files
are content-addressed, uploaded as a CI artifact, downloaded again, and compared
byte for byte before evaluation. Missing files remain missing; they are never
replaced with a PASS-shaped placeholder. The gate then checks a new SCM snapshot
and current policy/recipe bindings, not just the original submission.

The resulting `feedback.json` is structured for an Agent, but this initial public
workflow does **not** call a coding Agent or publish a required check. It states
`mode: advisory`, `scmEnforced: false`, `publication.state: NOT_PUBLISHED`.
An ALLOW in that file is a verification decision, not permission to merge.
The native `workflow_run` job check is on its workflow context and is not a
substitute for a check on the actual candidate integration SHA.

The reserved future exact-SHA check name is `delivery/acceptance`. Enforcing it
requires a separately trusted publishing identity (not merely a same-named job
from the common GitHub Actions App), checks-write permission for that publisher,
a ruleset requiring the correct source, protected policy inputs and SCM-enforced
freshness. New attempts must invalidate prior eligibility before work; stale or
out-of-order completions must not overwrite newer pending/BLOCK decisions.
No App credential, branch protection or repository permission is created here.

Both current repositories are personal repositories; this does not implement or
claim GitHub's organization-only native merge queue. A test merge is not an
atomic check-and-merge guarantee. No automatic merge or production deployment.

## Paired synthetic PR fixture

Two separately reviewable fixture branches can change only:

1. `poc/pr-gate-promotion`: `fixturePromotionEnabled = true` in
   `fixture_promotion.go`.
2. `poc/pr-gate-express`: `fixtureExpressEnabled = true` in
   `fixture_express.go`.

Either change alone leaves the business result correct. Their combination
activates the documented synthetic fault in `storedOrderTotal`: the persisted
order omits shipping while the UI/API quote includes it. The independent
acceptance policy is unchanged. The expected outcome is two single-candidate
passes and a combined-candidate business failure, not changed test expectations.
Creating or merging these branches is an external action performed separately.

After the combined failure, the exact bounded repair on the same express PR is
`fixtureInteractionFixed = true` in `fixture_express.go`, while keeping express
enabled. This selects correct persistence instead of suppressing an assertion.
The resolver accepts only those two exact express-file variants, not arbitrary
Agent-generated source. A general coding-Agent repair workflow requires a
stronger untrusted-code execution boundary and is not claimed by this fixture.

`composite-acceptance.yml` is a trusted manual experiment for those two PRs only.
It resolves their current heads, creates ordered merge commits in a temporary
local Git repository, compiles that exact integration SHA, and reuses the same
environment/evidence/gate path. It publishes no third branch or PR and does not
merge the real PRs. A public-source Git bundle preserves the local-only merge for
reproduction. A late API read rejects changed heads/base/policy. Its candidate
is labeled `controlled-composite`, `nativeMergeQueue: false`; the runtime subject
kind describes its combined source content, not GitHub queue authority.

## Current release prerequisite

`acceptance-release.json` is deliberately disabled until reviewed acceptance and
gate binaries are published and their exact SHA-256 values recorded. A disabled
release fails the orchestration; it is not a green implementation stub. This
document and unit tests are not evidence that a hosted PR run or model Agent ran.
