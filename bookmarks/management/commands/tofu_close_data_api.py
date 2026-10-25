# Tofu (2026-10-25): this file is Tofu's addition; it is not part of upstream linkding.
import logging

from django.core.management.base import BaseCommand
from django.db import connection

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Turn on row-level security for linkding's own tables on a Supabase database, "
        "so Supabase's Data API roles see none of their rows"
    )

    def handle(self, *args, **options):
        """
        Tofu's databases are Supabase PostgreSQL. On one whose default privileges still grant every new table in the
        public schema to the roles Supabase's Data API uses (anon and authenticated), anyone holding the project's public
        key could otherwise read and change linkding's tables through that API, accounts and sessions included. With
        row-level security on and no policy, those roles see no row, while linkding's own connection, which owns the
        tables, is not limited by it.

        It only ever turns row-level security on, and only for linkding's tables (its models' tables and Django's
        migration record) that linkding's role owns and that do not have it yet. On a database without those roles, or
        one that is not PostgreSQL, it does nothing.
        """
        if connection.vendor != "postgresql":
            return

        names = set(connection.introspection.django_table_names(include_views=False))
        # The record of applied migrations belongs to no app, so Django does not list it with the models' tables.
        names.add("django_migrations")

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('anon', 'authenticated'))"
            )
            if not cursor.fetchone()[0]:
                return

            cursor.execute(
                """
                SELECT c.relname
                FROM pg_class c
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public'
                  AND c.relkind IN ('r', 'p')
                  AND NOT c.relrowsecurity
                  AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)
                  AND c.relname = ANY(%s)
                ORDER BY c.relname
                """,
                [sorted(names)],
            )
            open_tables = [row[0] for row in cursor.fetchall()]

            for name in open_tables:
                cursor.execute(
                    f"ALTER TABLE public.{connection.ops.quote_name(name)} ENABLE ROW LEVEL SECURITY"
                )

        if open_tables:
            logger.info(
                f"Turned on row-level security for {len(open_tables)} of linkding's tables for Supabase's Data API"
            )
