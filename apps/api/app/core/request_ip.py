"""The real client IP for a request that may have passed through a proxy
(Railway's edge, in production) — used for rate limiting, API key
last_used_ip, api_request_logs, audit logs, and IP allowlist enforcement.

`X-Forwarded-For` carries a comma-separated chain, and **a client can put
anything it likes at the front of it**. A proxy appends the address it
actually saw, so the trustworthy entries are at the *right-hand* end: the
rightmost is the peer our own trusted proxy observed, and everything left
of that is hearsay supplied by the caller.

Reading the leftmost entry — the intuitive "original client" — is what
makes this header dangerous. It lets a caller pick their own identity for
anything keyed on IP: rotate it to bypass every rate limit, or set it to
an allowlisted address to defeat a merchant's API-key IP allowlist.

`trusted_proxy_hops` says how many proxies of our own sit in front of this
app, and we count that many entries in from the right. The default of 1
matches Railway's single edge. Put a second proxy in front (Cloudflare,
say) and that must become 2, otherwise this returns the intermediate
proxy's address instead of the client's.
"""

from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str | None:
    """The best-trusted client address, or None if it can't be determined.

    With no trusted proxy configured (hops=0) the header is ignored
    entirely and only the real socket peer is used — correct for running
    without a proxy, where any XFF present is purely caller-supplied.
    """
    hops = get_settings().trusted_proxy_hops
    socket_ip = request.client.host if request.client else None

    if hops <= 0:
        return socket_ip

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return socket_ip

    chain = [part.strip() for part in forwarded.split(",") if part.strip()]
    if not chain:
        return socket_ip

    # Count in from the right. A chain shorter than the configured hop
    # count means fewer proxies ran than expected, so the leftmost entry is
    # the furthest we can go without inventing one — clamped rather than
    # indexing past the end.
    index = max(0, len(chain) - hops)
    return chain[index]
