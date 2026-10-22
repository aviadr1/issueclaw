# Daily learning briefings

A knowledge repository can run the reusable `daily-learning-briefing.yml` workflow
with its own source configuration, schedule and existing reporting secrets. The
workflow collects GitHub/Linear-mirror evidence, generates one concrete brief with
named authors and reviewers, validates coverage, validates per-PR coverage and review-learning JSON audits, preserves artifacts, and posts a
channel message plus the complete inventory as replies, or one TLDR linking to a full Slack Canvas.

## Caller configuration

Team configs can set `"defaults": "briefing-defaults.json"` to read one shared
JSON file relative to the team config, independent of the working directory.
Explicit team values override defaults. Object fields such as `people` and
`learning_videos` merge by key; arrays and scalars replace the shared value,
including empty arrays and `false`. Defaults cannot reference another defaults
file. Existing standalone configurations still work.

Keep company defaults (people, timezone, hour, weekdays, Canvas presentation and
video options) in the knowledge repository. Each team supplies its `repos`,
`teams`, `channel`, `state_branch`, `title` and optionally `audience`,
`context_terms` and `instructions`. `context_terms` are literal, case-insensitive
keywords added to repository names when selecting related Linear projects and
documents. They do not expand the GitHub repository inventory. `instructions`
adds team-specific editorial guidance to the shared report prompt.
`what_changed_order_last` optionally places efforts led by those verified names
after other efforts. Without a title or audience, the report uses neutral
engineering wording; the tool has no backend-specific context keywords.

Preparation saves the resolved configuration as `briefing-config.json` in the
artifact. Subsequent stages and evidence-reuse previews retain those settings,
even if shared defaults change. Reuse and repair reject a different repository
set, Linear team set or Slack destination. Older artifacts without this snapshot
remain recoverable using the supplied configuration. Report generation reads the
title, audience and editorial settings from `window.json`; lesson research receives
the same title and audience in `topic.json`.

Keep one scheduled workflow caller per team, each using the same pinned reusable
workflow and tooling revision. Give each team its own publication concurrency
group and state branch. GitHub's cron declaration remains in the caller YAML and
must agree with the configured timezone, hour and weekdays. Video kit references,
runner selection and secrets also remain workflow inputs; JSON defaults cover
the report settings, not GitHub Actions syntax.

The JSON config supplies `repos` (owner/repo names), `people` (verified login/name
mapping, matched case-insensitively), `teams` (relevant Linear team identifiers), `timezone` (IANA), `hour`,
`weekdays` (optional Python weekday numbers, Monday=0; all days by default),
`channel` (Slack channel ID), `mirror_repository`, and `state_branch`. Set
`delivery_format: "canvas"` for a full report plus complete PR/ticket inventory in
a channel-tabbed Canvas and one short TLDR message. Legacy thread delivery remains
the default. Set `canvas_inventory: "merged"` to append only the window's merged
PRs. Open/draft work is curated in the narrative (at most eight linked PRs), with
named involvement and concrete next decisions; the full open/draft and ticket
inventories remain private evidence artifacts and still require complete audits.
Set `canvas_inventory: "none"` to omit both inventory appendices while preserving
the full source inventories and coverage audits in artifacts. The same eight-PR
open/draft curation limit applies.
The generator uses Claude Sonnet 5.5 (`claude-sonnet-5-5`) for drafting and revisions;
both reporting and video research use an Opus 5.5 advisor and Haiku subagents.
Video research uses Sonnet 5.5 at high effort (see below).
The full Canvas report has no 550-word limit; only the TLDR is capped
at 180 words in paragraph mode. Set `slack_summary_format: "titles"` for a contents
message: one bullet per narrative topic heading, in Canvas order with lead names,
plus a playful invitation of at most 25 words. Generic What changed/Learning labels
are omitted when they have child topics. Waiting on people, Active work and CI
require concrete child headings, shown as nested Slack bullets: people and their
next actions/work, or repositories and observed check statuses. Learning titles
describe the practical action or capability without a fixed slogan. Inventory appendices and headings inside
code examples are excluded. Bullets are assembled from the report rather than
rewritten by the model; their total is bounded by Slack message size rather than
the paragraph word cap. Alternatively, set `slack_summary_format: "actions"` for
**Needs attention** followed by **For awareness**, with an extra blank line between
the sections and the confirmed Canvas link at the bottom. The generator writes
`slack-summary.json` with `needs_attention` (0–8) and `for_awareness` (0–3) arrays of
single-line Markdown bullet bodies. The rendered summary is limited to 300 words;
empty arrays produce explicit quiet-day messages. Reviews and CI retain direct
source links and next actions; awareness is curated rather than a contents list.
No learning rules or review-video teasers are appended to this initial message;
the existing follow-up learning/video post remains separate. Canvas Learning and
review walkthroughs remain intact, including lesson replacement and video embeds.
The actions-mode Canvas starts with a TLDR and Needs attention, then What changed,
In progress, a separate Review walkthrough when available, and short Learning
topics (roughly 100–150 words each). Keep the detailed narrative and the caller's
status/adoption guidance; this is not a second Slack-sized summary.
The generator injects a complete fictional worked example (structured Slack input,
rendered message, and Canvas) into every actions-mode drafting and repair prompt.
It demonstrates the desired output; its people, dates and links are not evidence.

