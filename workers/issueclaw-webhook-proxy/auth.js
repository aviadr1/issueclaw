const encoder = new TextEncoder();
export async function digest(body) {
  return Array.from(
    new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(body))),
  )
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}
export async function signed(body, signature, secret) {
  if (!secret || !/^[a-fA-F0-9]{64}$/.test(signature || "")) return false;
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"],
  );
  return crypto.subtle.verify(
    "HMAC",
    key,
    Uint8Array.from(signature.match(/../g), (b) => parseInt(b, 16)),
    encoder.encode(body),
  );
}
export async function authorized(request, env) {
  if (!env.INBOX_TOKEN) return false;
  return crypto.subtle.timingSafeEqual(
    encoder.encode(await digest(request.headers.get("Authorization") || "")),
    encoder.encode(await digest(`Bearer ${env.INBOX_TOKEN}`)),
  );
}
export async function boundedBody(request) {
  const reader = request.body?.getReader();
  if (!reader) throw new Error("Body required");
  const chunks = [];
  let size = 0;
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > 512 * 1024) {
      await reader.cancel();
      throw new Error("Body too large");
    }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.length;
  }
  return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
}
