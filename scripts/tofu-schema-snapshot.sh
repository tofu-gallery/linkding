#!/bin/sh
# Tofu (2026-10-26): this file is Tofu's addition; it is not part of upstream linkding.
#
# Writes linkding's schema snapshot, bookmarks/tofu_schema.sql, which tofu_prepare_database loads into a database that
# has none of linkding's tables (see TOFU.md, "Start-up when several starts run at once"). Run it from the repository
# root, through /bin/sh, with Tofu's settings (DJANGO_SETTINGS_MODULE=bookmarks.settings.tofu), DATABASE_URL naming a
# new, empty PostgreSQL database, and pg_dump and psql on PATH; an optional argument names another output file. It
# applies linkding's migrations there the usual way, then writes the tables they made as pg_dump describes them (no
# owner, no privileges, no session settings, no psql commands), row-level security with no policy on each of them, as
# tofu_close_data_api turns it on, and Django's record of the migrations it applied. The image never runs it.
set -eu

out=${1:-bookmarks/tofu_schema.sql}
python manage.py migrate --noinput >&2
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
{
	echo "-- Tofu (2026-10-26): this file is Tofu's addition; it is not part of upstream linkding."
	echo "-- linkding's tables as its migrations leave a new PostgreSQL database, and Django's record of those"
	echo "-- migrations. tofu_prepare_database sends it in one round trip to a database with none of linkding's tables,"
	echo "-- inside the transaction that holds the start's advisory lock. Written by scripts/tofu-schema-snapshot.sh"
	echo "-- (Django $(python -c 'import django; print(django.get_version())'), pg_dump --schema-only --no-owner --no-privileges --schema=public)."
	pg_dump --schema-only --no-owner --no-privileges --schema=public "$DATABASE_URL" |
		grep -v -E '^(SET |SELECT pg_catalog\.set_config|CREATE SCHEMA |COMMENT ON SCHEMA |--|\\(un)?restrict )' |
		cat -s
	echo "-- Row-level security, with no policy, on every table (TOFU.md, \"The database's Data API\")."
	psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL" -c "
		SELECT format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY;', c.relname)
		FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname"
	echo
	psql -X -At -v ON_ERROR_STOP=1 "$DATABASE_URL" -c "
		SELECT 'INSERT INTO public.django_migrations (app, name, applied) VALUES' || E'\n'
			|| string_agg(format('(%L, %L, now())', app, name), E',\n' ORDER BY id) || ';'
		FROM django_migrations"
} > "$tmp"
cp "$tmp" "$out"
echo "wrote $out: $(grep -c '^CREATE TABLE' "$out") tables, $(grep -c 'ENABLE ROW LEVEL SECURITY' "$out") with row-level security, $(grep -c 'now())' "$out") migrations" >&2