The 200–250-word Slack target, 900–1,500-word Canvas target and 100–150-word lesson
target are editorial guidance, not minimum lengths or fatal validation thresholds.
Canvas section order is also prompt guidance. The Slack JSON shape, eight/three
bullet ceilings and 300-word maximum are validated. Invalid JSON, missing files,
wrong Slack sections and excess bullets/words enter the existing repair loop:
the agent receives the exact error and has up to two revisions using the same
evidence. If still invalid, generation fails and publication is skipped; the
workflow's always-run artifact upload preserves the draft, evidence and errors
for inspection/revision. It does not truncate bullets or publish an invalid draft.
This repair loop handles draft-validation errors; a failed model process or
workflow timeout can still stop the run. The final validation after optional
video/lesson replacement is a publication gate, not another draft-repair loop.

In titles mode, the previous successful invitation is checkpointed, and
repeating it blocks validation for a focused revision. Pending artifacts retain
their original message and invitation. Keep company
configuration in the caller. Pin both the reusable workflow and `tooling-ref` to
the same reviewed issueclaw commit. Required secrets are `REPOS_READ_TOKEN`,
`ANTHROPIC_API_KEY`, and `SLACK_BOT_TOKEN`. The caller's `GITHUB_TOKEN` needs
`contents: write` and `actions: read` for checkpoints and recovery artifacts.
The existing Slack bot needs membership and posting permission in the destination.
Canvas delivery also needs `canvases:write` and `files:read`, as design reporting does.

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

To replace a morning briefing with an early manual publication, pass `run-early:
true` to the reusable workflow and add that morning's local ISO date to the caller
config's `skip_scheduled_dates`, for example `["2026-10-06"]`. The planning job skips
generation and publication only for a scheduled run on that exact local date;
manual runs and subsequent dates remain enabled. Early mode ends coverage at the
planning job's actual UTC time, never at a future morning. It cannot be combined
with historical cutoff/evidence reuse. Coverage starts at the last successfully
published cutoff, and the next normal briefing starts at the early report's cutoff.
The exclusion does not change delivery checkpoints; verify early publication
succeeded before relying on the replaced morning's skip.

The weekly collector remains unchanged by default. Daily collection opts into
all open PRs and includes current head-SHA checks and requested reviewers. A query
reaching GitHub's 1,000-result search limit blocks publication rather than silently
omitting PRs. CI collection pins the default-branch commit, pages workflow runs
and attempt-specific jobs, and reads workflow triggers from that same commit.
It keeps failed and manual runs separate: a later success does not prove the same
tests ran. Skipped runs stay in audit evidence, while the report focuses on
executed jobs and actionable failures. A successful planner with skipped tests is
not test success; PR/manual-only triggers explain absent main-push checks without
inventing either a failure or a pass. Incomplete pagination or a moving branch
blocks publication. Per-PR check rollups identify checks on the current PR head. Discussions use paginated
GraphQL comments, reviews and inline threads, avoiding thousands of REST requests
when rebuilding the 30-day history. Timezone data ships with the package for Windows.

The reader-facing CI section is an action summary: one "All good — no CI action
needed" heading when supported, or a short item per unresolved problem with the
next action and an evidence link. Routine skips, expected PR/manual-only checks,
ordinary in-progress runs and proven recoveries stay out of that section. Detailed
coverage explanations stay in the audit. A missing required gate is an action to
verify, never grounds for an unsupported all-good claim.

