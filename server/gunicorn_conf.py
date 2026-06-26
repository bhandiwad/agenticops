"""Gunicorn config for the Aurora compute API (main_compute:app).

Uses the gevent worker so long-lived Server-Sent Events streams
(``routes/incidents_sse.py`` and friends) are hosted as lightweight greenlets
instead of each consuming an OS thread. Under the previous ``gthread`` worker a
handful of open SSE connections exhausted the small thread pool and starved all
other requests (including the health check), causing slow page loads and
timeouts.

Knobs (env): GUNICORN_WORKERS, GUNICORN_WORKER_CONNECTIONS, GUNICORN_TIMEOUT,
GUNICORN_RELOAD, FLASK_PORT.
"""

import os

bind = f"0.0.0.0:{os.getenv('FLASK_PORT', '5080')}"
worker_class = "gevent"
workers = int(os.getenv("GUNICORN_WORKERS", "3"))
worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "1000"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "300"))
graceful_timeout = 30
keepalive = 5

# gevent must monkey-patch the standard library *before* the application is
# imported. Preloading imports the app in the master (unpatched) and is therefore
# incompatible with gevent — each worker imports the app itself after patching.
preload_app = False

# Hot reload is for local development only (set GUNICORN_RELOAD=true in dev).
reload = os.getenv("GUNICORN_RELOAD", "false").lower() in ("1", "true", "yes")


def post_worker_init(worker):
    """Runs inside each worker after gevent has monkey-patched the stdlib and the
    app is loaded. Make blocking C-extension clients cooperate with the gevent
    hub so a single slow call can't stall the whole worker's greenlets."""
    # psycopg2 is a C extension; psycogreen lets it yield to the gevent hub.
    # Optional — without it, DB queries briefly block the hub (fine when queries
    # are fast). Never fatal.
    try:
        from psycogreen.gevent import patch_psycopg
        patch_psycopg()
        worker.log.info("psycogreen: psycopg2 patched for gevent")
    except Exception:
        worker.log.info("psycogreen unavailable; psycopg2 blocks the gevent hub per query (ok for fast queries)")

    # Weaviate's client uses gRPC, whose C-core does not cooperate with gevent
    # unless explicitly initialized — otherwise gRPC calls can hang.
    try:
        import grpc.experimental.gevent as grpc_gevent
        grpc_gevent.init_gevent()
        worker.log.info("grpc: gevent support initialized (Weaviate)")
    except Exception as e:  # pragma: no cover - defensive
        worker.log.warning(f"grpc gevent init skipped: {e}")
