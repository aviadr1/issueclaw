import { createHmac } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { Miniflare } from "miniflare";

export const secret = "local-test-signing-secret";
export const token = "local-test-inbox-token";
export function event(id = "1", overrides = {}) {
  return {
    organizationId: "test-org",
    action: "update",
    type: "Issue",
    data: { id },
    createdAt: "2026-09-13T00:00:00Z",
    ...overrides,
  };
}

export async function harness(t, { linear, dispatchStatus = 503 } = {}) {
  const calls = [];
  const mf = new Miniflare({
    modules: true,
    modulesRules: [{ type: "ESModule", include: ["**/*.js"] }],
    scriptPath: "worker.js",
    compatibilityDate: "2026-07-01",
    d1Databases: { INBOX: "test-inbox" },
    bindings: {
      LINEAR_WEBHOOK_SECRET: secret,
      INBOX_TOKEN: token,
      GITHUB_REPO: "test/repo",
      GITHUB_TOKEN: "fake",
      INBOX_STREAM: "test-stream",
      INBOX_ORGANIZATION_ID: "test-org",
      LINEAR_API_KEY: "fake-linear",
    },
    outboundService: async (request) => {
      const body = await request.json();
      if (request.url.includes("api.linear.app")) {
        return Response.json(
          linear ? await linear(body) : { errors: [{ message: "Offline" }] },
        );
      }
      calls.push(body);
      return new Response(null, { status: dispatchStatus });
    },
  });
  t.after(() => mf.dispose());
  const db = await mf.getD1Database("INBOX");
  for (const file of (await readdir("migrations")).filter(f => f.endsWith(".sql")).sort()) {
    await db.exec((await readFile(`migrations/${file}`, "utf8")).replaceAll("\n", " "));
  }
  const post = (path, value, headers = {}) =>
    mf.dispatchFetch(`https://worker.test${path}`, {
      method: "POST",
      body: JSON.stringify(value),
      headers,
    });
  const send = (value) =>
    post("/", value, {
      "Linear-Signature": createHmac("sha256", secret)
        .update(JSON.stringify(value))
        .digest("hex"),
    });
  const api = (path, value = {}) =>
    post(`/inbox/${path}`, value, { Authorization: `Bearer ${token}` });
  const ack = (batch, failed = []) =>
    api("ack", {
      token: batch.token,
      results: batch.items.map((i) => ({
        key: i.key,
        success: !failed.includes(i.key),
      })),
    });
  return { db, send, api, ack, mf, calls, post };
}
