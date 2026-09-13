import assert from "node:assert/strict";
import { test } from "node:test";
import { event, harness } from "./harness.js";

test("200 edits including comments collapse to one leased parent; no ingress dispatch", async (t) => {
  const h = await harness(t);
  for (let n = 0; n < 200; n++) {
    const value =
      n % 2
        ? event(`comment-${n}`, {
            type: "Comment",
            action: "remove",
            data: { id: `comment-${n}`, issueId: "1" },
          })
        : event("1", { url: `edit-${n}` });
    assert.equal((await h.send(value)).status, 200);
  }
  const batch = await (await h.api("claim")).json();
  assert.equal(batch.items.length, 1);
  assert.equal(batch.items[0].payload.type, "Issue");
  assert.equal(batch.items[0].payload.action, "update");
  assert.equal(h.calls.length, 0);
  assert.equal((await h.ack(batch)).status, 200);
  assert.equal((await h.api("claim")).status, 204);
});

test("an edit arriving after claim survives acknowledgement of the snapshot", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const first = await (await h.api("claim")).json();
  await h.send(event("1", { createdAt: "2026-09-13T01:00:00Z" }));
  assert.equal((await h.ack(first)).status, 200);
  const next = await (await h.api("claim")).json();
  assert.equal(next.items.length, 1);
  assert.ok(next.items[0].generation > first.items[0].generation);
});

test("failed keys do not hold successful keys hostage", async (t) => {
  const h = await harness(t);
  await h.send(event("bad"));
  await h.send(event("good"));
  const batch = await (await h.api("claim")).json();
  const bad = batch.items.find((i) => i.payload.data.id === "bad");
  assert.equal((await h.ack(batch, [bad.key])).status, 200);
  assert.equal((await h.api("status")).status, 200);
  const status = await (await h.api("status")).json();
  assert.equal(status.pending, 1);
  assert.equal(
    (await h.api("claim")).status,
    204,
    "Failed key must back off, not spin in the same job",
  );
  await h.db.prepare("UPDATE work SET retry_at = 0").run();
  const retry = await (await h.api("claim")).json();
  assert.deepEqual(
    retry.items.map((i) => i.key),
    [bad.key],
  );
});

test("edits do not move first-pending age or erase the breach", async (t) => {
  const h = await harness(t);
  await h.send(event());
  await h.db
    .prepare("UPDATE work SET first_pending_at = ?")
    .bind(Date.now() - 3 * 3600000)
    .run();
  await h.send(event("1", { url: "edited" }));
  const status = await (await h.api("status")).json();
  assert.equal(status.freshness_breached, true);
});
