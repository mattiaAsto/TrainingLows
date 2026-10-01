"""Lightweight fixed-window rate limiting on top of Flask-Caching.

Uses the configured cache backend, so no extra dependency is needed. With the
default SimpleCache the counters are per-process (per gunicorn worker), which
still caps abuse; point CACHE_TYPE at Redis/Memcached for exact global limits.
"""

from flask import abort, request

from app import cache


def _client_key(name):
    remote = request.remote_addr or 'unknown'
    return f'rl:{name}:{remote}'


def enforce_rate_limit(name, limit, window_seconds):
    """Abort with 429 once `limit` calls occurred within `window_seconds`."""
    key = _client_key(name)
    count = cache.get(key)
    if count is None:
        cache.set(key, 1, timeout=window_seconds)
        return
    if count >= limit:
        abort(429)
    try:
        cache.inc(key)
    except (AttributeError, ValueError):
        # Backend without atomic increment, or the key just expired.
        cache.set(key, count + 1, timeout=window_seconds)
