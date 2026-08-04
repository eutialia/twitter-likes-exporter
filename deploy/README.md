# Deployment Runbook — Likes Archive

Self-hosted deployment on a Proxmox unprivileged Debian 12 LXC.  
No Docker. Python managed by `uv`. Postgres on ZFS on the host; media on NFS.

---

## 1. Provision the LXC and NFS bind-mount

Create an unprivileged Debian 12 LXC in Proxmox. Add the NFS bind-mount to the container config:

```
# /etc/pve/lxc/<CTID>.conf
mp0: /mnt/nas/likes-media,mp=/mnt/media/likes,backup=0
```

Inside the container, `/mnt/media/likes` is `MEDIA_ROOT`. Both systemd units carry `RequiresMountsFor=/mnt/media/likes`, so they won't start until the mount is available.

Create the backup directory:

```bash
mkdir -p /mnt/media/likes/backups
chown likes:likes /mnt/media/likes/backups
```

---

## 2. Create the Postgres database (run once on the Postgres host)

Postgres runs on the Proxmox host against a ZFS-backed volume. The LXC connects over TCP via `DATABASE_URL`.

```sql
CREATE USER likes WITH PASSWORD '<password>';
CREATE DATABASE likes_archive OWNER likes;
```

> **PG15+ note:** `GRANT ALL ON DATABASE` no longer grants CREATE on `schema public`
> (behaviour changed in PostgreSQL 15, which Debian 12 ships). Making `likes` the
> database **owner** is the cleanest fix and lets Alembic create tables without
> additional schema-level grants.

---

## 3. Install the app

```bash
# As root in the LXC — create the service user
useradd -r -m -s /usr/sbin/nologin likes

# As the 'likes' user
su - likes -s /bin/bash
curl -Lsf https://astral.sh/uv/install.sh | sh
git clone <repo-url> /opt/likes-archive
cd /opt/likes-archive
uv sync --frozen        # installs runtime + dev deps from the lockfile
```

---

## 4. Install environment files

```bash
mkdir -p /etc/likes-archive

# Secrets (DATABASE_URL + X credentials) — mode 0600
cp deploy/env/secrets.env.example /etc/likes-archive/secrets.env
chmod 0600 /etc/likes-archive/secrets.env
chown likes:likes /etc/likes-archive/secrets.env
# Edit and fill in real values:
editor /etc/likes-archive/secrets.env

# Non-secret config — mode 0644
cp deploy/env/config.env.example /etc/likes-archive/config.env
chmod 0644 /etc/likes-archive/config.env
chown likes:likes /etc/likes-archive/config.env
# Edit MEDIA_ROOT and X_USER_ID at minimum:
editor /etc/likes-archive/config.env
```

---

## 5. Apply database migrations

```bash
cd /opt/likes-archive
# As the likes user (or root). Settings loads /etc/likes-archive/{secrets,config}.env
# automatically — same files the systemd units use — so no manual `source` is needed.
uv run likes-archive db upgrade
```

This runs `alembic upgrade head`. Re-run on every update (step 10).

---

## 6. One-time data migration (from legacy liked_tweets.json)

Only needed when migrating from the old two-script flow. Skip if this is a fresh installation.

```bash
uv run likes-archive migrate \
    --json /path/to/liked_tweets.json \
    --media-src /path/to/tweet_likes_html
```

See `uv run likes-archive migrate --help` for `--enrich`, `--skip-rsync`, and `--dry-run` options.

---

## 7. Install and enable systemd units

```bash
cp deploy/systemd/likes-web.service     /etc/systemd/system/
cp deploy/systemd/likes-scraper.service /etc/systemd/system/
cp deploy/systemd/likes-scraper.timer   /etc/systemd/system/

systemctl daemon-reload
systemctl enable --now likes-web.service
systemctl enable --now likes-scraper.timer
```

Check status:

```bash
systemctl status likes-web.service
systemctl status likes-scraper.timer
journalctl -u likes-web -f
```

---

## 8. Reverse proxy

The app binds plain HTTP on `PORT` (default 8000). Point your reverse proxy at `http://127.0.0.1:8000` and handle TLS termination, authentication, and access control there.

**nginx example** (minimal):

```nginx
server {
    listen 443 ssl;
    server_name likes.example.com;

    ssl_certificate     /etc/ssl/certs/likes.example.com.pem;
    ssl_certificate_key /etc/ssl/private/likes.example.com.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Optional: serve media files directly (zero Python overhead).
    # The FastAPI /media mount is the always-present fallback if you skip this.
    # location /media/ {
    #     alias /mnt/media/likes/;
    # }
}
```

---

## 9. Backups

Install the cron job (runs as the `likes` user):

```bash
cp deploy/cron/likes-archive-backup.cron /etc/cron.d/likes-archive-backup
chmod 0644 /etc/cron.d/likes-archive-backup
```

This runs `pg_dump | gzip` nightly at 03:00, writing to `MEDIA_ROOT/backups/`, and prunes dumps older than 30 days at 03:30. The NAS ZFS snapshot strategy covers the media files.

> The cron command strips the `+asyncpg` SQLAlchemy dialect suffix from
> `DATABASE_URL` before passing it to pg_dump (libpq only accepts
> `postgresql://` or `postgres://`). The backups directory is created
> automatically if it doesn't exist.

---

## 10. Updating

```bash
cd /opt/likes-archive
git pull
uv sync --frozen
uv run likes-archive db upgrade
systemctl restart likes-web.service
# The scraper timer will pick up the new binary on its next fire automatically.
```

---

## 11. Token refresh

When the X session expires (HTTP 401/403 from the scraper):

1. The scraper logs at `ERROR` and records `success=false` in `scrape_runs`.
2. The web UI shows a dismissible banner on `GET /` based on the latest `scrape_runs` row.
3. If `WEBHOOK_URL` is set, an ntfy-compatible POST is sent.

To refresh:

```bash
# Paste fresh Bearer/Cookie/CSRF values from browser DevTools
editor /etc/likes-archive/secrets.env

# The next timer fire re-reads Settings automatically.
# To trigger immediately:
systemctl start likes-scraper.service
```

No restart of `likes-web.service` is needed — `Settings` is re-read per scraper invocation.
