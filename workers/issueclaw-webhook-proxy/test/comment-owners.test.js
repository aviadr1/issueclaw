import assert from "node:assert/strict";
import { test } from "node:test";
import { harness, event } from "./harness.js";
for (const [field,type] of [["issueId","Issue"],["projectId","Project"],["initiativeId","Initiative"],["documentId","Document"]]) {
  test(`Comment ${field} is queued under the real owner`,async t => {
    const h=await harness(t);
    const record=event("comment",{type:"Comment",data:{id:"comment",updatedAt:"2026-09-13T00:00:00Z",[field]:"owner"}});
    assert.equal((await h.api("reconcile",{organizationId:"test-org",records:[record]})).status,200);
    const batch=await (await h.api("claim")).json();
    assert.equal(batch.items[0].payload.type,type);
    assert.equal(batch.items[0].payload.data.id,"owner");
    await h.ack(batch);
    assert.equal((await h.api("reconcile",{organizationId:"test-org",records:[record]})).status,200);
    assert.equal((await h.api("claim")).status,204);
  });
}
