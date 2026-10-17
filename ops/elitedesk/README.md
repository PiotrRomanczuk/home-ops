---
created: 2026-06-07
updated: 2026-10-17
---

# ops/elitedesk — host-side unit files for the elitedesk deployment

These are systemd `--user` units that run on `elitedesk` alongside the docker-compose
stack. They're version-controlled here; installed by symlinking into
`~/.config/systemd/user/`.

| File | What | Install pattern |
| --- | --- | --- |
| `pg-backup.sh` | Nightly `pg_dump -Fc` of `home_ops` → `/mnt/nas/monitoring-backup/home-ops/` | `chmod +x` |
| `pg-backup.service` | Oneshot unit that runs `pg-backup.sh` | `systemctl --user link` |
| `pg-backup.timer` | Fires `pg-backup.service` daily at 04:30 | `systemctl --user enable --now` |
| `daily-digest.sh` | Fetches `GET /api/digest`, renders, emails; `--mode morning\|evening` | `chmod +x` |
| `render-digest.py` + `digest_html.py` | Pure JSON model → email-safe HTML (tests in `tests/`) | (called by the `.sh`) |
| `send-digest.py` | stdlib `smtplib` sender (default transport, no install/sudo) | (called by the `.sh`) |
| `daily-digest.service` | Oneshot unit — `daily-digest.sh` (morning) | `systemctl --user link` |
| `daily-digest.timer` | Fires the morning digest daily at 07:00 | `systemctl --user enable --now` |
| `daily-digest-evening.service` | Oneshot unit — `daily-digest.sh --mode evening` | `systemctl --user link` |
| `daily-digest-evening.timer` | Fires the evening digest daily at 21:00 | `systemctl --user enable --now` |
| `seo-collect.py` | Daily Search Console / GA4 / Places snapshot → `POST /api/seo/ingest` | (run by the unit) |
| `seo_google.py`, `seo_sources.py` | Service-account JWT via `openssl`; per-source fetch + row shaping | (imported) |
| `seo-collect.sites.json` | Sites (GSC property, GA4 property, tracked events) + Places entries | edit in repo |
| `seo-collect.service` | Oneshot unit that runs `seo-collect.py` | `systemctl --user link` |
| `seo-collect.timer` | Fires `seo-collect.service` daily at 06:00 | `systemctl --user enable --now` |
| `seo-analyse.py` | 06:30 — 7d-vs-7d metrics + district breakdown → `digest.d/seo-<site>.txt` + `seo_analysis_daily` (+ headless Claude narrative) | (run by the unit) |
| `seo_metrics.py`, `seo_render.py`, `seo_llm.py` | Pure computations (tested), plain-text card, `claude -p` wrapper | (imported) |
| `seo-districts.json` | Query → district/metro-line regex classifier (right bank + M2 + central M1) | edit in repo |
| `seo-analyse.prompt.md`, `seo-improve.prompt.md` | Analyst / editor prompts for headless Claude | edit in repo |
| `seo-analyse.service` / `.timer` | Oneshot + daily 06:30 | `systemctl --user link` / `enable --now` |
| `seo-improve.sh` | Monday 06:45 — headless Claude edits a clone of gitara-lekcje, runs its gates, opens a `seo-auto` PR (never merges) | `chmod +x` |
| `seo-improve.service` / `.timer` | Oneshot + weekly Monday 06:45 | `systemctl --user link` / `enable --now` |
| `brief-pull.py` + `brief_parse.py` | Every 15 min — `git pull` the daily-brief repo, POST new/changed `briefs/*.md` to `/api/briefs` (tests in `tests/`) | (run by the unit) |
| `brief-pull.service` / `.timer` | Oneshot + every 15 min | `systemctl --user link` / `enable --now` |
| `brief-pull.env.example` | Template for `~/.config/home-ops/brief-pull.env` (all optional) | copy, `chmod 600` |

Migrations `020_digest_cards.sql` + `021_decisions.sql` add the routine
contract the digest renders (see "Daily digest email" below). Migration 014's
`queue_night_digest()` is no longer called: the GPU lane is off.

## Prerequisites — NAS mount

`pg-backup.sh` writes to `/mnt/nas/monitoring-backup/home-ops/`. The share
must be mounted before the timer fires. If not yet set up:

