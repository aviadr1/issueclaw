import { authorized, boundedBody, digest, signed } from "./auth.js";
import {
  aggregate,
  capture,
  claim,
  acknowledge,
  status,
  reserveDispatch,
  retain,
} from "./store.js";
import { importMetadata, completeReconciliation } from "./incremental.js";
import { failureResponse } from "./failures.js";

export default {
  async fetch(request, env) {
    try {
      if (!env.INBOX || !env.INBOX_STREAM || !env.INBOX_ORGANIZATION_ID)
        return new Response("Inbox not configured", { status: 503 });
      const path = new URL(request.url).pathname;
      if (path.startsWith("/inbox/")) {
        if (!(await authorized(request, env)))
          return new Response("Unauthorized", { status: 401 });
        if (request.method !== "POST")
          return new Response("POST required", { status: 405 });
        if (path === "/inbox/claim") return await claim(env);
        if (path === "/inbox/ack")
          return await acknowledge(env, JSON.parse(await boundedBody(request)));
        if (path === "/inbox/status") return Response.json(await status(env));
        if (path === "/inbox/reconcile")
          return await importMetadata(env, JSON.parse(await boundedBody(request)));
        if (path === "/inbox/reconcile-complete")
          return await completeReconciliation(env, JSON.parse(await boundedBody(request)));
        return new Response("Not found", { status: 404 });
      }
      if (request.method !== "POST")
        return new Response("POST required", { status: 405 });
      const body = await boundedBody(request);
      if (
        !(await signed(
          body,
          request.headers.get("Linear-Signature"),
          env.LINEAR_WEBHOOK_SECRET,
        ))
      )
        return new Response("Invalid signature", { status: 401 });
      let payload;
      try {
        payload = JSON.parse(body);
        aggregate(payload, env.INBOX_ORGANIZATION_ID);
      } catch {
        return new Response("Invalid event or unsupported parent", {
          status: 400,
        });
      }
      await capture(env, body, await digest(body), payload);
      // Linear requires exactly 200. No per-event dispatch or runner exists here.
      return new Response("Persisted", { status: 200 });
    } catch (error) {
      return failureResponse(error);
    }
  },
  async scheduled(_controller, env) {
    // Discovery runs daily on CI. An idle hour makes no external API calls.
    await retain(env);
    if (!(await reserveDispatch(env))) return;
    const response = await fetch(
      `https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GITHUB_TOKEN}`,
          Accept: "application/vnd.github+json",
          "Content-Type": "application/json",
          "User-Agent": "issueclaw-inbox",
        },
        body: JSON.stringify({ event_type: "linear-inbox-ready" }),
      },
    );
    if (!response.ok)
      throw new Error(`Inbox wakeup failed: HTTP ${response.status}`);
  },
};
