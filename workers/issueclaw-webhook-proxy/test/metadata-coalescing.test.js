import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";
import { metadataStatements } from "../incremental.js";

const child = (id, field = "issueId", time = "2026-09-12T00:00:00Z", type = "Comment") =>
  event(id, { type, data: { id, [field]: "parent", updatedAt: time }, createdAt: time });
const upload = (h, records) => h.api("reconcile", { organizationId: "test-org", records });
const count = async (h, table) => (await h.db.prepare(`SELECT count(*) n FROM ${table}`).first()).n;

for (const [type, field] of [["Comment", "issueId"], ["Comment", "projectId"],
  ["Comment", "initiativeId"], ["Comment", "documentId"], ["ProjectUpdate", "projectId"]]) {
  test(`${type}/${field}: 25 source versions require only one owner capture`, async (t) => {
    const h = await harness(t);
    const records = Array.from({ length: 25 }, (_, i) => child(String(i), field, undefined, type));
    assert.equal((await upload(h, records)).status, 200);
    assert.equal(await count(h, "events"), 1);
    assert.equal(await count(h, "work"), 1);
    assert.equal(await count(h, "source_versions"), 25);
    const first = await (await h.api("claim")).json();
    assert.equal(first.items.length, 1);
    await h.ack(first);
    // Retry order and batch boundaries must not create additional work.
    for (const retry of [records.toReversed(), records.slice(0, 12), records.slice(12)])
      assert.equal((await upload(h, retry)).status, 200);
    assert.equal(await count(h, "events"), 1);
    assert.equal((await h.api("claim")).status, 204);
  });
}

test("known newest source cannot hide an unseen older child during an active lease", async (t) => {
  const h = await harness(t);
  const newest = child("known", "issueId", "2026-09-13T00:00:00Z");
  assert.equal((await upload(h, [newest])).status, 200);
  const first = await (await h.api("claim")).json();
  assert.equal((await upload(h, [newest, child("unseen")])).status, 200);
  await h.ack(first);
  const next = await (await h.api("claim")).json();
  assert.ok(next.items[0].generation > first.items[0].generation);
  await h.ack(next);
  assert.equal((await h.api("claim")).status, 204);
});

test("different source kinds sharing an ID remain distinct observations of one owner", async (t) => {
  const h = await harness(t);
  const records = [child("parent", "projectId"), child("parent", "projectId", undefined, "ProjectUpdate"),
    event("parent", { type: "Project", data: { id: "parent", updatedAt: "2026-09-12T00:00:00Z" } })];
  assert.equal((await upload(h, records)).status, 200);
  assert.equal(await count(h, "events"), 1);
  assert.equal(await count(h, "source_versions"), 3);
  const batch = await (await h.api("claim")).json();
  assert.equal(batch.items.length, 1);
  assert.equal(batch.items[0].payload.type, "Project");
  assert.equal(batch.items[0].payload.data.id, "parent");
});

test("failure on the last source version rolls back all grouped owners and allows exact retry", async (t) => {
  const h = await harness(t);
  const records = [child("first"), child("second"), child("fail", "projectId")];
  await h.db.exec("CREATE TRIGGER outage BEFORE INSERT ON source_versions WHEN NEW.id='fail' BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END;");
  assert.equal((await upload(h, records)).status, 503);
  for (const table of ["events", "work", "source_versions"]) assert.equal(await count(h, table), 0);
  await h.db.exec("DROP TRIGGER outage");
  assert.equal((await upload(h, records)).status, 200);
  assert.equal(await count(h, "events"), 2);
  assert.equal(await count(h, "work"), 2);
  assert.equal(await count(h, "source_versions"), 3);
});

test("coalescing reduces measured D1 writes, and regrouped repeats write zero rows", async (t) => {
  const h = await harness(t);
  const env = { INBOX: h.db, INBOX_ORGANIZATION_ID: "test-org" };
  const records = Array.from({ length: 25 }, (_, i) => child(String(i)));
  const execute = async (values) => (await h.db.batch(await metadataStatements(env, values)))
    .reduce((sum, result) => sum + result.meta.rows_written, 0);
  // Compare the same canonical capture implementation, with versus without
  // shared-owner batching; measure real D1 metadata, not estimated SQL counts.
  let separate = 0;
  for (const record of records) separate += await execute([record]);
  const grouped = await execute(records.map((record) => ({ ...record,
    data: { ...record.data, id: `group-${record.data.id}`, issueId: "group-parent" } })));
  t.diagnostic(`25 same-owner sources: separate=${separate}, grouped=${grouped} row writes`);
  assert.ok(grouped > 0);
  assert.ok(grouped < separate / 2);
  assert.equal(await execute(records.toReversed()), 0);
  assert.equal(await execute(records.slice(0, 12)), 0);
  assert.equal(await execute(records.slice(12)), 0);
});