```bash
# As root on elitedesk, one-time setup
sudo mkdir -p /mnt/nas/monitoring-backup
sudo apt install -y cifs-utils
sudo install -m 600 -o root -g root /dev/null /etc/kuma-backup/credentials
# Put the kuma-backup user's NAS password into /etc/kuma-backup/credentials:
#   username=kuma-backup
#   password=<from password manager>
# (Reuses the same SMB user the Pi already authenticates as.)

# /etc/fstab
//192.168.1.25/monitoring-backup /mnt/nas/monitoring-backup cifs \
  credentials=/etc/kuma-backup/credentials,uid=$(id -u <user>),gid=$(id -g <user>),file_mode=0640,dir_mode=0750,_netdev,nofail 0 0

sudo mount -a
mkdir -p /mnt/nas/monitoring-backup/home-ops
```

Reuses the existing `monitoring-backup` SMB share documented in
`~/Desktop/MainCV/infrastructure/HOSTS.md` (Pi backs Kuma into the same share).

## Install the timer

```bash
# After git clone has finished and the stack is running
cd ~/logs-stack
chmod +x ops/elitedesk/pg-backup.sh

# Symlink (not copy) so future `git pull` updates the unit files in place.
ln -sf ~/logs-stack/ops/elitedesk/pg-backup.service ~/.config/systemd/user/
ln -sf ~/logs-stack/ops/elitedesk/pg-backup.timer   ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now pg-backup.timer
systemctl --user list-timers --all | grep pg-backup
```

