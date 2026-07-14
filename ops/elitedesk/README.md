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
| `daily-digest.sh` | Assembles + emails the morning home-ops digest | `chmod +x` |
| `daily-digest.service` | Oneshot unit that runs `daily-digest.sh` | `systemctl --user link` |
| `daily-digest.timer` | Fires `daily-digest.service` daily at 07:00 | `systemctl --user enable --now` |

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

A morning email (07:00 Europe/Warsaw) summarising the stack over the last 24h:
host health, sentinel alerts, error counts + top recurring failures, LLM-eval
progress, the eval board, GPU queue, commits — and **Today's focus**, pulled
from the top of the `## Next` list in `~/Obsidian/MainCV-Planner/projects/home-ops.md`.

**Steering the process.** There is no separate task store. To change what
tomorrow's digest features as *Today's focus*, reorder or edit the `## Next`
list in `projects/home-ops.md` in Obsidian (desktop or phone) — `planner-sync`
syncs it into the `projects` table within 60s. You can also tick items off from
the web console; the `task_toggles` writeback flows the change back to the vault.

## Prerequisites — outbound mail via msmtp + Gmail

The digest sends through your own Gmail account over SMTP using an **app
password** (not your login password — requires 2FA enabled on the Google
account).

```bash
# 1. Install msmtp
sudo apt install -y msmtp

# 2. Create a Gmail app password:
#    Google Account → Security → 2-Step Verification → App passwords
#    → generate one for "Mail". Copy the 16-char value.

# 3. Write ~/.msmtprc (0600 — never world-readable, it holds the app password)
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

# 4. Sanity-check the transport
echo -e "Subject: msmtp test\n\nhello" | msmtp -a gmail p.romanczuk@gmail.com
```

## Config

```bash
cd ~/logs-stack
cp ops/elitedesk/daily-digest.env.example ops/elitedesk/daily-digest.env
# Edit DIGEST_TO / DIGEST_FROM / MSMTP_ACCOUNT to match the ~/.msmtprc account.
# daily-digest.env is gitignored — the mail password stays in ~/.msmtprc.
chmod +x ops/elitedesk/daily-digest.sh
```

## Test before scheduling

```bash
# Prints the full HTML message to stdout, sends nothing:
ops/elitedesk/daily-digest.sh --dry-run

# Send one for real to confirm the whole path:
ops/elitedesk/daily-digest.sh
```

## Install the timer

```bash
ln -sf ~/logs-stack/ops/elitedesk/daily-digest.service ~/.config/systemd/user/
ln -sf ~/logs-stack/ops/elitedesk/daily-digest.timer   ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now daily-digest.timer
systemctl --user list-timers --all | grep daily-digest

# 07:00 is interpreted in the host's timezone — confirm it's Europe/Warsaw:
timedatectl | grep 'Time zone'
```

`Persistent=true` means a missed 07:00 (box asleep/off) fires on next wake.
Requires `loginctl enable-linger <user>` (already set for the backup timer) so
`--user` timers run without an active login session.

## Verify

```bash
systemctl --user start daily-digest.service     # fire once now
journalctl --user -u daily-digest.service -n 30  # check the run (also lands in host_logs)
```
