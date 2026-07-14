---
created: 2026-06-07
updated: 2026-07-14
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
| `daily-digest.sql` | Read-only queries that build the digest body | (piped into psql) |
| `daily-digest.sh` | Assembles + emails the digest; `--mode morning\|evening` | `chmod +x` |
| `send-digest.py` | stdlib `smtplib` sender (default transport, no install/sudo) | (called by the `.sh`) |
| `daily-digest.service` | Oneshot unit — `daily-digest.sh` (morning) | `systemctl --user link` |
| `daily-digest.timer` | Fires the morning digest daily at 07:00 | `systemctl --user enable --now` |
| `daily-digest-evening.service` | Oneshot unit — `daily-digest.sh --mode evening` | `systemctl --user link` |
| `daily-digest-evening.timer` | Fires the evening digest daily at 21:00 | `systemctl --user enable --now` |

Migration `postgres/migrations/014_night_digest.sql` adds `queue_night_digest()`,
called by the **evening** run to enqueue the overnight LLM narrative.

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

Two emails a day, same rich HTML, one `daily-digest.sh` with `--mode`:

- **Morning (07:00)** — `--mode morning` (default). The 24h stack summary
  (host health, sentinel alerts, error counts + top recurring failures, LLM-eval
  progress, eval board, GPU queue, commits) + **Today's focus** (top of the
  `## Next` list in `projects/home-ops.md`) + the **🌙 Overnight narrative**: an
  LLM briefing written on the GPU overnight (see below).
- **Evening (21:00)** — `--mode evening`. The same end-of-day snapshot, and it
  **queues the overnight narrative job** now that the win10 box is done gaming
  and the GPU is free. `queue_night_digest()` (migration 014) inserts one
  `summarise` `gpu_job` from the day's infra/eval/gpu/project state; the win10
  scheduler runs it overnight; the next morning's digest reads `result.summary`.
  Idempotent per day. If the GPU didn't finish, the morning card says so and the
  rest of the email is unaffected.

**Apply the migration once** (functions aren't re-run from `docker-entrypoint-initdb.d`
on an existing volume):

```bash
docker exec -i home-ops-postgres-1 psql -U postgres -d home_ops \
  < ~/logs-stack/postgres/migrations/014_night_digest.sql
```

**Steering the process.** There is no separate task store. To change what
tomorrow's digest features as *Today's focus*, reorder or edit the `## Next`
list in `projects/home-ops.md` in Obsidian (desktop or phone) — `planner-sync`
syncs it into the `projects` table within 60s. You can also tick items off from
the web console; the `task_toggles` writeback flows the change back to the vault.

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
