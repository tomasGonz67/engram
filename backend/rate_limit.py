import hmac
import os
import uuid
from slowapi import Limiter
from trusted_proxy import parse_trusted_proxies, resolve_client_ip

ADMIN_BYPASS_TOKEN = os.getenv("ADMIN_BYPASS_TOKEN")

# Comma-separated IPs/CIDRs of proxies allowed to hand us a client IP via
# X-Forwarded-For — e.g. Traefik's fixed address on its private Docker
# network (see prod.md's "Reverse proxy & trusted client IP" section).
# Empty/unset (the default) trusts nobody, identical to today's behavior.
# Parsed at import time specifically so a malformed value fails
# application startup immediately rather than silently narrowing or
# widening the trust boundary — see trusted_proxy.parse_trusted_proxies.
TRUSTED_PROXY_IPS = parse_trusted_proxies(os.getenv("TRUSTED_PROXY_IPS", ""))

def get_rate_limit_key(request) -> str:
    """Returns the IP to key rate limiting by, unless a valid admin bypass
    token is present in the X-Admin-Bypass-Token header — in that case
    returns a fresh random key instead, so the request never counts
    against (or gets blocked by) any real caller's bucket. Used by
    scripts/seed.py so it can populate a lot of memories quickly without
    hitting the same 20/5min ceiling a real anonymous caller does.

    Not auth on the product itself — store()/search()/generate() stay
    open to everyone regardless of this token, by permanent design (see
    architecture.md). This is a maintenance-only credential, same category
    as OPENAI_API_KEY: an env var only the project owner controls, never
    exposed to or required by any real caller. If ADMIN_BYPASS_TOKEN isn't
    set (the default), this check can never pass — falsy short-circuits
    before comparing anything, so an unconfigured deployment behaves
    exactly like there's no bypass at all. See security-preventions.md.

    hmac.compare_digest() rather than == — constant-time comparison so a
    caller can't guess the token character-by-character via response-time
    differences. Defaults the header to "" (not None) first specifically
    so compare_digest never sees a missing header as None, which it can't
    compare against a str without raising.

    Client IP resolution goes through trusted_proxy.resolve_client_ip()
    rather than slowapi's own get_remote_address() (which only ever reads
    request.client.host) — see trusted_proxy.py for why, and prod.md for
    the deployment side (backend port never publicly reachable, Uvicorn
    started with --no-proxy-headers so it never rewrites request.client
    itself) that this depends on to be meaningful rather than just
    decorative. Uvicorn's own proxy-header handling must stay off:
    trusted_proxy.py is the sole owner of this decision, not a second
    layer alongside it — see trusted_proxy.py's module docstring."""
    token = request.headers.get("X-Admin-Bypass-Token", "")
    if ADMIN_BYPASS_TOKEN and hmac.compare_digest(token, ADMIN_BYPASS_TOKEN):
        return str(uuid.uuid4())
    peer_host = request.client.host if request.client else None
    return resolve_client_ip(peer_host, request.headers.get("X-Forwarded-For"), TRUSTED_PROXY_IPS)

# Single shared Limiter instance, imported by both routers/ files and by
# main.py for setup. IP-keyed (via get_rate_limit_key above) since Masi
# Memory has no auth/session concept to key on instead (see architecture.md's
# permanent no-auth decision) — the same ceiling Eleutheria's session-based
# limiters don't have to work within, since Eleutheria has session tokens
# even without full auth.
#
# In-memory storage (slowapi's default) rather than Redis-backed — correct
# for this project's actual deployment shape: a single DigitalOcean droplet
# running one backend process, not multiple instances needing shared state.
# See prod.md.
#
# IMPORTANT: default_limits does NOT apply automatically to every route
# just because SlowAPIMiddleware is registered — verified live that it
# silently enforces nothing without an explicit decorator on each route
# (plus a request: Request parameter on that route, which slowapi needs
# to identify the caller). There is no global fallback for an undecorated
# route.
#
# Also verified live: @limiter.limit(...) scopes its bucket per-route by
# default — decorating store()/search()/generate() with the same limit
# string each gave every route its own independent 20/5min allowance
# (effectively 60/5min total across the API), not the single flat ceiling
# actually wanted. api_limit uses shared_limit() instead specifically to
# pool all three routes into one bucket — mirroring Eleutheria's
# globalApiLimiter (app.use('/api', globalApiLimiter), one shared limiter
# across every route) rather than Eleutheria's per-route limiters. Two
# windows stacked, same "burst cap + sustained cap" pattern as Eleutheria's
# postIpLimiter + postDailyIpLimiter: 20 requests per 5 minutes (burst) and
# 200 requests per day (sustained abuse), combined across store/search/generate.
limiter = Limiter(key_func=get_rate_limit_key)
api_limit = limiter.shared_limit("20/5minutes;200/day", scope="global_api")