## Preview and recovery

`workflow_dispatch` should default to `post-to-slack: false`; it preserves the same
sources, coverage and message artifact without writing a checkpoint or contacting
Slack. An optional aware ISO cutoff previews a prior window; open PR/reviewer/CI
states remain current, not reconstructed historical snapshots.

To recover a run that failed before producing a report, callers can explicitly
enable publication with the original timezone-aware `cutoff` and `post-to-slack:
true`. Do not pass `run-early` or reuse preview evidence. This recollects evidence
for the original window, starting at the last successful delivery. A cutoff without
a timezone or in the future is rejected; an already delivered cutoff is a no-op.
Use the same publication concurrency group as scheduled runs. A normal rerun on
a later day without an explicit cutoff would instead select that day's window.

Read-only GitHub evidence requests retry truncated/invalid JSON, timeouts,
connection failures, HTTP 5xx, and rate limits up to four total attempts. Backoff
is 2, 4, and 8 seconds plus jitter (30 seconds plus jitter for rate limits), with
a 180-second timeout per attempt. Authentication, permission, and other permanent
errors fail immediately. Exhausted requests are recorded in `evidence/manifest.json`
as incomplete sources, keeping publication blocked and preserving diagnostics.

Before posting, a checkpoint on the caller's dedicated state branch records the
prepared artifact run ID and content digest. Every message has a stable metadata
key and a durable intent/receipt. Only a fully posted thread advances last_cutoff.
The next run resumes a pending thread from that exact artifact, without regenerating
its messages. A later run covers any missed days from the last successful cutoff.
A successful cutoff is never reposted, even if a workflow is rerun. Receipts for
older completed cutoffs are pruned when the next thread starts, keeping the
checkpoint small. GitHub collection errors preserve the CLI diagnostic in the
manifest, so quota and permission failures are distinguishable.

If a network loss occurs after Slack may have accepted a message, recovery attempts
to find its metadata in Slack history/replies. This requires history permissions;
some bot installations cannot read public-channel replies. If recovery is unavailable
or ambiguous, the process stops rather than blindly duplicating a message. An
operator must inspect the thread and repair that intent on the state branch with the
verified timestamp, or clear it only after verifying no message was accepted. An
explicit Slack rejection is safe to retry. Expired/unavailable artifacts block
recovery; artifact retention is 90 days. GitHub workflow failures remain visible in
Actions. No extra failure message is posted to the team channel.

The generator is given no Slack token or write credentials. It must not change
issues, deployments or the source mirror. Evidence and generated messages are
uploaded even on failure when available. Raw evidence stays in artifacts rather
than being committed into the mirror or a new Linear report document every day.

## Review evidence checks

Preparation writes `review-learning-evidence.json` with exact 30-day formal-review
and inline-comment totals and usable dated bodies. Current review snapshots and
bodies edited after cutoff are excluded from the learning corpus. The generator
writes `review-learning.json`, recording inspected PRs and the comment URLs behind
any repeated problem. Validation rejects incorrect totals, fabricated citations,
patterns supported by only one PR, and missing top-level citations. Empty patterns
need an explicit reason. These checks establish provenance; they cannot prove that
a generated interpretation is sound. The prompt requires plain before/after language,
explicit roles for people and observed CI check names instead of blanket health claims.

Generation validates the draft and permits at most two focused revisions against
the same prepared sources. Evidence JSON and inventory replies are hashed before
model calls; changing either blocks the run. Revisions do not recollect sources.
Pending publication artifacts are never rewritten. An isolated preview may supply
`evidence-run-id` to download an earlier artifact from the same caller repository
and repair its invalid draft. Evidence reuse is rejected for publishing runs.

## Canvas delivery and recovery

Canvas mode reuses `issueclaw.slack_canvas`, the publisher used by design weekly
reports. Validation assembles the full narrative and the configured inventory appendix
into `canvas.md`; complete source inventories remain in the artifact. Its title and content are included in the pending artifact digest.
The shared Canvas publisher can checkpoint each creation intent, ID and confirmed
URL through a callback; daily reporting stores these on its dedicated state branch.
The confirmed link is appended to the TLDR in memory, and only that message is sent.
A failure fetching the permalink retries with the known canvas ID; an uncertain
creation outcome stops for inspection. Record the recovered ID and clear the canvas
receipt's pending marker only after checking Slack. A cutoff completes only when
both the Canvas and its TLDR are delivered. New cutoffs replace the old receipt;
previous reports remain accessible in Slack. Previews create neither Canvas nor
Slack messages, and retain the assembled Markdown as an artifact.

