FROM postgres:17

# pg_cron — scheduled prunes for host_logs (30d) and gpu_jobs (30d for done only).
# See postgres/migrations/002_pg_cron.sql for the scheduled jobs.
# Requires shared_preload_libraries=pg_cron + cron.database_name=home_ops
# (set via the `command:` override in docker-compose.yml).
RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-17-cron \
 && rm -rf /var/lib/apt/lists/*
