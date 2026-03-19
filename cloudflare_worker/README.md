# Cloudflare Worker Gateway

This Worker keeps the existing Telegram Bot API proxy behavior and adds a temporary PNG delivery flow for `sendPhoto(url)`.

## What it does

- Proxies all non-`/temp-media` requests to Telegram Bot API.
- Accepts raw PNG uploads on `POST /temp-media`.
- Stores PNGs in a private R2 bucket with a short TTL.
- Returns a signed temporary URL that Telegram can fetch directly.
- Cleans up expired files from R2 on a cron schedule.

## Required bindings and secrets

- `TEMP_MEDIA_BUCKET` - private R2 bucket for short-lived PNGs.
- `TEMP_MEDIA_UPLOAD_TOKEN` - bearer token used by the bot for uploads.
- `TEMP_MEDIA_SIGNING_SECRET` - secret used to sign temporary download URLs.

## Required vars

- `TELEGRAM_API_BASE` - defaults to `https://api.telegram.org`.
- `TEMP_MEDIA_TTL_SECONDS` - default link lifetime in seconds, recommended `300`.

## Setup

1. Create an R2 bucket, for example `podval-temp-media`.
2. Copy `wrangler.toml.example` to `wrangler.toml` and adjust names if needed.
3. Add secrets:
   - `wrangler secret put TEMP_MEDIA_UPLOAD_TOKEN`
   - `wrangler secret put TEMP_MEDIA_SIGNING_SECRET`
4. Deploy the Worker:
   - `wrangler deploy`

## Bot env

Set these env vars for the Python bot:

- `TEMP_MEDIA_ENABLED=true`
- `TEMP_MEDIA_UPLOAD_URL=https://<your-worker-domain>/temp-media`
- `TEMP_MEDIA_UPLOAD_TOKEN=<same token as Worker secret>`
- `TEMP_MEDIA_TTL_SECONDS=300`
- `TEMP_MEDIA_UPLOAD_TIMEOUT=30`

## Smoke test

Upload a PNG directly:

```bash
curl -X POST "https://<your-worker-domain>/temp-media" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: image/png" \
  -H "X-TTL-Seconds: 300" \
  --data-binary @test.png
```

Expected result: JSON with `url`, `key`, and `expires_at`.

Then open the returned `url` in a browser. The image should load before expiry and fail after expiry.