An operator can pass `revision-notes` to revise an existing preview even when its
structural checks pass. Notes are passed through a quoted environment variable,
not interpolated into shell code. Source/inventory immutability and audit checks
still apply. A pending publication always skips the generator, including these
notes. Callers should expose notes as a preview-only input; scheduled runs use the
normal prompt. The revised artifact can then be reserved for exact publication.

## Waiting attribution

Daily collection retains a complete current discussion snapshot, paginated commit
identities/dates and human review-request/readiness/reopen/force-push events for
open PRs. This current activity is separate from the cutoff-bounded learning corpus.
Each PR record and inventory row includes a `waiting` baseline with named people,
reason, evidence, last movement and an as-of timestamp. Four elapsed days (96 hours)
without substantive movement returns the next action to the author, overriding
pending review requests. Otherwise feedback without a later author commit/comment
waits on the author; pending review requests wait on named reviewers. Author
follow-up clears that feedback wait. Recent drafts without a review dependency
remain active work. CI/label churn and bot comments never reset inactivity.

The generator must also read reviews posted as ordinary issue comments, cite them
and compare later author activity: formal review requests can remain even after
such a review. Teammate changes are credited but do not become author follow-up.
Missing snapshots or unattributed possible follow-up produce an unverified person,
not a claim that the author has done nothing. Head changes during paginated activity
collection block publication for retry. Retained commit timestamps are not a complete
push log, and deleted comments or commits removed from the branch are unavailable.
Waiting items remain curated; this does not add the old open backlog to the Canvas.

## Learning lessons and videos

The daily briefing can turn each lesson it teaches into a short lesson with a video. The
caller opts in by passing `learning-videos-repository` and a reviewed
`learning-videos-ref` to the reusable workflow, plus `learning_videos.max` (default 1) in its config. Optional
`learning_videos.instructions` holds the caller's own guidance for the lesson and
its video (style, sound, tone); it is appended to the agent's prompt.
For readable line-level diffs, use `learning_videos.instructions_file` instead,
for example `"instructions_file": "prompts/learning-video.md"`. The UTF-8 file is
resolved relative to the JSON file declaring it (including a shared defaults file).
Its text is loaded verbatim, without trimming, newline conversion or templating.
Declare only one of `instructions` and `instructions_file` in each config; a team's
inline or file-based value overrides the shared default. Resolved configuration
snapshots contain the text, so frozen-evidence recovery needs no original prompt file.
The kit is a repository following promo-videos' `src/learnings/AGENT.md`, such
as `aviadr1/promo-videos`. `REPOS_READ_TOKEN` must read it, or the caller supplies
`VIDEOS_READ_TOKEN`.

The briefing's `## Learning` section holds one or two `###` lessons from recent
work, of any kind worth sharing. Examples: a surprising root cause, a distributed
failure mode, a concurrency guard, a new primitive or system, an algorithm or
heuristic, a measured performance or scaling change, a CI fix, a restructuring,
a convention turned into a check, a testing or observability technique. A problem
repeated across reviews is one strong signal among these, not the only one. The
prompt lists kinds to skip (releases, bump PRs, plumbing, series follow-ups) and
how to rank candidates; this list came from sampling 65 merged PRs over 40 days.
Published lessons are remembered on the state branch (`taught_lessons`, the
last 60) and passed to the next briefing as `window.json` `previous_lessons`, so
it doesn't teach the same lesson twice.

After the briefing is drafted, the `learn` command gives each of those lessons (up
to the limit) to a separate agent: Claude Sonnet 5.5 (`claude-sonnet-5-5`) at high
effort, with an Opus 5.5 advisor, Haiku subagents and a 60-minute cap. The agent
gets the briefing's draft (`draft.md`) and any review comments it cites
(`comments.json`), digs into the PRs and code with read-only GitHub access, then
writes `learnings/<n>/learning.md` (three or four short paragraphs, e.g. Problem /
Root cause / Fix / Rule, or Problem / Idea / How it works / Takeaway) and
`learning.json` (slug, title, rule, sources),
and renders `video.mp4` with the kit. Its output is used as written. A lesson is
dropped only if the agent wrote no text, title or rule, and it is published without
a video if no video was made. If the agent leaves before its render finishes, the
kit's `render-learning.sh` is run to finish it. Nothing here can block the briefing:
agent and render failures are recorded in `error.txt` or `render.log`, and the
briefing publishes without the lesson. `learnings.json` records the lessons; a
rerun, revision or evidence-reuse preview reuses it instead of running the researcher again.
Previews keep each video in the artifact for review.

