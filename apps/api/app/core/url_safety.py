"""Validation for URLs this backend will itself make requests to.

A merchant chooses their own webhook URL, and the server then fetches it —
on a test delivery and on every real event. That makes the field a
server-side request forgery vector: without a check, a merchant can point
it at `http://169.254.169.254/` and have our infrastructure fetch cloud
metadata for them, or sweep internal addresses and learn what responds from
the timing.

`HttpUrl` alone does not help. It validates that a string is shaped like a
URL, not that the URL is somewhere we should be willing to go.

Two rules, both enforced only in production:

- **HTTPS.** A webhook carries payment events and a signature; over plain
  http both are readable and alterable in transit.
- **Public addresses only.** Loopback, private ranges, link-local, and the
  cloud metadata address are all refused.

Local development needs `http://localhost` to work, so the check is
relaxed outside production — deliberately, and only there.
"""

import ipaddress
import socket
from urllib.parse import urlparse

from app.config import get_settings
from app.core.errors import ValidationAPIError

# Refused outright. 169.254.169.254 is inside the link-local range already,
# but it is named because it is the specific address an SSRF attempt wants.
_METADATA_HOSTS = {"169.254.169.254", "metadata.google.internal", "metadata"}


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_outbound_url(raw_url: str, *, field: str = "URL") -> str:
    """Returns the URL if this server may safely request it, else raises.

    Resolves the hostname, because a name is not a promise: `evil.test`
    can have an A record pointing at 127.0.0.1, so checking the literal
    string would miss it. Every resolved address must be public, not just
    the first.

    This is a check at the time of saving, not at the time of sending. DNS
    can change afterwards (a rebinding attack), so it raises the cost of
    an attempt rather than making one impossible — worth having, and worth
    being honest that it is not a complete defence.
    """
    settings = get_settings()
    enforce = settings.environment == "production"

    parsed = urlparse(raw_url)

    if parsed.scheme not in ("http", "https"):
        raise ValidationAPIError(f"{field} must start with https://")

    if enforce and parsed.scheme != "https":
        raise ValidationAPIError(f"{field} must use https:// so payloads and signatures cannot be read in transit")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValidationAPIError(f"{field} must include a hostname")

    if not enforce:
        return raw_url

    if host in _METADATA_HOSTS:
        raise ValidationAPIError(f"{field} must be a public address")

    # A literal IP needs no lookup; a name does.
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None

    if literal is not None:
        if _is_disallowed_ip(literal):
            raise ValidationAPIError(f"{field} must be a public address, not an internal one")
        return raw_url

    try:
        resolved = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise ValidationAPIError(f"{field} could not be resolved. Check the hostname.") from None

    for entry in resolved:
        address = entry[4][0]
        try:
            candidate = ipaddress.ip_address(address)
        except ValueError:  # pragma: no cover - getaddrinfo returns valid IPs
            continue
        if _is_disallowed_ip(candidate):
            raise ValidationAPIError(f"{field} resolves to an internal address and cannot be used")

    return raw_url
