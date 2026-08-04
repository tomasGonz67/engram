"""
Resolves the real client IP for rate limiting when the app runs behind a
reverse proxy (Traefik, and eventually Cloudflare in front of that — see
prod.md's "Reverse proxy & trusted client IP" section for the deployment
side of this: backend port never published, a fixed-subnet Docker
network, and Uvicorn's own --proxy-headers processing explicitly
DISABLED (--no-proxy-headers) so this module is the sole owner of trust
decisions. Uvicorn's ProxyHeadersMiddleware and this module solving the
same problem at the same time is not defense-in-depth — Uvicorn would
rewrite request.client.host before this code ever sees it, breaking the
assumption below that peer_host is the untouched, immediate TCP peer.
Pick one owner; this module is it.

Deliberately a separate, pure-function module from rate_limit.py's
SlowAPI wiring: every edge case here (malformed input, spoofing attempts,
IPv4/IPv6, CIDR ranges, multiple trusted hops) is unit-testable in
isolation, without needing a live server or cycling a rate limiter
through 20 requests per case. See test_trusted_proxy.py.

Uses the ipaddress stdlib module for every address/CIDR comparison —
deliberately not hand-rolled, since manually reimplementing CIDR matching
or address parsing is exactly the kind of security-sensitive logic that's
easy to get subtly wrong.

Targets Python 3.9+ deliberately (this backend actually runs on 3.11 —
see the Dockerfile — but this module has no reason to require newer than
it needs): `from __future__ import annotations` defers evaluation of the
`X | Y` union-type annotations below to strings, and the two real
(non-annotation) type-alias assignments use typing.Union explicitly,
since the future import doesn't cover those. Without either, this file
fails to import on Python < 3.10 — caught by trying to run
test_trusted_proxy.py directly on a 3.9 host, exactly the "run it
directly" use this module's tests are meant to support.
"""

from __future__ import annotations

import ipaddress
from typing import Union

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def parse_trusted_proxies(raw: str) -> list[IPNetwork]:
    """Parses TRUSTED_PROXY_IPS (comma-separated IPs/CIDRs) into ipaddress
    network objects. Empty/unset input is valid and trusts nobody — the
    safe default, identical to today's behavior (no proxy trust at all).

    Any entry that fails to parse raises ValueError immediately, rather
    than being silently dropped or silently trusting nothing: a
    misconfigured trust boundary (a typo in an IP, a malformed CIDR)
    should fail application startup loudly, not quietly narrow or widen
    who gets trusted. Called at module import time in rate_limit.py, so
    this is a real fail-fast on process start, not just on first use."""
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError as e:
            raise ValueError(
                f"Invalid TRUSTED_PROXY_IPS entry {entry!r}: {e}. "
                "TRUSTED_PROXY_IPS must be a comma-separated list of IP "
                "addresses or CIDR ranges (e.g. \"10.0.0.5,10.1.0.0/24\"), "
                "or unset/empty to trust nobody."
            ) from e
    return networks


def _is_trusted(ip: IPAddress, trusted_proxies: list[IPNetwork]) -> bool:
    for network in trusted_proxies:
        if ip.version == network.version and ip in network:
            return True
    return False


def _parse_forwarded_for_chain(header_value: str) -> list[IPAddress] | None:
    """Parses X-Forwarded-For into a list of addresses, left-to-right as
    written (original client first, nearest proxy last — the standard
    convention: each proxy appends what it received from onto the end).

    Returns None — meaning "unusable, discard the whole header" — if ANY
    entry fails to parse as a bare IP address: invalid syntax, an empty
    segment, or an unexpected port suffix (X-Forwarded-For entries never
    legitimately carry a port). Deliberately does not skip a bad entry
    and keep walking the rest of the chain — a single malformed hop makes
    the whole chain's trustworthiness unverifiable, since there's no way
    to know whether the corruption is accidental or an attempt to break
    the parse in a way that shifts which entry the resolver lands on."""
    entries = [e.strip() for e in header_value.split(",")]
    if not entries or any(not e for e in entries):
        return None
    parsed = []
    for entry in entries:
        try:
            parsed.append(ipaddress.ip_address(entry))
        except ValueError:
            return None
    return parsed


def resolve_client_ip(
    peer_host: str | None,
    forwarded_for_header: str | None,
    trusted_proxies: list[IPNetwork],
) -> str:
    """Resolves the real client IP, trusting X-Forwarded-For only from an
    explicitly configured set of proxies — never from an arbitrary
    caller. Mirrors slowapi's get_remote_address() default of "127.0.0.1"
    when no client info is available at all (request.client is None).

    Algorithm: start at the immediate TCP peer (request.client.host). If
    it isn't in trusted_proxies, stop immediately and use it as-is — this
    is the security-critical step. An untrusted peer's own
    X-Forwarded-For is never even parsed, so a direct caller can't just
    declare an arbitrary IP for itself by sending the header (this is
    also why the backend port must never be reachable except through the
    trusted proxy — see prod.md — otherwise this whole mechanism trusts
    nothing, by design, and every caller falls back to its own real
    peer address).

    If the peer IS trusted, walk the X-Forwarded-For chain from the right
    (the hop closest to us — what the nearest trusted proxy claims it
    received from) leftward, re-checking trust at every step, stopping at
    the first untrusted hop (or the leftmost entry if the whole chain is
    trusted, e.g. multiple chained trusted proxies). This is what makes
    an attacker-prepended fake IP harmless even when talking to a trusted
    peer: anything written to the left of a genuinely untrusted hop is
    never reached, because the walk stops at that untrusted hop first —
    it does not matter what an attacker put further left in the header,
    only who is vouching for it."""
    if not peer_host:
        return "127.0.0.1"

    try:
        peer_ip = ipaddress.ip_address(peer_host)
    except ValueError:
        # request.client.host normally comes straight from the real TCP
        # connection, not a header, so this should be unreachable outside
        # an unusual transport/test client. Can't do trust arithmetic on
        # an unparseable value either way — treat it like any other
        # untrusted peer and use it as-is.
        return peer_host

    if not _is_trusted(peer_ip, trusted_proxies):
        return peer_host

    if not forwarded_for_header:
        return peer_host

    chain = _parse_forwarded_for_chain(forwarded_for_header)
    if chain is None:
        return peer_host

    current: IPAddress = peer_ip
    for hop in reversed(chain):
        if not _is_trusted(current, trusted_proxies):
            return str(current)
        current = hop

    return str(current)
