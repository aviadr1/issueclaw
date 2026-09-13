import assert from "node:assert/strict";
import { test } from "node:test";
import { event, harness } from "./harness.js";

for (const deferred of [false, true]) {
  test(`unfinished work is ${deferred ? "deferred" : "failed"}, never acknowledged`, async (t) => {
    const h = await harness(t);
    await h.send(event());
    const batch = await (await h.api("claim")).json();
    assert.equal((await h.api("ack", { token: batch.token, results: [{ key: batch.items[0].key, success: false, deferred }] })).status, 200);
    const status = await (await h.api("status")).json();
    assert.equal(status.pending, 1);
    assert.equal(status.failed, deferred ? 0 : 1);
    assert.equal((await h.api("claim")).status, deferred ? 200 : 204);
  });
}

test("deferral preserves newer edits, prior failures and lease fencing", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const first = await (await h.api("claim")).json();
  await h.ack(first, [first.items[0].key]);
  await h.db.prepare("UPDATE work SET retry_at=0").run();
  const batch = await (await h.api("claim")).json();
  await h.send(event("1", { createdAt: "2026-09-13T01:00:00Z" }));
  const body = {token: batch.token, results: [{key: batch.items[0].key, success: false, deferred: true}]};
  assert.equal((await h.api("ack", body)).status, 200);
  assert.equal((await h.api("ack", body)).status, 409);
  const next = await (await h.api("claim")).json();
  assert.ok(next.items[0].generation > batch.items[0].generation);
  assert.equal((await (await h.api("status")).json()).failed, 1);
  await h.ack(next);
  assert.equal((await (await h.api("status")).json()).pending, 0);
});

for (const outcome of [{success: true, deferred: true}, {success: false, deferred: "true"}, {success: false, deferred: null}]) {
  test(`invalid deferral cannot alter a lease: ${JSON.stringify(outcome)}`, async (t) => {
    const h = await harness(t);
    await h.send(event());
    const batch = await (await h.api("claim")).json();
    assert.equal((await h.api("ack", {token: batch.token, results: [{key: batch.items[0].key, ...outcome}]})).status, 400);
    assert.equal((await h.ack(batch)).status, 200);
  });
}
