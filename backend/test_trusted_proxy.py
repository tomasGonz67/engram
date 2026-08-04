"""
Exhaustive tests for trusted_proxy.py's client-IP resolution — the
security-critical logic deciding when X-Forwarded-For is trusted at all.
This project deliberately has no broader automated test suite (see
techDebt.md's "No automated testing" entry) — this is a scoped exception:
a pure function with no fixtures, no DB, no network, cheap to keep
correct, and hard to verify any other way given how easy this class of
logic is to get subtly wrong.

Plain assertions, no pytest dependency — run directly:
    python3 backend/test_trusted_proxy.py
"""

from trusted_proxy import parse_trusted_proxies, resolve_client_ip

failures = []


def check(label, actual, expected):
    if actual != expected:
        failures.append(f"{label}: expected {expected!r}, got {actual!r}")


def check_raises(label, fn, exc_type=ValueError):
    try:
        fn()
    except exc_type:
        return
    except Exception as e:
        failures.append(f"{label}: expected {exc_type.__name__}, got {type(e).__name__}: {e}")
        return
    failures.append(f"{label}: expected {exc_type.__name__}, nothing raised")


TRAEFIK = "10.0.0.5"
CLOUDFLARE = "10.0.0.6"
CLIENT = "203.0.113.7"
CLIENT_2 = "203.0.113.9"
ATTACKER_PREPENDED = "6.6.6.6"

no_trust = parse_trusted_proxies("")
traefik_only = parse_trusted_proxies(TRAEFIK)
traefik_and_cloudflare = parse_trusted_proxies(f"{TRAEFIK},{CLOUDFLARE}")

# 1. No trusted proxies configured — header always ignored, peer always wins.
check(
    "no trusted proxies, header present but ignored",
    resolve_client_ip(TRAEFIK, CLIENT, no_trust),
    TRAEFIK,
)

# 2. Untrusted peer with forged header — peer's own header claim is never consulted.
check(
    "untrusted peer, forged header ignored",
    resolve_client_ip("198.51.100.1", "1.2.3.4", traefik_only),
    "198.51.100.1",
)

# 3. Trusted peer with one client address — resolves to the real client.
check(
    "trusted peer, single-hop header",
    resolve_client_ip(TRAEFIK, CLIENT, traefik_only),
    CLIENT,
)

# 4. Trusted Traefik, but Cloudflare (an intermediate hop) is NOT trusted —
# the walk must stop at Cloudflare's address, not continue past it to the
# client just because the nearest hop (Traefik) was trusted.
check(
    "trusted Traefik only, untrusted Cloudflare hop stops the walk",
    resolve_client_ip(TRAEFIK, f"{CLIENT}, {CLOUDFLARE}", traefik_only),
    CLOUDFLARE,
)

# 5. Multiple trusted proxies — a fully-trusted chain walks all the way to
# the original client.
check(
    "multiple trusted proxies, full chain walked",
    resolve_client_ip(TRAEFIK, f"{CLIENT}, {CLOUDFLARE}", traefik_and_cloudflare),
    CLIENT,
)

# 6. Attacker-prepended address before the real client — even at a trusted
# peer, a fake value prepended left of a genuinely untrusted hop must
# never be reached, because the walk stops at that untrusted hop first.
check(
    "attacker-prepended fake IP never reached",
    resolve_client_ip(TRAEFIK, f"{ATTACKER_PREPENDED}, {CLOUDFLARE}", traefik_only),
    CLOUDFLARE,
)

# 6b. The canonical version of the same attack: a FULLY trusted two-proxy
# chain (Traefik and Cloudflare both legitimate and both trusted), with
# an attacker-prepended fake IP written to the left of the real client —
# not left of an untrusted hop, which case 6 above already covers. This
# is the case that actually proves the resolver stops at the real
# client (an ordinary, untrusted end-user address) and does not keep
# walking into attacker-controlled territory just because everything to
# its right happened to be trusted.
check(
    "attacker-prepended address ahead of the real client, in an otherwise fully-trusted chain",
    resolve_client_ip(TRAEFIK, f"{ATTACKER_PREPENDED}, {CLIENT}, {CLOUDFLARE}", traefik_and_cloudflare),
    CLIENT,
)

