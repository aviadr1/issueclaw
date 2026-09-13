import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";

test("hourly scheduler never queries Linear, including an empty inbox", async (t) => {
  let requests = 0;
  const h = await harness(t, { linear: () => { requests++; return {}; }, dispatchStatus: 204 });
  const worker = await h.mf.getWorker();
  await worker.scheduled({ cron: "17 * * * *" });
  assert.equal(requests, 0);
  assert.equal(h.calls.length, 0);
  await h.send(event());
  await worker.scheduled({ cron: "17 * * * *" });
  await worker.scheduled({ cron: "17 * * * *" });
  assert.equal(requests, 0);
  assert.equal(h.calls.length, 1);
});

test("daily metadata skips versions already captured by webhooks but queues newer edits", async (t) => {
  const h = await harness(t);
  const record = event("one", { data: { id: "one", updatedAt: "2026-09-12T00:00:00Z" } });
  await h.send(record);
  await h.ack(await (await h.api("claim")).json());
  const upload = (records) => h.api("reconcile", { organizationId: "test-org", records });
  assert.equal((await upload([record])).status, 200);
  assert.equal((await h.api("claim")).status, 204);
  record.data.updatedAt = record.createdAt = "2026-09-13T01:00:00Z";
  assert.equal((await upload([record])).status, 200);
  assert.equal((await h.api("claim")).status, 200);
});

test("daily checkpoint is compare-and-swap and never advances on malformed import", async (t) => {
  const h = await harness(t);
  const until = Date.now() - 1000;
  assert.equal((await h.api("reconcile", { organizationId: "wrong", records: [event()] })).status, 400);
  assert.equal((await (await h.api("status")).json()).reconciliation_at, 0);
  assert.equal((await h.api("reconcile-complete", { expected: 0, until })).status, 200);
  assert.equal((await h.api("reconcile-complete", { expected: 0, until })).status, 409);
  assert.equal((await h.api("reconcile-complete", { expected: until, until: until - 1 })).status, 400);
});

for (const [kind, parentField, target] of [["Issue", null, "Issue"], ["Document", null, "Document"],
  ["Project", null, "Project"], ["Initiative", null, "Initiative"], ["Comment", "issueId", "Issue"],
  ["ProjectUpdate", "projectId", "Project"]]) {
  test(`${kind} imports share capture and survive edits during a claim`, async (t) => {
    const h = await harness(t);
    const record = event("source", { type: kind, data: { id: "source", updatedAt: "2026-09-12T00:00:00Z",
      ...(parentField ? { [parentField]: "parent" } : {}) } });
    const upload = () => h.api("reconcile", { organizationId: "test-org", records: [record] });
    assert.equal((await upload()).status, 200);
    const first = await (await h.api("claim")).json();
    assert.equal(first.items[0].payload.type, target);
    assert.equal(first.items[0].payload.data.id, parentField ? "parent" : "source");
    record.data.updatedAt = record.createdAt = "2026-09-13T00:00:00Z";
    assert.equal((await h.send(record)).status, 200);
    await h.ack(first);
    const second = await (await h.api("claim")).json();
    assert.ok(second.items[0].generation > first.items[0].generation);
    await h.ack(second);
    record.data.updatedAt = record.createdAt = "2026-09-12T00:00:00Z";
    assert.equal((await upload()).status, 200);
    assert.equal((await h.api("claim")).status, 204);
  });
}

for (const invalid of [
  { type: "Team" }, { action: "remove" }, { organizationId: "other" },
  { data: { id: "bad", updatedAt: "nonsense" } },
  { type: "Comment", data: { id: "bad", updatedAt: "2026-09-12T00:00:00Z" } },
]) {
  test(`invalid metadata batch is all-or-nothing: ${JSON.stringify(invalid)}`, async (t) => {
    const h = await harness(t);
    const valid = event("valid", { data: { id: "valid", updatedAt: "2026-09-12T00:00:00Z" } });
    assert.equal((await h.api("reconcile", { organizationId: "test-org", records: [valid, { ...valid, ...invalid }] })).status, 400);
    assert.equal((await h.api("claim")).status, 204);
    assert.equal((await h.db.prepare("SELECT count(*) AS n FROM source_versions").first()).n, 0);
  });
}

test("import batch capacity is bounded and duplicate requests cannot create new generations", async (t) => {
  const h = await harness(t);
  const records = Array.from({ length: 26 }, (_, i) => event(String(i), { data: { id: String(i), updatedAt: "2026-09-12T00:00:00Z" } }));
  const upload = (values) => h.api("reconcile", { organizationId: "test-org", records: values });
  assert.equal((await upload(records)).status, 400);
  assert.equal((await h.api("claim")).status, 204);
  assert.equal((await upload(records.slice(0, 25))).status, 200);
  const first = await (await h.api("claim")).json();
  assert.equal(first.items.length, 25);
  await h.ack(first);
  assert.equal((await upload(records.slice(0, 25))).status, 200);
  assert.equal((await h.api("claim")).status, 204);
});
