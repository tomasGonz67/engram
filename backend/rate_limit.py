from slowapi import Limiter
from slowapi.util import get_remote_address

# Single shared Limiter instance, imported by both routers/ files and by
# main.py for setup. IP-keyed since Masi Memory has no auth/session concept
# to key on instead (see architecture.md's permanent no-auth decision) —
# the same ceiling Eleutheria's session-based limiters don't have to work
# within, since Eleutheria has session tokens even without full auth.
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
limiter = Limiter(key_func=get_remote_address)
api_limit = limiter.shared_limit("20/5minutes;200/day", scope="global_api")
