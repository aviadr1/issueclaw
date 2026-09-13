import assert from "node:assert/strict";
import { test } from "node:test";
import { event, harness } from "./harness.js";

test("duplicate ACK cannot change already committed progress", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const batch = await (await h.api("claim")).json();
  assert.equal((await h.ack(batch)).status, 200);
  assert.equal((await h.ack(batch)).status, 409);
  assert.equal((await h.api("claim")).status, 204);
});

test("dispatch failure leaves durable work, duplicate events and cron do not multiply it", async (t) => {
  const h = await harness(t);
  await h.send(event());
  await h.send(event());
  const worker = await h.mf.getWorker();
  assert.equal(
    (await worker.scheduled({ cron: "17 * * * *" })).outcome,
    "exception",
  );
  await worker.scheduled({ cron: "17 * * * *" });
  assert.deepEqual(h.calls, [{ event_type: "linear-inbox-ready" }]);
  const batch = await (await h.api("claim")).json();
  assert.equal(batch.items.length, 1);
  assert.equal(
    (await h.db.prepare("SELECT count(*) AS n FROM events").first()).n,
    1,
  );
});

test("1001 distinct entities drain in bounded batches", async (t) => {
  const h = await harness(t);
  const ids = [];
  for (let n = 0; n < 1001; n++)
    assert.equal((await h.send(event(String(n)))).status, 200);
  for (let n = 0; n < 11; n++) {
    const batch = await (await h.api("claim")).json();
    assert.ok(batch.items.length <= 100);
    ids.push(...batch.items.map((i) => i.payload.data.id));
    assert.equal((await h.ack(batch)).status, 200);
  }
  assert.deepEqual(
    ids.sort(),
    Array.from({ length: 1001 }, (_, n) => String(n)).sort(),
  );
  assert.equal((await h.api("claim")).status, 204);
});

test("lease expiry replays only unprocessed generations and rejects old owner", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const first = await (await h.api("claim")).json();
  await h.db.prepare("UPDATE work SET lease_until=0").run();
  const next = await (await h.api("claim")).json();
  assert.deepEqual(next.items, first.items);
  assert.notEqual(next.token, first.token);
  assert.equal((await h.ack(first)).status, 409);
  assert.equal((await h.ack(next)).status, 200);
});

test("overlapping claims never share an entity lease", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const replies = await Promise.all(
    Array.from({ length: 8 }, () => h.api("claim")),
  );
  assert.deepEqual(
    replies.map((r) => r.status).sort(),
    [200, 204, 204, 204, 204, 204, 204, 204],
  );
});

test("unauthorized requests and another organization cannot mutate state", async (t) => {
  const h = await harness(t);
  assert.equal(
    (await h.post("/", {}, { "Linear-Signature": "bad" })).status,
    401,
  );
  for (const path of ["claim", "ack", "status"])
    assert.equal((await h.post(`/inbox/${path}`, {})).status, 401);
  assert.equal(
    (await h.send(event("1", { organizationId: "other" }))).status,
    400,
  );
  assert.equal(
    (await h.db.prepare("SELECT count(*) AS n FROM events").first()).n,
    0,
  );
});

test("failed durable write never acknowledges Linear", async (t) => {
  const h = await harness(t);
  await h.db.exec("DROP TABLE events");
  assert.equal((await h.send(event())).status, 503);
});

test("idle cron launches no runner; retention cannot strip pending evidence", async (t) => {
  const h = await harness(t);
  const worker = await h.mf.getWorker();
  await worker.scheduled({ cron: "17 * * * *" });
  assert.equal(h.calls.length, 0);
  await h.send(event("processed"));
  await h.ack(await (await h.api("claim")).json());
  await h.send(event("pending"));
  await h.db.prepare("UPDATE events SET received_at=0").run();
  await worker.scheduled({ cron: "17 * * * *" });
  const rows = (
    await h.db.prepare("SELECT work_key,payload FROM events ORDER BY seq").all()
  ).results;
  assert.equal(rows[0].payload, "");
  assert.notEqual(rows[1].payload, "");
});
