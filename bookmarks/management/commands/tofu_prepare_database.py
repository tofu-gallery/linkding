# Tofu (2026-10-26): this file is Tofu's addition; it is not part of upstream linkding.
import logging
import re
import time
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import DatabaseError, connection, transaction

logger = logging.getLogger(__name__)

# The advisory lock every start of a copy takes before it touches the schema: the same number in every start
# (b"linkding" read as a 64-bit integer).
LOCK_KEY = 7811896436176023143
# How long a start waits for another start's schema step before it gives up; tofu-entrypoint.sh then tries again.
LOCK_WAIT = "120s"
# linkding's tables as its migrations leave a new database, with Django's record of those migrations
# (scripts/tofu-schema-snapshot.sh makes it).
SNAPSHOT = Path(__file__).resolve().parents[2] / "tofu_schema.sql"
# An object another start made first: unique_violation (two starts creating the same table or type), duplicate_table,
# duplicate_object.
DUPLICATE_SQLSTATES = {"23505", "42P07", "42710"}


def _sqlstate(error):
    while error is not None:
        sqlstate = getattr(error, "sqlstate", None)
        if sqlstate:
            return sqlstate
        error = error.__cause__ or error.__context__
    return None


def snapshot_migrations():
    """The (app, name) of every migration the snapshot records as applied."""
    return re.findall(r"\('([a-z_]+)', '([0-9a-z_]+)', now\(\)\)", SNAPSHOT.read_text())


class Command(BaseCommand):
    help = (
        "Everything a start does to the database, for Tofu's copy of linkding: on PostgreSQL in one transaction "
        "that holds an advisory lock, so that starts running at the same moment take turns"
    )

    def handle(self, *args, **options):
        """
        Tofu's container hosting can start several instances of a new deployment within the same second, each on its
        own disk, all with the same new database. Each start used to run migrate, then turn on row-level security,
        then create the first account, and starts running at the same moment failed on the tables and types another
        start was creating.

        Here, on PostgreSQL, one transaction does all of it: its first statement takes a transaction-level advisory
        lock (pg_advisory_xact_lock), so one start does the work while the others wait, and each of them then finds it
        done. Tofu's DATABASE_URL goes through a transaction pooler, which keeps a client on one server connection for
        exactly one transaction: a lock that lasts as long as the transaction holds through it, and the pooler cannot
        hand that server connection to anybody else before the transaction ends and the lock goes with it. A
        session-level lock would not hold there. PostgreSQL's DDL is transactional, so Django's migrations, each in its
        own savepoint, commit together with everything else or not at all.

        After the lock, and only then, it reads what the database holds. A database with none of linkding's tables in
        public gets them from the schema snapshot in one round trip instead of 76 migrations sent statement by statement;
        then migrate applies whatever the snapshot does not record (on this version, nothing), Django adds its
        content types and permissions, row-level security goes on for every table of linkding's, and the first
        account is created once LD_SUPERUSER_NAME is set. A start that meets an object another start made first
        anyway, which the lock should never let happen, rolls back and tries the whole step once more.
        """
        call_command("generate_secret_key")

        if connection.vendor != "postgresql":
            # Upstream's steps, unchanged: a SQLite file is one container's own.
            call_command("migrate", interactive=False)
            call_command("enable_wal")
            call_command("create_initial_superuser")
            return

        try:
            self.prepare()
        except DatabaseError as error:
            if _sqlstate(error) not in DUPLICATE_SQLSTATES:
                raise
            logger.warning(
                f"tofu-prepare: another start made an object first ({error}); trying once more"
            )
            self.prepare()

    def prepare(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                started = time.monotonic()
                # A wait for another start's schema step is bounded by lock_timeout, for this transaction only.
                cursor.execute(
                    f"SET LOCAL lock_timeout = '{LOCK_WAIT}'; SELECT pg_advisory_xact_lock({LOCK_KEY})"
                )
                waited = time.monotonic() - started
                if waited >= 1:
                    logger.info(
                        f"tofu-prepare: waited {waited:.1f} s while another start prepared the database"
                    )

                tables = sorted(
                    set(connection.introspection.django_table_names(include_views=False))
                    | {"django_migrations"}
                )
                # The snapshot makes its tables in public, where Django makes them on Tofu's databases.
                cursor.execute(
                    """
                    SELECT current_schema() = 'public' AND NOT EXISTS (
                        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = 'public' AND c.relname = ANY(%s)
                    )
                    """,
                    [tables],
                )
                if cursor.fetchone()[0]:
                    cursor.execute(SNAPSHOT.read_text())
                    logger.info(
                        f"tofu-prepare: new database, made linkding's tables from its schema snapshot "
                        f"({len(snapshot_migrations())} migrations)"
                    )

            call_command("migrate", interactive=False)
            call_command("tofu_close_data_api")
            try:
                with transaction.atomic():
                    call_command("create_initial_superuser")
            except Exception:
                logger.exception("tofu-prepare: create_initial_superuser failed")