The CLI runs up to two video tasks concurrently (`learning_videos.workers`,
default 2; set 1 for a smaller runner). Each concurrent task gets a separate
copy of the kit, including its registry, assets and dependency caches. Results
keep their report order even when tasks finish out of order. Source is preserved
on failure and by the workflow's interruption cleanup. `timings.json` records
each task's wall time; `render-timings/` contains the kit's per-stage measurements.
The reusable workflow sets `LEARNING_VIDEO_WEBM=0` because delivery consumes MP4.
Standalone kit exports still include WebM by default.

Use a kit supporting `render-learning.sh --chapter <id>` and
`learning-qa.mjs --chapter <id>`. The researcher corrects muted chapter previews
before the final export. These retain absolute frames and neighboring footage;
they are not cached independently or spliced together. Earlier timing/state
changes require inspecting affected later chapters. A complete final render,
full-sequence QA and the existing publication validator remain required.
Chapter previews carry `preview.json` and cannot pass final-video validation.

The kit owns the craft of the video. The agent writes the lesson as data
(`src/learnings/<slug>/lesson.ts`: a cast of objects on a grid and chapters of
captioned beats), and the kit's lesson engine times every beat from its caption's
reading budget and its actions, eases every movement, keeps the picture on screen
between chapters, and writes the sound cues, `storyboard.json` and per-scene QA
stills. Its check refuses to render overlapping or off-stage objects, captions
longer than two lines, and beats where nothing visible changes for about four
seconds. Its QA script adds `filmstrip/` (the whole video at two frames a second,
timestamped) and `motion.txt` (holds and abrupt single-frame changes per beat),
which the agent and its advisor read before the publisher's check runs. Hand
animation (frame numbers, pixel positions, cues) is no longer part of the
agent's job; the prompt covers research, the story and the review of what was
rendered.

In the Canvas and its Slack topic list, each lesson replaces the learning the
briefing wrote, in the same place: the section the lesson came from takes the
lesson's title at the same level, or, if it is the "Learning" heading itself, the
lesson goes under it. A video
placeholder is filled at publication. A learning the briefing never wrote up is not
added. `report.md` keeps the briefing's text, so the review-citation audit is
unchanged. The lessons and the videos' hashes are part of the pending digest. At publication, each
video is uploaded once and embedded in the Canvas through its Slack file link,
and the TLDR gains a **Learning:** line with each lesson's rule. The formatted
briefing post carries the Canvas file as its card. A separate channel post follows
with one line summarizing the lesson and those same uploaded video file IDs.
The Canvas references that shared video, so channel members can open it there too.
Both posts and their attachments are verified before the coverage cutoff advances.
A failed attachment retries against the checkpointed message without posting another
or uploading another copy. Uploading needs the bot's `files:write` scope. If Slack refuses an upload,
the refusal is recorded for that cutoff: the Canvas has no embed (it stays identical
on retry) and the TLDR is posted as plain text. Canvas embedding of video files
follows Slack's file-embed syntax; if a workspace shows a link rather than a player,
the video is still in its separate Slack post.

Messages use Slack's `markdown_text` input so topic bullets and their nested items
become native lists. Video attachment preserves the returned rich-text blocks;
updating only `text` would discard their formatting.
The confirmed Canvas link is the first line, labeled **Your daily briefing canvas**.
The title and bullets follow it; the changing invitation stays at the bottom.

For a clip recovered after a briefing completed, the reusable
`attach-briefing-video.yml` workflow accepts the original artifact run and an
already uploaded Slack file ID. It calls `daily_briefing attach-video --file-id F…`
with the caller's bot credentials. Only the latest completed cutoff can be repaired,
and a pending publication blocks the repair. It preserves the message text and
coverage cutoff and records the attachment separately. The caller must serialize
this workflow with publication. A separately repaired Canvas should reference
the same file ID.

