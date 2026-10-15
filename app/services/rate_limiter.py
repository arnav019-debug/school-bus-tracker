import ipaddress
import time
from collections import defaultdict
from typing import Optional
from fastapi import HTTPException, Request, status

def get_client_ip(request: Request) -> str:
    """
    Extracts the trusted client IP address behind reverse proxies (Render / Cloudflare).
    Validates that the IP is well-formed to prevent spoofing or injection attacks.
    """
    # 1. Cloudflare header if present
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        cf_ip_clean = cf_ip.strip()
        try:
            ipaddress.ip_address(cf_ip_clean)
            return cf_ip_clean
        except ValueError:
            pass

    # 2. X-Forwarded-For header: parse comma-separated chain
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        parts = [p.strip() for p in x_forwarded_for.split(",") if p.strip()]
        # Loop through IPs: pick the first valid IP that isn't spoofed/malformed
        for part in parts:
            try:
                ip_obj = ipaddress.ip_address(part)
                # If there are public IPs, return the first valid public IP
                if not ip_obj.is_private and not ip_obj.is_loopback:
                    return str(ip_obj)
            except ValueError:
                continue
        # If all were private/loopback, return the first valid one
        if parts:
            try:
                ipaddress.ip_address(parts[0])
                return parts[0]
            except ValueError:
                pass

    # 3. Direct client host fallback
    if request.client and request.client.host:
        try:
            ipaddress.ip_address(request.client.host)
            return request.client.host
        except ValueError:
            pass

    return "127.0.0.1"


class InMemoryRateLimiter:
    """
    Sliding window in-memory rate limiter with configurable window and error details.
    """
    def __init__(self, max_requests: int = 5, window_seconds: int = 900, detail_message: Optional[str] = None):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.detail_message = detail_message or "Too many requests. Please try again later."
        self.requests: dict[str, list[float]] = defaultdict(list)

    def check(self, key: str) -> None:
        now = time.time()
        cutoff = now - self.window_seconds
        valid_timestamps = [ts for ts in self.requests[key] if ts > cutoff]
        if len(valid_timestamps) >= self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=self.detail_message
            )
        valid_timestamps.append(now)
        self.requests[key] = valid_timestamps

    def reset(self) -> None:
        self.requests.clear()


# Rate limiters
forgot_password_limiter = InMemoryRateLimiter(
    max_requests=5,
    window_seconds=900,
    detail_message="Too many password reset requests. Please try again later."
)
reset_password_limiter = InMemoryRateLimiter(
    max_requests=5,
    window_seconds=900,
    detail_message="Too many password reset attempts. Please try again later."
)
login_limiter = InMemoryRateLimiter(
    max_requests=10,
    window_seconds=60,
    detail_message="Too many login attempts. Please try again in a minute."
)
login_failed_limiter = InMemoryRateLimiter(
    max_requests=5,
    window_seconds=300,
    detail_message="Too many failed login attempts for this account. Please try again in 5 minutes."
)

