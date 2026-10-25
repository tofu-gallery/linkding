# Placeholder, can be mounted in a Docker container with a custom settings
#
# Tofu (2026-10-25): Tofu's settings for its gallery copy of linkding (see TOFU.md at the repository root). prod.py
# imports this file last, so each name in __all__ below replaces prod.py's value; nothing else is exported. Tofu's image
# runs prod.py (DJANGO_SETTINGS_MODULE in the Dockerfile and in uwsgi.ini). Upstream's test settings (dev.py) do not
# import this file.
import hashlib
import os
from urllib.parse import parse_qsl, unquote, urlsplit

from .base import LD_DB_OPTIONS


def _flag(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value in ("True", "true", "1")


__all__ = []

# Tofu sets DATABASE_URL (postgresql://user:password@host:port/database?sslmode=require), which goes through a
# transaction pooler. It is used unless LD_DB_ENGINE is set, in which case upstream's LD_DB_* settings stay as they are.
_database_url = os.getenv("DATABASE_URL", "")
if _database_url and not os.getenv("LD_DB_ENGINE"):
    _url = urlsplit(_database_url)
    if _url.scheme in ("postgres", "postgresql"):
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": unquote(_url.path.lstrip("/")) or "postgres",
                "USER": unquote(_url.username or ""),
                "PASSWORD": unquote(_url.password or ""),
                "HOST": _url.hostname or "",
                "PORT": str(_url.port or ""),
                # The URL's query (sslmode=require) becomes libpq connection parameters. A transaction pooler keeps no
                # prepared statement from one transaction to the next: Django's psycopg 3 cursors bind parameters on
                # the client and prepare nothing, and prepare_threshold=None makes sure psycopg never prepares either.
                "OPTIONS": {
                    **dict(parse_qsl(_url.query)),
                    "prepare_threshold": None,
                    **LD_DB_OPTIONS,
                },
                # Nor does it keep a server-side cursor between transactions.
                "DISABLE_SERVER_SIDE_CURSORS": True,
                # Each worker keeps its connection for a minute, checked before reuse, instead of opening a new TLS
                # connection to the pooler for every request.
                "CONN_MAX_AGE": 60,
                "CONN_HEALTH_CHECKS": True,
            }
        }
        __all__ += ["DATABASES"]

# Upstream keeps its secret key in data/secretkey.txt, and a copy has no lasting disk: every restart would make a new
# key and sign everyone out. So the key is LD_SECRET_KEY when the owner saves one as a hidden value, and otherwise the
# SHA-256 of "linkding-secret-key:" and the whole DATABASE_URL, which Tofu keeps as a hidden value.
if os.getenv("LD_SECRET_KEY"):
    SECRET_KEY = os.environ["LD_SECRET_KEY"]
    __all__ += ["SECRET_KEY"]
elif _database_url:
    SECRET_KEY = hashlib.sha256(
        ("linkding-secret-key:" + _database_url).encode()
    ).hexdigest()
    __all__ += ["SECRET_KEY"]

# Tofu serves the copy over HTTPS through its own proxy, which says in X-Forwarded-Proto and X-Forwarded-Host which
# scheme and address the visitor used. Django's CSRF check compares a form's Origin with them. LD_CSRF_TRUSTED_ORIGINS
# (upstream's setting, which a gallery copy sets to its own address) is read by base.py.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = _flag("LD_USE_X_FORWARDED_HOST", True)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
__all__ += [
    "SECURE_PROXY_SSL_HEADER",
    "USE_X_FORWARDED_HOST",
    "SESSION_COOKIE_SECURE",
    "CSRF_COOKIE_SECURE",
]

# What upstream keeps as files on the server's disk is off, because a copy has none that lasts: the next restart would
# lose the files while the database still names them. Uploading files to a bookmark, HTML snapshots (which also need
# the Chromium of upstream's "plus" image), favicons and preview images.
LD_DISABLE_ASSET_UPLOAD = True
LD_ENABLE_SNAPSHOTS = False
LD_DISABLE_FAVICONS = True
LD_DISABLE_PREVIEW_IMAGES = True
__all__ += [
    "LD_DISABLE_ASSET_UPLOAD",
    "LD_ENABLE_SNAPSHOTS",
    "LD_DISABLE_FAVICONS",
    "LD_DISABLE_PREVIEW_IMAGES",
]

# A copy does not follow upstream, so the settings page does not ask GitHub for upstream's latest release.
LD_DISABLE_VERSION_CHECK = True
# While there is no account yet, the login page tells the copy's owner how to make the first one.
LD_INITIAL_SUPERUSER_HINT = True
__all__ += ["LD_DISABLE_VERSION_CHECK", "LD_INITIAL_SUPERUSER_HINT"]