The recovery workflow's optional `format-message` input reparses the original TLDR
as Markdown and verifies Slack returns native lists. It reconstructs the Markdown
from the original artifact and confirmed Canvas URL, then requires the current
message text to match exactly before changing presentation. Its file attachment
and coverage cutoff stay in place.

The optional `split-delivery` recovery input restores the Canvas card on the
original briefing and posts the recovered video with its lesson rule in a separate
channel message. Both message timestamps are checkpointed, so retrying the repair
does not duplicate the follow-up. Formatting and split repairs cannot be combined.


## Readable videos, selection audits and review walkthroughs

The Sonnet 5.5 report runner now uses `--advisor claude-opus-5-5` and
`CLAUDE_CODE_SUBAGENT_MODEL=haiku`. The Sonnet 5.5 video researcher also uses
`--advisor claude-opus-5-5`, high effort, and Haiku for bounded source extraction and
a cold-viewer test: a Haiku subagent sees only the caption script and must explain
the lesson back before the video is built. Candidate comparisons and advisor
conclusions are concise decision records; they do not claim to expose hidden
model reasoning. The generator writes `selection-audit.json` comparing reuse,
evidence, tradeoffs and why each candidate won or lost across the merged work.

The reusable workflow accepts `generation-runner` (default `ubuntu-latest`) so
consumers can select a larger existing runner for research/rendering. Planning and
publishing keep standard runners. Runner traces include CPU count and runner name.

Optional caller settings under `learning_videos`:

- `playback_speed: 1` keeps animation, transitions and audio at their native speed.
  Add stable caption holds in the composition, then regenerate soundtrack cues
  without changing musical tempo. Do not stretch the finished video or audio.
  Lessons target 60–90 seconds without padding shorter explanations. Legacy
  caller-selected retiming remains available, but is not the recommended pacing.
- `review: true` adds one substantial open PR walkthrough without consuming `max`
  lesson slots. The report compares eligible PRs and writes `review-selection.json`.
  Selection requires the collected open state, reviewer dependency and head SHA;
  approved, draft and author-blocked work are excluded. No suitable candidate gets
  an explicit reason. Review videos target 2–3 minutes, inspect source and tests at
  the recorded head, and explain purpose, mechanism, review difficulty and specific
  questions with evidence and unknowns. Previously covered PR/heads are remembered.
- `quality_checks: true` requires research, questions, a standalone narrative with
  advisor critique, per-caption reading windows, scene QA stills and a cold-viewer
  content audit. A caption remains legible while meaningful diagram actions continue;
  the gate no longer requires all reading time after the entire scene stops moving.
  Persistent chrome does not repeatedly consume caption time. The legacy whole-scene
  format is still readable. Each caption gets at least three seconds or words / 3 +
  one second, with two extra seconds for code/diagram interpretation.
  The same CLI/publisher check runs ffmpeg freeze detection and preserves motion.json
  and motion.log. Near-identical frames for at least 4.5 seconds reject the video,
  including frozen tails. This is a heuristic: QA must reject decorative motion and
  captions that fail to explain the context, problem, change, engineering tradeoff
  and reusable lesson. A failed gate retains text and failed media in the artifact,
  but does not upload that clip to Slack.
