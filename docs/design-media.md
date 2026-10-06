# Visual evidence for design reports

The optional `media` extra adds a Chromium handoff collector. Company-specific
repositories, authors and approved preview hosts belong in the caller's JSON
config, not in issueclaw. Run `python -m issueclaw.design_media --help`.

```json
{
  "repositories": ["example/app"],
  "design_authors": ["designer"],
  "preview_hosts": ["preview.example.com"],
  "states_per_preview": 6,
  "record_walkthroughs": true
}
```

## Collection and publication

1. Install `issueclaw[media]` and `python -m playwright install --with-deps chromium`.
2. Run `collect --config sources.json --out-dir /tmp/report/media` with read-only
   `GH_TOKEN`. This discovers open author-owned preview PRs; the report author
   still traces implementation PRs and other designer involvement independently.
3. Run `host --manifest /tmp/report/media/manifest.json --bucket BUCKET
   --prefix reports/RUN_ID --public-base https://BUCKET.s3.amazonaws.com` using the
   caller's existing AWS identity. No bucket, ACL, role or public policy is created.
   The supplied prefix must already be appropriate for the report's audience.
4. Inspect local candidate images, write the report with verified hosted URLs,
   and save a selection JSON as shown below.
5. Run `validate --manifest ... --selection selection.json --report report.md`
   both after generation and after restoring artifacts for publication.

```json
{"sources": [
  {"pr_url": "https://github.com/example/app/pull/42", "media_ids": ["app-42-0-3"]},
  {"pr_url": "https://github.com/example/app/pull/43", "media_ids": [],
   "exclusion_reason": "This retained reference has no automatic handoff screen list."}
]}
```

An exclusion's exact reason and PR link must appear in the report. Images must
be embedded; videos must be labeled links. Every inventoried PR is accounted for,
and a report cannot discard every available image. Persist the manifest, source
evidence, images, videos, selection and report together as private CI artifacts.
Missing access, zero captures, incomplete source pagination, failed hosting or
invalid coverage fail the relevant stage. Individual inaccessible preview routes
remain in the manifest, so the report can explain partial coverage.

## Capture contract and limits

The collector recognizes numbered handoff buttons (the mobile `Proto` frame and
the web `ConceptFrame`), enumerates all discovered entries, then spreads a bounded
candidate selection over the list. It clicks actual rows: hash mutation alone can
leave React previews on an old state. Description-only entries are retained in
inventory but never captured as visual evidence. Device frames and handoff iframes
are captured directly; other layouts use the viewport. Walkthrough videos show
the screen picker selecting fixture states, not an asserted end-user journey.

The manifest distinguishes PR head metadata, raw deployment comments, capture
time, screen URL, label and a digest of the media. It does not attest that the
served deployment equals the PR head. The writer must establish that separately
or label the capture as the observed preview. Screenshots also do not prove native
implementation, merge, release, or successful backend operations.

Source entrypoints are inferred from changed static `public/*/index.html` files,
`dev.*.tsx` route files and explicit links. Other frameworks can add config
`routes` entries keyed by `owner/repo#number`, with paths relative to the preview
root. Sites without a supported screen list are reported as unavailable for
automatic capture. New authors must be added to the consumer configuration.
The default budget is 40 preview routes, configurable with `max_previews`.

GitHub and AWS credentials stay in their request processes. The browser uses a
fresh unauthenticated context, no saved session, and never clicks purchase, send,
join, or other application controls. Only screen-selection buttons are clicked.

## Tests

`uv run pytest tests/test_design_media.py -n 0` tests route discovery and publication
invariants. `uv sync --extra media` followed by `uv run pytest
tests/test_design_media_browser.py -m browser -n 0` exercises real Chromium against
a local handoff fixture. CI installs Chromium for that dedicated job; the default
unit suite does not require a browser. `DESIGN_BROWSER_EXECUTABLE` can select an
already-installed local Chromium when testing.