If you need the timer to fire even when nobody is logged in (typical for a
headless box that doesn't keep a user session alive), enable lingering once:

```bash
loginctl enable-linger <user>
```

## Verify

```bash
# Trigger one immediately to test
systemctl --user start pg-backup.service
journalctl --user -u pg-backup.service -n 30

# Confirm the dump exists and is restorable
ls -lh /mnt/nas/monitoring-backup/home-ops/
docker run --rm -i postgres:17 pg_restore --list < /mnt/nas/monitoring-backup/home-ops/home_ops_*.dump | head
```

---

# Daily digest email

_updated: 2026-10-13 — rewritten around routine cards + decisions._

The email answers two questions on a phone at 07:00: **did something break**
and **what needs me**. Everything else lives in the console.

```
daily-digest.sh ──GET /api/digest──▶ JSON model ──render-digest.py──▶ HTML ──▶ smtplib / msmtp
```

Sections, each shown only when it has content:

| Section | Source |
| --- | --- |
| Verdict (also the subject line) | computed by `/api/digest` |
| **Needs you** — open decisions with one-tap buttons | `decisions` (migration 021) |
| **Needs attention** — recurring problems, one per source, with "since" | `host_logs` errors grouped by source + host; known noise muted in `routes/digest.ts` |
| Hosts — one line each; logs-only host names collapsed | `host_metrics` + `host_logs` |
| Your sites — DOWN / RECOVERED transitions | rpi-sentinel `app:<slug>` events (`host='rpi'`) |
| Today — focus + 3 next titles | Board focus / vault `## Next` |
| **Routines** — latest card per routine, trend, acceptance | `digest_cards` (migration 020) |
| Overnight / extras | narrative (if any) + `digest.d/*.txt` **younger than 26 h** |

## How a routine reports

Every routine ends its run with one card, and asks before anything public or
irreversible. From bash:

```bash
python3 -m agents.routine_report card seo-analyse "Traffic flat, 2 hypotheses added" \
  --item "H3: district pages|https://…" --metric "crawl findings=17" --delta -2 --lower-is-better
python3 -m agents.routine_report ask seo-improve "Merge the weekly SEO PR #53?" \
  --ref 53 --context https://github.com/…/pull/53 --option yes:Merge --option no:Skip --skip-if-open
python3 -m agents.routine_report answers seo-improve      # next run: act on these
python3 -m agents.routine_report consume seo-improve <id> # then mark done
```

From Python: `agents.routine_report.Reporter`. From a headless Claude: the MCP
tools `post_digest_card`, `create_decision`, `list_decisions`, `consume_decision`.

**Rule of thumb:** ask only when the effect is public or irreversible
(publish, merge, send). Drafts, analyses and reports just get a card.

## Decision links

Buttons in the email are signed links (`/d/<id>/<option>/<exp>/<sig>`, HMAC
keyed by `DECISION_SECRET`, default derived from `INGEST_TOKEN`). Opening one
shows a confirmation page; only the POST from that page records the answer,
so mail-client link prefetching can never answer for you. "No" asks for a
one-line reason; reasons feed the per-routine acceptance line. Set
`PUBLIC_BASE_URL` in `.env` to the console URL reachable from the phone
(LAN or Tailscale), then `docker compose up -d --build ingest`.

## Prerequisites — outbound mail

The digest sends through your own Gmail account over SMTP using an **app
password** (not your login password — requires 2-Step Verification on the
account: Google Account → Security → 2-Step Verification → App passwords →
"Mail" → copy the 16-char value).

Two transports are supported, selected by `DIGEST_TRANSPORT` in the env file.

### Default — `smtplib` (no install, no sudo)

Uses Python's standard library (already on elitedesk). The app password lives in
a `0600` file that the sender reads at send time; it is never placed in an env
var or committed.

```bash
mkdir -p ~/.config/home-ops
# Paste the 16-char app password with hidden input, no shell-history trace:
read -rs APPPW
printf '%s' "$APPPW" > ~/.config/home-ops/smtp.pass
chmod 600 ~/.config/home-ops/smtp.pass
unset APPPW
```

### Alternative — `msmtp` (set `DIGEST_TRANSPORT=msmtp`)

```bash
sudo apt install -y msmtp
install -m 600 /dev/null ~/.msmtprc
cat > ~/.msmtprc <<'RC'
defaults
auth           on
tls            on
tls_trust_file /etc/ssl/certs/ca-certificates.crt
logfile        ~/.msmtp.log

account        gmail
host           smtp.gmail.com
port           587
from           p.romanczuk@gmail.com
user           p.romanczuk@gmail.com
password       <16-char-app-password>

account default : gmail
RC
chmod 600 ~/.msmtprc
```

## Config

```bash
cd ~/logs-stack
cp ops/elitedesk/daily-digest.env.example ops/elitedesk/daily-digest.env
# Set DIGEST_TO / DIGEST_FROM. Leave DIGEST_TRANSPORT=smtplib (default) unless
# you set up msmtp above. daily-digest.env is gitignored; the password lives in
# ~/.config/home-ops/smtp.pass (smtplib) or ~/.msmtprc (msmtp), never in the env.
chmod +x ops/elitedesk/daily-digest.sh
```

## Test before scheduling

```bash
# Prints the full HTML message to stdout, sends nothing (evening also reports
# that it WOULD queue the overnight narrative, but doesn't mutate anything):
ops/elitedesk/daily-digest.sh --dry-run                 # morning
ops/elitedesk/daily-digest.sh --mode evening --dry-run  # evening

# Send one for real to confirm the whole path:
ops/elitedesk/daily-digest.sh                 # morning
ops/elitedesk/daily-digest.sh --mode evening  # evening (also queues the night job)
```

## Install the timer

```bash
# Morning + evening — symlink both service/timer pairs
ln -sf ~/logs-stack/ops/elitedesk/daily-digest.service         ~/.config/systemd/user/
ln -sf ~/logs-stack/ops/elitedesk/daily-digest.timer           ~/.config/systemd/user/
ln -sf ~/logs-stack/ops/elitedesk/daily-digest-evening.service ~/.config/systemd/user/
ln -sf ~/logs-stack/ops/elitedesk/daily-digest-evening.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daily-digest.timer daily-digest-evening.timer
systemctl --user list-timers --all | grep daily-digest

# 07:00 / 21:00 are interpreted in the host's timezone — confirm it's Europe/Warsaw:
timedatectl | grep 'Time zone'
```

`Persistent=true` means a missed 07:00 (box asleep/off) fires on next wake.
Requires `loginctl enable-linger <user>` (already set for the backup timer) so
`--user` timers run without an active login session.

## Verify

```bash
systemctl --user start daily-digest.service          # fire the morning digest now
systemctl --user start daily-digest-evening.service  # fire the evening digest (queues the night job)
journalctl --user -u daily-digest.service -u daily-digest-evening.service -n 40
```

---

# seo-collect — daily search-visibility snapshot

_Added 2026-10-07._ Feeds `seo_gsc_daily`, `seo_ga4_daily` and `seo_places_daily`
(migration `017_seo.sql`) for gitarawarszawa.pl and romanczuk.online — the raw
material for weekly SEO reports.

## One-time Google setup (done by hand — keys never go through the repo)

1. Google Cloud project (e.g. `home-ops-seo`) → enable **Google Search Console API**,
   **Google Analytics Data API** and (optionally) **Places API (New)**.
2. Create a service account → **Keys → Add key → JSON**. Copy it to
   `~/code/logs-stack/ops/elitedesk/seo-sa.json`, `chmod 600` (gitignored as `*-sa.json`).
3. Add the service account's e-mail as a **Restricted** user on each Search Console
   property and as **Viewer** on each GA4 property listed in `seo-collect.sites.json`.
4. Optional: an API key restricted to *Places API (New)* → `PLACES_API_KEY`. Six
   lookups/day stay inside the free monthly usage cap.

## Config + test run

```bash
cd ~/code/logs-stack
cp ops/elitedesk/seo-collect.env.example ops/elitedesk/seo-collect.env && chmod 600 ops/elitedesk/seo-collect.env
# fill INGEST_TOKEN (same as the other agents), SEO_SA_JSON, PLACES_API_KEY
set -a; . ops/elitedesk/seo-collect.env; set +a; python3 ops/elitedesk/seo-collect.py
```

Prints `{"summary": {...}, "failed": [...]}`. A source without credentials is skipped
with a `warn` in `host_logs`; an API error exits 1.

## Install the timer

```bash
ln -sf ~/code/logs-stack/ops/elitedesk/seo-collect.service ~/.config/systemd/user/
ln -sf ~/code/logs-stack/ops/elitedesk/seo-collect.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now seo-collect.timer
```

## Verify

```sql
SELECT site, max(day), count(*) FROM seo_gsc_daily GROUP BY site;
SELECT site, day, sum(sessions), jsonb_object_agg(source_medium, events) FROM seo_ga4_daily GROUP BY 1, 2 ORDER BY 2 DESC LIMIT 7;
SELECT label, day, rating, review_count FROM seo_places_daily ORDER BY day DESC, label;
```

`gitarawarszawa.pl` is configured as a URL-prefix GSC property (`https://gitarawarszawa.pl/`).
If it turns out to be a domain property, change `gsc` to `sc-domain:gitarawarszawa.pl`.

---

# SEO routine (gitarawarszawa.pl)

Three units, one pipeline, all driven by `seo-collect.env`:

| When | Unit | What | Output |
| --- | --- | --- | --- |
| 06:00 | `seo-collect` | Search Console (7-day rolling window), GA4, Places → `POST /api/seo/ingest` | `seo_gsc_daily`, `seo_ga4_daily`, `seo_places_daily` (017) |
| 06:30 | `seo-analyse` | 7d vs previous 7d, district + metro-line breakdown, adaptive opportunities; **own-site crawl** → snapshots + rule findings (drift, CTA coverage); **plan evaluation** (in_pr → shipped on PR merge; 14/28-day verdicts vs baseline + control pages); `claude -p` narrative + validated ```plan-updates``` JSON applied to `seo_plan` | `digest.d/seo-gitarawarszawa-pl.txt` → 07:00 e-mail; `seo_analysis_daily` (018); `seo_plan`, `seo_page_snapshot`, `seo_findings` (019) |
| Mon 06:45 | `seo-improve` | takes up to 3 `ready` hypotheses from `seo_plan`, headless Claude edits `~/code/gitara-lekcje`, gates (`lint` + `typecheck` + `test`) **and an LLM-as-judge pass on the diff** (facts from `lib/site.ts`, scope, thin content), opens PR labelled `seo-auto`, rows → `in_pr` | a PR for Piotr to review — **never auto-merged** |

Degradation is explicit: no service-account key → collector skips Google with a
warning; Claude CLI logged out → the card still ships, narrative column stays
NULL and the journal says why; gates red → `seo-improve` discards the diff and
exits 1 (no push).

## Install

```bash
cd ~/code/logs-stack && git pull
docker exec -i home-ops-postgres-1 psql -U postgres -d home_ops -v ON_ERROR_STOP=1 \
  -f postgres/migrations/017_seo.sql -f postgres/migrations/018_seo_analysis.sql -f postgres/migrations/019_seo_plan.sql
docker compose up -d --build ingest            # /api/seo/ingest route
cp ops/elitedesk/seo-collect.env.example ops/elitedesk/seo-collect.env && chmod 600 ops/elitedesk/seo-collect.env
# fill INGEST_TOKEN (same as .env), SEO_SA_JSON path once the key exists
for u in seo-collect seo-analyse seo-improve; do
  ln -sf ~/code/logs-stack/ops/elitedesk/$u.service ~/.config/systemd/user/
  ln -sf ~/code/logs-stack/ops/elitedesk/$u.timer   ~/.config/systemd/user/
done
systemctl --user daemon-reload
systemctl --user enable --now seo-collect.timer seo-analyse.timer seo-improve.timer
claude login                                  # once; headless runs reuse the session
```

Google side (one-time, in the Cloud console): create a service account, download
its JSON key to `ops/elitedesk/seo-sa.json` (chmod 600, gitignored), enable
**Search Console API** and **Google Analytics Data API** on the project, add the
service-account e-mail as a *restricted* user of the GSC property and as *Viewer*
on the GA4 property.

## Verify

```bash
systemctl --user start seo-collect.service && journalctl --user -u seo-collect -n 20
systemctl --user start seo-analyse.service && cat ops/elitedesk/digest.d/seo-gitarawarszawa-pl.txt
docker exec -i home-ops-postgres-1 psql -U postgres -d home_ops -c \
  "select day, model, length(narrative) from seo_analysis_daily order by day desc limit 5"
bash ops/elitedesk/seo-improve.sh --dry-run | head -40   # prints the prompt, edits nothing
```

## Plan as state (`seo_plan`)

```
proposed ──(LLM/Piotr: ready)──▶ ready ──(seo-improve: PR)──▶ in_pr ──(PR merged)──▶ shipped
    │                                                                              │
    └──────── retire ◀─────────────────────────────── helped | hurt | neutral ◀────┘ (day28 verdict)
```

Piotr can edit the plan by hand: `UPDATE seo_plan SET status='ready' WHERE id=…;` or insert a row with
`source='piotr'`. Verdicts need ≥ 10 impressions per window; the control group is every GSC row no
shipped hypothesis targets, so a site-wide lift isn't credited to one change.

---

# Daily briefs (brief-pull) — feeds the console's „Dziś” tab

Contract + reasoning: `docs/adr/2026-10-17-daily-briefs.md`. A cloud routine
commits `briefs/YYYY-MM-DD-<slot>.md` to the private repo
`PiotrRomanczuk/daily-brief`; this host pulls it every 15 min and upserts each
brief via `POST /api/briefs`. Needs migration `022_daily_briefs.sql`.

## One-time setup: read-only deploy key (by hand, on elitedesk)

```bash
ssh-keygen -t ed25519 -N '' -C 'uwh brief-pull (read-only)' -f ~/.ssh/daily_brief_deploy
cat >> ~/.ssh/config <<'CFG'

Host github-daily-brief
  HostName github.com
  User git
  IdentityFile ~/.ssh/daily_brief_deploy
  IdentitiesOnly yes
CFG
# From the Mac (gh logged in): add the PUBLIC key as a read-only deploy key.
#   ssh uwh cat .ssh/daily_brief_deploy.pub > /tmp/daily_brief_deploy.pub
#   gh repo deploy-key add /tmp/daily_brief_deploy.pub -R PiotrRomanczuk/daily-brief -t uwh-brief-pull
# (no --allow-write → read-only)
ssh -T github-daily-brief   # expect: "Hi PiotrRomanczuk/daily-brief! … does not provide shell access"
```

## Install

```bash
mkdir -p ~/.config/home-ops && cp ops/elitedesk/brief-pull.env.example ~/.config/home-ops/brief-pull.env
chmod 600 ~/.config/home-ops/brief-pull.env      # defaults are fine; INGEST_* come from elitedesk-watcher.env
python3 ops/elitedesk/brief-pull.py               # first run clones ~/code/daily-brief and backfills ≤120 days
systemctl --user link ~/code/logs-stack/ops/elitedesk/brief-pull.service ~/code/logs-stack/ops/elitedesk/brief-pull.timer
systemctl --user enable --now brief-pull.timer
```

## Verify

```bash
systemctl --user list-timers brief-pull.timer
journalctl --user -u brief-pull.service -n 20
docker exec home-ops-postgres-1 psql -U postgres -d home_ops \
  -c "SELECT brief_date, slot, title, generated_at FROM daily_briefs ORDER BY brief_date DESC LIMIT 4"
curl -s -H "X-Ingest-Token: $INGEST_TOKEN" http://127.0.0.1:64421/api/today | head -c 600
```

Re-send everything (harmless, upserts): `rm ~/.local/state/home-ops/brief-pull.state`.
A malformed brief is skipped and logged as `agent:brief-pull` error (visible in
the „Dziś” tab under Problemy); network/5xx failures retry on the next tick.

