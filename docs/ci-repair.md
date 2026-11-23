# Scheduled CI repair

The consumer repository owns the clock and company policy. This package supplies
discovery, the official Claude Action worker, private checkpoints, a separate draft
PR publisher, verification receipts and briefing integration. Product repositories
own their nightly policies. No process merges PRs or marks them ready automatically.

```
consumer's 06:00 schedule (IANA timezone)
  -> load policies at each repository's default head
  -> collect historical failed runs and attempt-specific jobs
  -> persist assignments on ci-repair-state
  -> one isolated official-Action session per assignment (4 concurrent)
       all failures + peer owners + this agent's assignment
       subscription OAuth + Sonnet + Opus advisor + LangSmith
       periodic private transcript/patch checkpoints
  -> fresh publisher job: draft PR in assigned repository
  -> dispatch allowlisted candidate CI in that repository
  -> morning briefing refreshes candidate SHA, actual jobs, artifacts and traces
```

## Authentication and costs

Only `CLAUDE_CODE_OAUTH_TOKEN` is supplied to Claude. Missing subscription credentials
fail the job; there is no API-key fallback or dollar cap. GitHub's 95-minute agent
step timeout preserves time for cleanup. Four is a concurrency setting, not a daily
incident allowance. Usage and API-equivalent estimated cost are reported separately
from subscription billing; incomplete results mean unknown usage, never zero.

`REPOS_READ_TOKEN` is the consumer's existing cross-repository token. Despite its
name, publishing requires contents/PR write and Actions dispatch permissions on the
product repositories. It is available only to checkout/evidence preparation and
the separate publisher. Claude receives the consumer's read-only `github.token`.
No product cloud, deployment or device-farm secrets are passed to the agent.

The image is built from `docker/ci-repair/Dockerfile` and passed by immutable digest.
It contains Python 3.14, Node 24, Claude CLI 2.1.308, gh, Bun, uv, Git, jq, ripgrep
and compiler tools. Repository-specific packages/services remain the repository's
responsibility. Native mobile builds and authenticated external integration tests
run in product CI, not inside this generic container.

## Repository policy

Consumer configuration maps repository names to `policy_path`, normally
`.github/ci-repair.json`. Missing/unreadable policies are explicit discovery errors.
Policies are loaded from an immutable default-head revision and copied into the
assignment, so candidate changes cannot redefine their own verification contract.
Supported fields:

```json
{
  "branches": ["main"],
  "events": ["schedule", "workflow_dispatch", "push"],
  "exclude_workflows": [],
  "instructions": "Describe relevant environments, child runs, setup and limits.",
  "verification": {
    ".github/workflows/tests.yml": {
      "workflow": "tests.yml",
      "inputs": {"coverage": "true"}
    }
  }
}
```

All failed workflows in the selected branches/events are discoverable, including
nightly tests, e2e, stress, build and security checks. Repair workflows are excluded
to prevent recursion. Policies need not enumerate every workflow to detect it.
Automatic verification is opt-in per source workflow. It dispatches the repair
branch, binds the resulting run to the immutable candidate SHA, and requires every
non-skipped source job to pass. Workflow edits, missing/ambiguous runs, changed PR
heads and absent required jobs remain unverified. This comparison does not replace
a suite's own test-count/build-provenance verdict. Only add a verifier when that
workflow already enforces those invariants. Never map a dispatch wrapper to itself.

Unknown/manual stress inputs, shared-cluster operations and tests of deployed main
must remain manual-validation-required until an adapter can faithfully preserve
their workload and candidate identity. The draft and session are still reported.
The 06:00 snapshot cannot know failures that finish later. The morning briefing's
existing CI collector continues to surface later failures; they are not silently
claimed as repaired by the earlier batch.

## Coordination and durable reporting

Each assignment sees the complete incident roster. If the cause belongs to another
assigned failure, the agent emits `depends_on` with that owner's incident ID and
stops duplicate work. The publisher then emits `deferred` without publishing its
patch. A dependency declaration never changes a test result to passed.

Receipts live on a separate data branch, not the consumer's default source branch.
Assignments are saved before execution. The briefing can therefore report a failed
image build, cancelled job, no-PR attempt, absent receipt or expired checkpoint.
Repeat occurrences group by repository, branch, workflow, run title and failed jobs;
this is an ownership key, not a claim that two stack traces have the same cause.
Existing open repair PRs prevent duplicate publishing. Previous unresolved records
survive changes to main and the initial seven-day discovery window.

Set `ci_repair_repository` in briefing configuration to read these receipts. The
briefing rechecks PR heads and actual candidate runs at report time. It links the
source failure, draft PR, verification evidence, LangSmith traces and session run.
It must highlight no-PR and still-failing attempts, including missing evidence.

## Human handoff

Private artifacts last 30 days. The independent watcher copies the flushed JSONL
every minute and uploads uniquely named snapshots: replacing a checkpoint cannot
delete the last good copy during cancellation. It records whether assistant messages
are present. A hard runner loss can still lose the most recent unflushed turn; a
prompt-only checkpoint is identified as such. No credential/config directory is
uploaded. Raw conversations and patches must never use public S3 media hosting.

The Windows launcher is extracted from the compatibility experiment, with generic
repository/workflow allowlists. Install from reviewed code:

```powershell
./docker/ci-repair/install-handoff.ps1 -PythonPath <python3.14.exe> `
  -ClaudePath <claude.exe> -PolicyPath <handoff-policy.json> `
  -InstallDirectory <launcher-folder> -StorageDirectory <checkout-folder>
```

The policy supplies `coordinator_repositories`, `target_repositories` and `workflows`.
`issueclaw-ci://resume/OWNER/COORDINATOR/RUN/ARTIFACT` restores the saved transcript
and patch to an isolated checkout and opens Desktop. Repeated clicks preserve edits.
`issueclaw-ci://cloud/...` launches native cloud creation in a real terminal using an
excerpt of the conversation. It is a **new cloud session**, not a transcript import;
its URL appears in that terminal. Alternatively use Desktop's **Open in → Cloud**.
Neither option promises unattended cloud creation on ephemeral CI runners.

`src/issueclaw/ci-handoff.html` is a static landing page with these two buttons. Its
fragment is `#OWNER/COORDINATOR/RUN/ARTIFACT`; no private transcript is served publicly.
It can be hosted using the existing `s3_hosting.put` primitive. A launcher install,
GitHub access and Claude subscription login are required on the human's computer.

## Rollout and review

Merge reviewed repo policies first, then pin this runtime in the consumer. Run
discovery with `dry-run: true`; inspect every assignment and collection error before
enabling the scheduled caller. Preview mode writes only an artifact and launches no
Claude sessions. The schedule only becomes active when its caller reaches the default
branch. PRs for this feature are not permission to merge themselves.
