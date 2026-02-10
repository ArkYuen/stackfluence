# Stackfluence

**Influencer measurement infrastructure — from click to conversion, cleanly.**

Stackfluence captures influencer-driven traffic at the click, generates durable signed click IDs, and provides a normalized event stream that brands can match to on-site sessions and conversions.

## Architecture

```
Creator's Link                Stackfluence Wrapper              Advertiser Site
─────────────────           ─────────────────────────         ──────────────────
stackfluence.com/c/         1. Look up link                   Landing page with
  {creator}/                2. Score bot risk                  ?inf_click_id=...
  {campaign}/               3. Mint signed click_id            │
  {asset?}                  4. Log click event (server-side)   ├─ sf.js snippet
       │                    5. 302 redirect ──────────────────►│   fires session +
       │                                                       │   pageview events
       │                    Event Ingestion API                │
       │                    ◄──────────────────────────────────┤
       │                    POST /v1/events/conversion         │
       │                    POST /v1/events/session            │
       │                    POST /v1/events/pageview           │
       │                                                       │
       ▼                    ▼                                  │
   Click Event ──► Event Store (append-only) ◄─────────────────┘
                    │
                    ├─► Qualified Session computation
                    ├─► Billing policy engine
                    └─► Exports (CSV / BigQuery / Snowflake)
```

## Key Design Decisions

- **Identity is event-based, not cookie-based.** Works with Safari ITP, in-app browsers, cross-device.
- **Click IDs are HMAC-signed with expiry.** Downstream events with invalid signatures are non-billable.
- **Bot detection scores, doesn't block.** Suspicious traffic is flagged; billing policy decides what counts.
- **Append-only event store.** Raw events are immutable; derivations are computed separately.

## Project Structure

```
stackfluence/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Environment config (pydantic-settings)
│   ├── api/
│   │   ├── redirect.py      # GET /c/{creator}/{campaign} — the hot path
│   │   ├── events.py        # POST /v1/events/* — advertiser event ingestion
│   │   └── links.py         # CRUD for tracked links
│   ├── core/
│   │   ├── click_id.py      # HMAC-signed click ID minting + verification
│   │   └── bot_detection.py # Layer 1 bot scoring (UA, headers, ASN, rate limits)
│   └── models/
│       ├── database.py      # Async SQLAlchemy engine + sessions
│       └── tables.py        # All database models (entities + events)
├── static/
│   └── sf.js                # Advertiser JS snippet (drop-in or GTM)
├── tests/
│   ├── test_click_id.py     # Click ID signing/verification tests
│   └── test_bot_detection.py# Bot scoring tests
├── docker-compose.yml       # Local dev: Postgres + Redis + app
├── Dockerfile
├── requirements.txt
└── .env.example
```

## Quickstart

```bash
# 1. Clone and set up
cp .env.example .env
# Edit .env — at minimum, set SF_CLICK_ID_SECRET to a real secret

# 2. Start services
docker-compose up -d

# 3. Run migrations (after Alembic setup)
# alembic upgrade head

# 4. Create a test link via API
curl -X POST http://localhost:8000/v1/links \
  -H "Content-Type: application/json" \
  -d '{
    "organization_id": "...",
    "creator_id": "...",
    "campaign_id": "...",
    "creator_handle": "emma",
    "campaign_slug": "summer-drop",
    "destination_url": "https://brand.com/collection"
  }'

# 5. Test the redirect
curl -v http://localhost:8000/c/emma/summer-drop
# → 302 redirect to https://brand.com/collection?inf_click_id=<signed_id>
```

## Advertiser Integration

### Option 1: JS Snippet
```html
<script src="https://cdn.stackfluence.com/sf.js"
        data-org="YOUR_ORG_ID"
        data-endpoint="https://api.stackfluence.com"></script>
```

Track conversions:
```js
sfq('conversion', {
  event_type: 'purchase',
  order_id: 'ORD-123',
  revenue_cents: 4999,
  currency: 'USD'
});
```

### Option 2: Server-to-Server
```bash
curl -X POST https://api.stackfluence.com/v1/events/conversion \
  -H "Content-Type: application/json" \
  -d '{
    "inf_click_id": "...",
    "organization_id": "...",
    "event_type": "purchase",
    "order_id": "ORD-123",
    "revenue_cents": 4999
  }'
```

## What's Next (MVP Roadmap)

- [ ] Alembic migrations
- [ ] Redis rate limiting middleware
- [ ] GeoIP integration (MaxMind) for country + ASN
- [ ] Qualified Session computation + dedupe engine
- [ ] Stripe metered billing integration
- [ ] Shopify app connector
- [ ] Dashboard (React frontend)
- [ ] CSV + BigQuery export
