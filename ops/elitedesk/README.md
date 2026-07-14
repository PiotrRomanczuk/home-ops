---
created: 2026-06-07
updated: 2026-06-07
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
