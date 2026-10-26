#!/bin/sh
# Tofu (2026-10-25): this file is Tofu's addition; it is not part of upstream linkding.
#
# Starts a copy of linkding on Tofu (the Dockerfile's CMD). It does what upstream's bootstrap.sh does, with Tofu's
# settings (bookmarks/settings/tofu.py, which the image names), which read the database from DATABASE_URL:
#   1. PORT, which Tofu sets (80 without it), becomes LD_SERVER_PORT, and the server listens on all IPv4 addresses
#      (LD_SERVER_HOST 0.0.0.0) unless LD_SERVER_HOST is set.
#   2. Tofu (2026-10-26): `manage.py tofu_prepare_database` does everything the start does to the database, in one
#      Python process: upstream's secret key file, then, on PostgreSQL in one transaction that holds an advisory lock
#      (so that instances starting at the same moment take turns), `migrate` (a new database first gets linkding's
#      schema snapshot), row-level security on linkding's tables on a Supabase database, and upstream's
#      `create_initial_superuser`, which creates the first account once LD_SUPERUSER_PASSWORD is saved: named
#      LD_SUPERUSER_NAME, or admin without it, and nothing once that account exists. Tofu's database is new on the
#      first start, so a failure is retried a few times before the container gives up.
#   3. supervisord runs upstream's supervisord-all.conf: the web server (uwsgi, as upstream's uwsgi.ini says) and the
#      background tasks (Huey), both writing to the container's log.
# Upstream's migrate_tasks is left out: it moves the tasks of a linkding older than its Huey queue, kept in a SQLite
# file a copy never has.
set -eu

cd "$(dirname "$0")"

LD_SERVER_PORT=${PORT:-${LD_SERVER_PORT:-80}}
LD_SERVER_HOST=${LD_SERVER_HOST:-0.0.0.0}
export LD_SERVER_PORT LD_SERVER_HOST

# Upstream's folders. Nothing in them outlives a restart: the database keeps everything a copy has.
mkdir -p data data/favicons data/previews data/assets

if [ -n "${LD_SUPERUSER_PASSWORD:-}" ] && [ -z "${LD_SUPERUSER_NAME:-}" ]; then
	LD_SUPERUSER_NAME=admin
	export LD_SUPERUSER_NAME
fi

# Upstream's secret key file (Tofu's settings use LD_SECRET_KEY or a key derived from DATABASE_URL instead), then the
# database: see tofu_prepare_database.
attempt=1
until python manage.py tofu_prepare_database; do
	if [ "$attempt" -ge 5 ]; then
		echo "tofu-entrypoint: preparing the database failed $attempt times, giving up" >&2
		exit 1
	fi
	echo "tofu-entrypoint: preparing the database failed (attempt $attempt of 5), retrying in 5 seconds" >&2
	attempt=$((attempt + 1))
	sleep 5
done

# uwsgi's workers and the background tasks run as www-data (uwsgi.ini, supervisord-all.conf) and write the task queue
# into data/.
if [ "$(id -u)" = "0" ]; then
	chown -R www-data:www-data data
fi

exec supervisord -c supervisord-all.conf
