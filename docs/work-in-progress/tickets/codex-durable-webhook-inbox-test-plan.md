# Hourly inbox implementation plan

The first prototype used an ordered global cursor. Replace it with durable per-entity generations: it is one identity model for capture, claim, retry and ACK, not a second cancellation scheme. Keep existing Python entity parsing/rendering as the authority. Extract shared Miniflare and real-Git fixtures instead of mock call sequences.

- [x] Capture → claim → edits during lease → ACK: new generation survives, first pending age is not extended by rapid edits.
- [x] Same-entity Issue/Comment storms collapse to one current-state fetch; raw events retained separately.
- [x] Partial batch failure leaves only failed keys retryable; valid keys publish and ACK.
- [x] Failed Git push cannot ACK; accepted push + lost ACK reuses remote per-key receipts.
- [x] Expired lease, overlapping claims, duplicate ACK, wrong token and stream tests.
- [x] Hourly dispatch only for due work, durable rate limit, zero dispatch during ingress or idle hours.
- [x] Complete paginated census tests recover missing entities/comments and require separated observations for deletion; failed scans retain the last snapshot.
- [x] Retention removes only processed old payloads, never pending keys or receipts.
- [x] Worker and Python share a wire fixture checked against the actual producer; packaged CLI executes.
- [ ] Company opt-in caller pinned to published implementation SHA.
- [x] Full Python suite, type checks, lint and Worker dependency audit.
- [x] Final Worker suite: 22 passed; Python duplicate-test-name audit passed.

No production resources will be provisioned or deployed in this task. Real-provider capacity, credentials/visibility and cost/freshness measurements remain rollout gates, not passing local test claims.