# 7. Empty header — trusted peer, nothing to walk, falls back to peer.
check("empty header string", resolve_client_ip(TRAEFIK, "", traefik_only), TRAEFIK)
check("missing header (None)", resolve_client_ip(TRAEFIK, None, traefik_only), TRAEFIK)

# 8. Malformed IP — one bad entry discards the WHOLE header, not just that
# entry; never skip-and-continue past a malformed hop.
check(
    "malformed entry discards whole header",
    resolve_client_ip(TRAEFIK, f"{CLIENT}, not-an-ip", traefik_only),
    TRAEFIK,
)
check(
    "unexpected port suffix treated as malformed",
    resolve_client_ip(TRAEFIK, "1.2.3.4:5678", traefik_only),
    TRAEFIK,
)
check(
    "empty segment in chain treated as malformed",
    resolve_client_ip(TRAEFIK, f"{CLIENT}, , {CLOUDFLARE}", traefik_and_cloudflare),
    TRAEFIK,
)

# 9. IPv4 and IPv6 — both address families work, and a v4 peer isn't
# accidentally matched against a v6-only trusted range or vice versa.
v6_traefik = "2001:db8::1"
v6_client = "2001:db8::dead:beef"
traefik_v6_only = parse_trusted_proxies(v6_traefik)
check(
    "IPv6 peer and IPv6 client",
    resolve_client_ip(v6_traefik, v6_client, traefik_v6_only),
    v6_client,
)
check(
    "IPv4 peer not matched against IPv6-only trusted set",
    resolve_client_ip(TRAEFIK, CLIENT, traefik_v6_only),
    TRAEFIK,
)
check(
    "IPv6 peer not matched against IPv4-only trusted set",
    resolve_client_ip(v6_traefik, v6_client, traefik_only),
    v6_traefik,
)

# 10. CIDR matching — a trusted range, not just a single address.
cidr_trusted = parse_trusted_proxies("10.0.0.0/24")
check(
    "peer inside trusted CIDR range",
    resolve_client_ip("10.0.0.42", CLIENT, cidr_trusted),
    CLIENT,
)
check(
    "peer outside trusted CIDR range",
    resolve_client_ip("10.0.1.42", CLIENT, cidr_trusted),
    "10.0.1.42",
)

# 11. Invalid TRUSTED_PROXY_IPS — fails fast at parse time, not silently.
check_raises("garbage entry raises", lambda: parse_trusted_proxies("not-an-ip"))
check_raises("garbage entry among valid ones raises", lambda: parse_trusted_proxies(f"{TRAEFIK},garbage,10.0.0.0/24"))
check("empty string is valid, trusts nobody", parse_trusted_proxies(""), [])
check("whitespace-only is valid, trusts nobody", parse_trusted_proxies("   "), [])

# 12. Missing request.client (peer_host is None) — mirrors slowapi's own
# get_remote_address() fallback.
check("missing client falls back to 127.0.0.1", resolve_client_ip(None, CLIENT, traefik_only), "127.0.0.1")
check("missing client, no trusted proxies either", resolve_client_ip(None, None, no_trust), "127.0.0.1")

# Extra: multi-hop chain where an untrusted hop appears in the middle, not
# at the very end — the walk must still stop at the first untrusted hop
# encountered walking right-to-left, not scan the whole chain for one.
three_hop_trusted = parse_trusted_proxies(f"{TRAEFIK},{CLOUDFLARE}")
UNTRUSTED_MIDDLE = "9.9.9.9"
check(
    "untrusted hop in the middle of an otherwise-trusted-looking chain",
    resolve_client_ip(TRAEFIK, f"{CLIENT}, {UNTRUSTED_MIDDLE}, {CLOUDFLARE}", three_hop_trusted),
    UNTRUSTED_MIDDLE,
)

if failures:
    print(f"FAILED: {len(failures)} of the test cases above")
    for f in failures:
        print(f"  - {f}")
    raise SystemExit(1)
else:
    print("All trusted_proxy.py tests passed.")
