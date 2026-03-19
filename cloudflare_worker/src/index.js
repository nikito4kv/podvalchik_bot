const DEFAULT_TTL_SECONDS = 300;
const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;
const TEMP_MEDIA_PREFIX = "/temp-media/";

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === "/temp-media" && request.method === "POST") {
      return handleTempMediaUpload(request, env);
    }

    if (url.pathname.startsWith(TEMP_MEDIA_PREFIX) && request.method === "GET") {
      return handleTempMediaDownload(request, env, ctx);
    }

    return proxyTelegramApi(request, env);
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(cleanupExpiredMedia(env));
  },
};

async function handleTempMediaUpload(request, env) {
  assertConfigured(env);

  const authHeader = request.headers.get("Authorization") || "";
  if (authHeader !== `Bearer ${env.TEMP_MEDIA_UPLOAD_TOKEN}`) {
    return jsonResponse({ error: "Unauthorized" }, 401);
  }

  const contentType = request.headers.get("Content-Type") || "";
  if (!contentType.startsWith("image/png")) {
    return jsonResponse({ error: "Only image/png is supported" }, 415);
  }

  const ttlSeconds = clampTtl(request.headers.get("X-TTL-Seconds"), env.TEMP_MEDIA_TTL_SECONDS);
  const expiresAt = Date.now() + ttlSeconds * 1000;
  const key = buildObjectKey(expiresAt);
  const body = await request.arrayBuffer();

  if (body.byteLength === 0) {
    return jsonResponse({ error: "Empty body" }, 400);
  }
  if (body.byteLength > MAX_UPLOAD_BYTES) {
    return jsonResponse({ error: "Payload is too large" }, 413);
  }

  await env.TEMP_MEDIA_BUCKET.put(key, body, {
    httpMetadata: {
      contentType: "image/png",
      cacheControl: `public, max-age=${Math.min(ttlSeconds, 60)}`,
      contentDisposition: buildContentDisposition(request.headers.get("X-Filename")),
    },
    customMetadata: {
      expiresAt: String(expiresAt),
      uploadedAt: String(Date.now()),
    },
  });

  const url = new URL(request.url);
  const signature = await signValue(env.TEMP_MEDIA_SIGNING_SECRET, `${key}:${expiresAt}`);
  url.pathname = `${TEMP_MEDIA_PREFIX}${key}`;
  url.search = new URLSearchParams({
    exp: String(expiresAt),
    sig: signature,
  }).toString();

  return jsonResponse({
    key,
    url: url.toString(),
    expires_at: expiresAt,
  });
}

async function handleTempMediaDownload(request, env, ctx) {
  assertConfigured(env);

  const url = new URL(request.url);
  const key = url.pathname.slice(TEMP_MEDIA_PREFIX.length);
  const expiresAt = Number(url.searchParams.get("exp") || "0");
  const signature = url.searchParams.get("sig") || "";

  if (!key || !Number.isFinite(expiresAt) || expiresAt <= 0 || !signature) {
    return jsonResponse({ error: "Invalid signed URL" }, 400);
  }

  const now = Date.now();
  if (now > expiresAt) {
    ctx.waitUntil(env.TEMP_MEDIA_BUCKET.delete(key));
    return jsonResponse({ error: "URL expired" }, 410);
  }

  const expectedSignature = await signValue(
    env.TEMP_MEDIA_SIGNING_SECRET,
    `${key}:${expiresAt}`,
  );
  if (!timingSafeEqual(signature, expectedSignature)) {
    return jsonResponse({ error: "Invalid signature" }, 403);
  }

  const object = await env.TEMP_MEDIA_BUCKET.get(key);
  if (!object) {
    return jsonResponse({ error: "Not found" }, 404);
  }

  const objectExpiresAt = Number(object.customMetadata?.expiresAt || "0");
  if (objectExpiresAt > 0 && now > objectExpiresAt) {
    ctx.waitUntil(env.TEMP_MEDIA_BUCKET.delete(key));
    return jsonResponse({ error: "Object expired" }, 410);
  }

  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set("etag", object.httpEtag);
  headers.set("cache-control", `public, max-age=${Math.min(Math.max(0, Math.floor((expiresAt - now) / 1000)), 60)}`);

  return new Response(object.body, {
    status: 200,
    headers,
  });
}

async function proxyTelegramApi(request, env) {
  const base = env.TELEGRAM_API_BASE || "https://api.telegram.org";
  const incomingUrl = new URL(request.url);
  const upstreamUrl = new URL(incomingUrl.pathname + incomingUrl.search, base);
  const upstreamRequest = new Request(upstreamUrl.toString(), request);
  return fetch(upstreamRequest);
}

async function cleanupExpiredMedia(env) {
  assertConfigured(env);

  let cursor = undefined;
  const now = Date.now();

  do {
    const listing = await env.TEMP_MEDIA_BUCKET.list({
      prefix: "temp/",
      cursor,
    });

    const expiredKeys = [];
    for (const object of listing.objects) {
      const expiresAt = parseExpiresAtFromKey(object.key);
      if (expiresAt > 0 && expiresAt < now) {
        expiredKeys.push(object.key);
      }
    }

    if (expiredKeys.length > 0) {
      await env.TEMP_MEDIA_BUCKET.delete(expiredKeys);
    }

    cursor = listing.truncated ? listing.cursor : undefined;
  } while (cursor);
}

function buildObjectKey(expiresAt) {
  return `temp/${expiresAt}/${crypto.randomUUID()}.png`;
}

function parseExpiresAtFromKey(key) {
  const parts = key.split("/");
  if (parts.length < 3) {
    return 0;
  }
  const expiresAt = Number(parts[1]);
  return Number.isFinite(expiresAt) ? expiresAt : 0;
}

function clampTtl(requestedTtlHeader, configuredDefault) {
  const configuredTtl = Number(configuredDefault || DEFAULT_TTL_SECONDS);
  const requestedTtl = Number(requestedTtlHeader || configuredTtl);
  if (!Number.isFinite(requestedTtl) || requestedTtl <= 0) {
    return DEFAULT_TTL_SECONDS;
  }
  return Math.max(60, Math.min(requestedTtl, 3600));
}

function buildContentDisposition(filename) {
  const safeName = (filename || "image.png").replace(/[^a-zA-Z0-9._-]/g, "_");
  return `inline; filename="${safeName}"`;
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function timingSafeEqual(left, right) {
  if (left.length !== right.length) {
    return false;
  }
  let result = 0;
  for (let index = 0; index < left.length; index += 1) {
    result |= left.charCodeAt(index) ^ right.charCodeAt(index);
  }
  return result === 0;
}

async function signValue(secret, value) {
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(value));
  return bufferToHex(signature);
}

function bufferToHex(buffer) {
  return [...new Uint8Array(buffer)]
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

function assertConfigured(env) {
  if (!env.TEMP_MEDIA_BUCKET) {
    throw new Error("TEMP_MEDIA_BUCKET binding is not configured");
  }
  if (!env.TEMP_MEDIA_UPLOAD_TOKEN) {
    throw new Error("TEMP_MEDIA_UPLOAD_TOKEN secret is not configured");
  }
  if (!env.TEMP_MEDIA_SIGNING_SECRET) {
    throw new Error("TEMP_MEDIA_SIGNING_SECRET secret is not configured");
  }
}
