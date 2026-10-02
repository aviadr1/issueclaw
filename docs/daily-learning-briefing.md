# Daily learning briefings

A knowledge repository can run the reusable `daily-learning-briefing.yml` workflow
with its own source configuration, schedule and existing reporting secrets. The
workflow collects GitHub/Linear-mirror evidence, generates one concrete brief with
named authors and reviewers, validates coverage, validates a per-PR JSON coverage audit, preserves artifacts, and posts a
channel message plus the complete inventory as replies in the same Slack thread.

## Caller configuration

The JSON config supplies `repos` (owner/repo names), `people` (verified login/name
mapping), `teams` (relevant Linear team identifiers), `timezone` (IANA), `hour`,
`weekdays` (optional Python weekday numbers, Monday=0; all days by default),
`channel` (Slack channel ID), `mirror_repository`, and `state_branch`. Keep company
configuration in the caller. Pin both the reusable workflow and `tooling-ref` to
the same reviewed issueclaw commit. Required secrets are `REPOS_READ_TOKEN`,
`ANTHROPIC_API_KEY`, and `SLACK_BOT_TOKEN`. The caller's `GITHUB_TOKEN` needs
`contents: write` and `actions: read` for checkpoints and recovery artifacts.
The existing Slack bot needs membership and posting permission in the destination.

Scheduled runs use the most recent configured local cutoff even if GitHub starts
late. With `weekdays: [0, 1, 2, 3, 4]`, Monday covers Friday 08:00 through Monday
08:00; Tuesday through Friday cover the previous morning through that morning.
The first Monday includes Friday’s workday and the weekend even without an earlier
checkpoint. DST changes preserve local boundaries without gaps (a fall-back Monday
covers 73 actual hours). Generation starts at the scheduled time; Slack arrives after
collection and generation, and GitHub can delay scheduled starts. It is not an
exact-minute delivery guarantee. Review evidence is freshly collected for 30 days;
open drafts and reviewers are collected even when their last update is older.
Current metadata is clearly separate from cutoff-bounded merge/discussion evidence.

The weekly collector remains unchanged by default. Daily collection opts into
all open PRs and includes current head-SHA checks and requested reviewers. A query
reaching GitHub's 1,000-result search limit blocks publication rather than silently
omitting PRs. CI collection pages check suites on the current default-branch commit; per-PR
check rollups identify checks on the current PR head. Discussions use paginated
GraphQL comments, reviews and inline threads, avoiding thousands of REST requests
when rebuilding the 30-day history. Timezone data ships with the package for Windows.

## Preview and recovery

`workflow_dispatch` should default to `post-to-slack: false`; it preserves the same
sources, coverage and message artifact without writing a checkpoint or contacting
Slack. An optional aware ISO cutoff previews a prior window; open PR/reviewer/CI
states remain current, not reconstructed historical snapshots.

Before posting, a checkpoint on the caller's dedicated state branch records the
prepared artifact run ID and content digest. Every message has a stable metadata
key and a durable intent/receipt. Only a fully posted thread advances last_cutoff.
The next run resumes a pending thread from that exact artifact, without regenerating
its messages. A later run covers any missed days from the last successful cutoff.
A successful cutoff is never reposted, even if a workflow is rerun.

If a network loss occurs after Slack may have accepted a message, recovery attempts
to find its metadata in Slack history/replies. This requires history permissions;
some bot installations cannot read public-channel replies. If recovery is unavailable
or ambiguous, the process stops rather than blindly duplicating a message. An
operator must inspect the thread and repair that intent on the state branch with the
verified timestamp, or clear it only after verifying no message was accepted. An
explicit Slack rejection is safe to retry. Expired/unavailable artifacts block
recovery; artifact retention is 45 days. GitHub workflow failures remain visible in
Actions. No extra failure message is posted to the team channel.

The generator is given no Slack token or write credentials. It must not change
issues, deployments or the source mirror. Evidence and generated messages are
uploaded even on failure when available. Raw evidence stays in artifacts rather
than being committed into the mirror or a new Linear report document every day.
