# Design Canvas publishing repair

- [x] Preserve Slack's actionable content rejection detail and redact the token; only confirmed rejection codes clear pending creation.
- [x] Normalize h4–h6 to h3 through the production publisher; keep fenced Markdown, image URLs and links intact; resume without duplicate Canvas creation.
- [x] Upload selected manifest captures through the real shared Slack file transport with mocked HTTP; verify hashes before upload and preserve full-size public links.
- [x] Recover a lost file-completion response using the saved file ID; repair the same Canvas without another upload or summary message.
- [x] Reject missing/changed captures and paths escaping the manifest directory before upload.
- [x] Regression coverage for existing daily briefings and video delivery after sharing the file transport.
- [x] Real CI diagnosed `line 28: Unsupported heading depth (4)`; heading repair published the report, then user screenshot exposed blank external image previews.
- [x] Real Claude conversion used Sonnet 5.5, Haiku 5.5 and Opus 5.5 advisor (run 37903561951).
- [x] Native image repair run 37904480539 succeeded: 24 completed image receipts, 24 image embeds in Slack read-back, same Canvas ID and summary timestamp. The read-back retains all 41 preview URL occurrences and six video links. Computer-use visual inspection was unavailable because its runtime rejected the WSL working directory.

Report source: linear-git run 37781764858. Existing Canvas: F0C7TT5G81Z; preserve its URL and summary timestamp. No Terraform changes, apply, or PR merges.