- `attach_to_prs: true` posts one comment per video/source PR with the video
  uploaded and embedded as a native player (`gh pr comment --attach`, GitHub CLI
  2.99+; the publish job installs a pinned, checksum-verified release when the
  runner's is older), plus links to the hosted review page, the team Slack post
  and the generation run. If the upload fails, the comment links the hosted video
  (or the Slack post) instead and the step fails visibly; a rerun finds the
  comment by its marker and does not post again. Review videos attach only to
  their selected PR and refuse a changed head or closed/draft state. Lesson videos
  attach to the PR URLs cited as sources in configured repos.

Comment publishing happens only after Slack publication; previews never comment.
An optional `PR_COMMENT_TOKEN` needs write access on the source repositories:
GitHub requires it to upload media, and only accepts OAuth or classic personal
access tokens for uploads (fine-grained tokens are not documented to work). It falls back to `REPOS_READ_TOKEN`, which must have that write scope
for this feature despite its historical name. Generation still receives only the
existing read token. Missing access fails the attachment step visibly and leaves
per-target receipts, while the already delivered Slack briefing is preserved.
Rerun the publish job to recover: comments are found by authenticated author and
video-hash marker, so even an accepted write with a lost response is not duplicated.

### Hosting review media by URL

Pass `ci-artifact-role-arn`, `ci-artifact-bucket`, `ci-artifact-prefix` and
`ci-artifact-public-base` (and `ci-artifact-region`, default `us-east-1`) to host
each video's review media in a public-by-URL CI bucket with no listing. A
separate `host-media` job, on the caller's `main` only, downloads the run artifact
as data, assumes the role over OIDC and uploads an allowlist per published video:
the MP4, its filmstrip, QA stills, motion report and lesson text, plus an index
page. The agent's transcript, prompts, research, evidence and captured source are
never uploaded; they stay in the private run artifact. Objects go under
`<prefix>/daily-learning-briefing/<run>/<attempt>/<uuid>/`, so a URL is hard to
guess but anyone holding it can share it. Only `host-media` gets `id-token: write`;
the job that runs the lesson agent never can mint the credentials. The caller must
grant `id-token: write` in its own permissions. Hosting is optional and fail-soft:
publication proceeds if it fails or is skipped, and previews from other branches
skip it. `hosted-media.json` records the URLs that PR comments link.

Start artifact review at `TRACE-INDEX.md`, which links each completed or failed video
attempt to its questions, evidence, QA, timing and source.
The `daily-learning-briefing` artifact retains selection audits, frozen evidence,
exact model prompts and requested models, structured tool transcripts, runner and
pinned tooling/kit versions, source/captured assets, questions, research, storyboard,
QA stills, pacing measurements, MP4s and outcomes for 90 days. Source is copied even
when an agent fails. `daily-learning-briefing-delivery` separately retains publication
state and PR-comment receipts after publication, including partial failures. Neither
artifact serializes credential environments. The rendered video's SHA-256 links its
pacing record to the PR-comment receipt. Source inspection/QA transcripts may contain
private repository material; artifacts stay in the caller repository.

Evidence-reuse previews archive earlier learning outputs under
`previous-videos/<source-run>/` before generating replacements. Frozen evidence
stays unchanged; the previous video manifest cannot silently skip a rewrite.


### Live video sessions

Video generation has separate research and visual-authoring sessions, using the
same Sonnet/Opus models and a shared one-hour limit. Research settles pinned
claims, captions and the personalized card in `script.json`, with a caption cold
read and factual advisor preflight. Authoring starts with a fresh context and
reads that handoff. The video kit generates composition/registry/cue plumbing and
joins captions to actions by beat ID. Final QA generates questions.md and
narrative.md from the compiled storyboard, so corrections cannot leave those
derived records stale. Research and visual-review notes remain authored evidence.
Actual-frame advisor review and all final
filmstrip, reading, motion, join, audio and publisher checks remain required.

While generation runs, `learning-progress-<attempt>-<sequence>` artifacts appear
about once a minute. They contain full research/authoring JSONL transcripts,
prompts and model settings, plus `progress.json`. Download the newest snapshot
from the running workflow's artifacts. Local counters update every 15 seconds;
the final artifact retains `progress/history.jsonl`. Counters separate active
tools, advisor waits, layout checks, stills and renders. Tool durations can overlap;
they are not an exclusive partition of wall time. API duration is reported when
each CLI session ends. Snapshot/upload failures do not stop video generation.
The artifact uploader's runtime credentials are excluded from the child process.

Provide optional `LANGSMITH_API_KEY` and `langsmith-workspace-id` to send full
sessions to the private `langsmith-project` (default `daily-learning-briefing`).
The pinned official LangSmith Claude Code plugin records prompts, tool inputs and
outputs, assistant responses, subagents and usage, with secret redaction enabled.
Tool traces upload during a turn; complete model/subagent structure settles as
sessions finish. `research.trace.json` and `agent.trace.json` retain the session
IDs. Metadata includes CI run/attempt, repository, commit, lesson and phase.
System prompts and unavailable/redacted advisor internals are not recoverable.

The plugin is pinned to 0.4.2: a real workspace-scoped smoke test succeeded there;
0.5.3 dropped the workspace when uploading with an org-scoped key (HTTP 403).
Verify ingestion, not only hook exit status, when updating this pin. Tracing
failures retain the full private GitHub transcripts and never relax quality QA.
The public-by-URL S3 media bucket is not a destination for raw session traces;
its existing main-only publisher and IAM boundary remain unchanged.
