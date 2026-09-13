import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";

for (const [message, code] of [
  ["Your account has exceeded D1's free tier daily row write limit. private-canary", "d1_daily_write_limit"],
  ["Your account has exceeded D1's free tier daily row read limit. private-canary", "d1_daily_read_limit"],
  ["unexpected private-canary", "inbox_unavailable"],
]) {
  test(`capture exposes safe failure category: ${code}`, async (t) => {
    const h = await harness(t);
    await h.db.exec(`CREATE TRIGGER outage BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, '${message.replaceAll("'", "''")}'); END;`);
    const response = await h.send(event());
    assert.equal(response.status, 503);
    assert.equal(response.headers.get("Content-Type"), "application/json");
    assert.deepEqual(await response.json(), { error: code });
    const retry = Number(response.headers.get("Retry-After"));
    assert.ok(retry > 0 && retry <= 86400);
  });
}
