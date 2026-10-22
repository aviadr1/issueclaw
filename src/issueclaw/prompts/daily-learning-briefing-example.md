# Worked example: a readable action-first briefing

This is a fictional example of the finished writing, using invented people,
repositories, dates and evidence. Learn its structure, density and tone. Replace
every fact, name, date and URL with the current run's verified evidence; this
example is never a source. The day below has only two meaningful changes, so its
Canvas is shorter than a busy day's report. Do not add filler to match a word count.

The Slack message answers who needs to act, while the Canvas explains the work.
Notice the concrete next steps, adoption limits and short standalone lesson. The
review walkthrough is about an open PR; the learning is about a completed change.

## Agent output: slack-summary.json

```json
{
  "needs_attention": [
    "**Rae:** re-review [web #41](https://github.com/example/web/pull/41); the author pushed the requested access-filter changes yesterday.",
    "**Mobile CI — owner unverified:** investigate the failing reconnect lane and rerun it. A later dispatch-only success did not exercise that lane. [Failure](https://github.com/example/mobile/actions/runs/100)",
    "**Release check:** confirm common 1.8 is published before merging the web adoption PR; publication was not captured in this snapshot."
  ],
  "for_awareness": [
    "Mobile checkout now carries the selected discount into the cart; web adoption is still open.",
    "The test harness now deduplicates replayed announcements. Production chat is unchanged."
  ]
}
```

The publisher renders that data as follows. The example link is illustrative;
the real publisher supplies the confirmed Canvas URL after creation.

> **Frontend morning briefing — 2026-01-15**
>
> **🔴 Needs attention**
>
> - **Rae:** re-review [web #41](https://github.com/example/web/pull/41); the author pushed the requested access-filter changes yesterday.
> - **Mobile CI — owner unverified:** investigate the failing reconnect lane and rerun it. A later dispatch-only success did not exercise that lane. [Failure](https://github.com/example/mobile/actions/runs/100)
> - **Release check:** confirm common 1.8 is published before merging the web adoption PR; publication was not captured in this snapshot.
>
>
> **🟢 For awareness**
>
> - Mobile checkout now carries the selected discount into the cart; web adoption is still open.
> - The test harness now deduplicates replayed announcements. Production chat is unchanged.
>
> [Open the daily briefing](https://example.invalid/confirmed-canvas)

## Agent output: report.md

```markdown
# Frontend morning briefing · January 15

## TLDR

- Rae has one re-review waiting; mobile reconnect CI still needs investigation.
- Mobile checkout carries discounts into the cart; web adoption remains open.
- The harness replay fix is merged. The short Learning section explains the pattern for another event consumer.

## Needs attention

### Reviews and release checks

| Who | Next action | Context |
|---|---|---|
| Rae | Re-review [web #41](https://github.com/example/web/pull/41) | Kim pushed the access-filter changes and re-requested review on January 14 at 15:10 UTC. |
| Owner unverified | Confirm common 1.8 publication before merging [web #43](https://github.com/example/web/pull/43) | The adoption PR depends on that version; the snapshot did not capture a successful publish run. |

### CI

**Mobile reconnect lane — investigate and rerun.** The scheduled run failed while reconnecting the test client; no cause or owner is established. A later success ran only dispatch, so it does not demonstrate recovery. [Failed run](https://github.com/example/mobile/actions/runs/100)

## What changed

### Selected discounts reach mobile checkout — Leads: Kim Park

The selected discount used to disappear when a product card was cloned, so a discounted preview could lead to a full-price cart. [Common #20](https://github.com/example/common/pull/20) now preserves the discount through parsing and cloning and includes it when building the cart link. Product-detail caching also includes the discount context, preventing one offer's price from being reused for another.

[Mobile #30](https://github.com/example/mobile/pull/30) adopted the shared change and rejects older validation responses when the selection changes. Its tests cover cloning, clearing the discount, and a slow response arriving after a newer selection. This establishes the tested behavior; it does not prove a production release.

**For you — Use an existing capability:** callers using common 1.8's `buildCartLink(product, {discountCode})` pass the selected code when constructing checkout links. Upgrading without supplying the code does not adopt the discount behavior. Web's adoption PR remains open, so web main has not acquired this path.

### Harness replay no longer drops queued announcements — Leads: Rae Chen

[Common #21](https://github.com/example/common/pull/21) fixes message loss during a test-client reconnect. Both apps adopted the updated harness in their test configuration. This changes the stand-in server used by tests, not production chat.

The Learning section below explains the failure and the reusable deduplication technique. Those merged changes do not establish recovery of the separate failing mobile run above.

## In progress

**Kim — web discount adoption.** [Web #43](https://github.com/example/web/pull/43) is a draft wiring the selected code into checkout. It has no review request; confirm the shared-package release before it is ready to merge.

## Review walkthrough: compare the list filter with existing access rules

[Web #41](https://github.com/example/web/pull/41) is open at reviewed head `abc1234`. The proposed list filter should show exactly the recordings that the existing detail view allows the visitor to open.

Kim addressed yesterday's finding about expired invitations. Rae's next review should compare both allowed and denied cases against the detail-view rule, including community membership and invitation expiry. The test added for expired invitations covers denial; it does not establish equivalence for every allowed case.

Start with the shared filter, then the regression test, then the detail-view permission check. This is review guidance, not approval. No rollout is claimed for this open PR.

## Learning

### Merged learning: deduplicate replayed events at receipt

**For you — Apply a technique:** when building another replayable consumer, such as a reconnecting notification feed, deduplicate by event identity rather than connection state.

Rae's [common #21](https://github.com/example/common/pull/21) merged into **main on January 14**. The test harness had skipped queued announcements once a socket connected, although the socket had never received those older events. The fix applies each announcement once, whichever path delivers it first. The PR reports reconnect tests that failed before the fix and passed afterward.

For another consumer, define event identity and how long its deduplication history must survive. That prevents loss or duplicate application across delivery paths; this example does not establish production-chat behavior.

**Learn more:** [Failure reproduction and reconnect tests](https://github.com/example/common/pull/21).

Coverage: January 14, 08:00 → January 15, 08:00 UTC. Review and CI snapshot: January 15, 08:12 UTC. Production rollout was not verified.
```

On a genuinely quiet day, `{"needs_attention": [], "for_awareness": []}` is valid.
The publisher supplies quiet-day text. Only use empty arrays when the evidence
supports them; shortening a busy day's summary is not a reason to erase work.
Keep a quiet Canvas factual and brief. Preserve the evidence note and any useful
carry-over; omit an unavailable walkthrough rather than inventing a PR to review.
