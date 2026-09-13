import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { event, harness } from "./harness.js";
import { nextHour, HOUR } from "../store.js";

test("real Worker claim matches the Python consumer's shared wire fixture", async (t) => {
  const h = await harness(t);
  await h.send(event());
  const batch = await (await h.api("claim")).json();
  assert.ok(batch.token);
  batch.token = "NORMALIZED_LEASE_TOKEN";
  assert.deepEqual(
    batch,
    JSON.parse(await readFile("../../tests/fixtures/inbox-batch.json", "utf8")),
  );
});

for (const offset of [0, 1, 17 * 60 * 1000, HOUR - 1]) {
  test(`hourly boundary does not drift at offset ${offset}`, () => {
    assert.equal(nextHour(100 * HOUR + offset), 101 * HOUR);
  });
}

test("out-of-order old deletion cannot supersede a newer entity update", async (t) => {
  const h = await harness(t);
  await h.send(event("1", { createdAt: "2026-09-13T02:00:00Z" }));
  await h.send(
    event("1", { action: "remove", createdAt: "2026-09-13T01:00:00Z" }),
  );
  const batch = await (await h.api("claim")).json();
  assert.equal(batch.items[0].payload.action, "update");
  assert.equal(batch.items[0].payload.createdAt, "2026-09-13T02:00:00Z");
});
