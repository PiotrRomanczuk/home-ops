---
created: 2026-06-08
updated: 2026-06-08
---

# home-ops event clients

Drop-in libraries for emitting `source = 'app:<slug>'` events to home-ops
from any project on the network. Each is a single file with stdlib only —
vendor by copying, no install step.

The whole point: surface project lifecycle and errors in the home-ops console
(Logs tab, Projects drill page) so cross-pillar correlation actually has
data flowing. Right now `app:<slug>` is documented as the join key between
`projects` and `host_logs`, but no project emits to it. These clients fix
that.

## Surfaces

| File | Stack | Vendor as |
| --- | --- | --- |
| `python/home_ops_log.py` | Python 3.10+, stdlib only | `lib/home_ops_log.py` |
| `node/home-ops-log.mjs` | Node 20+, ESM, fetch built-in | `lib/home-ops-log.mjs` |

## Setup (per consuming project)

1. Copy the relevant file into the project's `lib/` (or wherever).
2. Set env vars on the host where the project runs:
   ```
   INGEST_URL=http://elitedesk.tail266853.ts.net:64421/api/ingest
   INGEST_TOKEN=<same one the watchers use>
   # optional: HOME_OPS_HOST=mac        # default is os.hostname()
   ```
3. Call `init(slug)` once at process start with the project's planner slug
   (`'guitar-crm'`, `'stano'`, etc.). The slug becomes the `app:<slug>`
   source.

## Python — `home_ops_log.py`

```python
import home_ops_log as hops
hops.init('guitar-crm')

hops.event('stripe webhook received', data={'event_id': evt.id})
hops.event('twilio 429 rate-limited', level='error', data={'pid': os.getpid()})

with hops.lifecycle('send_reminders') as life:
    life.set_data({'count': len(batch)})
    for r in batch:
        send_one(r)
    # on clean exit:  emits send_reminders_succeeded with duration_ms + data
    # on exception:   emits send_reminders_failed and re-raises
```

## Node — `home-ops-log.mjs`

```js
import * as hops from './lib/home-ops-log.mjs';
hops.init('guitar-crm');

hops.event('stripe webhook received', { data: { event_id: evt.id } });

await hops.lifecycle('send_reminders', async (life) => {
  life.setData({ count: batch.length });
  for (const r of batch) await sendOne(r);
});
```

## What's a good lifecycle stage name?

Verbs in snake_case. The emitted events are `<stage>_started`,
`<stage>_succeeded`, `<stage>_failed`. Examples:

- `send_reminders` (cron job)
- `regenerate_cv` (build step)
- `scrape_offers` (scraper run)
- `process_webhook` (per-request)
- `embed_batch` (background work)

## Failure mode

Emits are best-effort. If the ingest API is unreachable or returns non-2xx,
the client logs to stderr and continues. The calling code never sees the
emit failure — keeps the integration invisible in the happy path and
recoverable when home-ops is down for whatever reason.

## What NOT to emit

- Don't emit on hot paths (per-request HTTP loops, tight ticks). Use it
  for *meaningful* lifecycle: webhook in, batch done, cron complete.
- Don't emit secrets in `data`. The console renders the jsonb verbatim.
- Don't emit huge blobs. The server caps `message` at 8k chars; keep
  `data` under a few KB.

## Sprinkle targets

The plan calls for sprinkling these into the three hot projects:

- `guitar-crm/` — Node client. Stripe webhook handlers, cron lesson
  reminder batches, no-show flag flips.
- `stano/` — Python or Node depending on the surface. Scrape start/end,
  SSE reconnect (one event, not the storm), backend errors.
- `job-search/cv_generator/` and `job-search/offers/pracuj/` — Python
  client. Regenerate, scrape, application send.

Each of those is a separate PR in its own project repo. The lib lives here.
