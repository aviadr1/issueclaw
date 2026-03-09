/**
 * Cloudflare Worker: Linear webhook proxy
 *
 * Receives Linear webhooks, validates the signature, and forwards
 * the payload to a GitHub repository_dispatch event.
 *
 * Environment variables (set via wrangler secrets):
 *   LINEAR_WEBHOOK_SECRET  - Linear webhook signing secret
 *   GITHUB_TOKEN           - GitHub PAT with repo scope
 *   GITHUB_REPO            - Target repo in "owner/repo" format
 */

export default {
  async fetch(request, env) {
    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const body = await request.text();

    // Validate Linear webhook signature
    const signature = request.headers.get("Linear-Signature");
    if (!signature) {
      return new Response("Missing signature", { status: 401 });
    }

    const isValid = await verifySignature(body, signature, env.LINEAR_WEBHOOK_SECRET);
    if (!isValid) {
      return new Response("Invalid signature", { status: 401 });
    }

    // Parse the payload
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return new Response("Invalid JSON", { status: 400 });
    }

    // Forward to GitHub repository_dispatch
    const repo = env.GITHUB_REPO;
    const githubUrl = `https://api.github.com/repos/${repo}/dispatches`;

    const dispatchPayload = {
      event_type: "linear-webhook",
      client_payload: {
        action: payload.action,
        type: payload.type,
        data: payload.data,
        url: payload.url,
        createdAt: payload.createdAt,
      },
    };

    const githubResponse = await fetch(githubUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
        "User-Agent": "issueclaw-webhook-proxy",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify(dispatchPayload),
    });

    if (!githubResponse.ok) {
      const errorText = await githubResponse.text();
      console.error(`GitHub dispatch failed: ${githubResponse.status} ${errorText}`);
      return new Response("GitHub dispatch failed", { status: 502 });
    }

    return new Response("OK", { status: 200 });
  },
};

/**
 * Verify Linear webhook signature using HMAC-SHA256.
 */
async function verifySignature(body, signature, secret) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signed = await crypto.subtle.sign("HMAC", key, encoder.encode(body));
  const expectedSignature = Array.from(new Uint8Array(signed))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  return expectedSignature === signature;
}
