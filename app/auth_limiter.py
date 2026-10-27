"""
Centralized rate-limiting module for authentication endpoints.
Provides IP-based throttling to defend against brute-force and credential-stuffing attacks.
"""
import time
from collections import defaultdict
from fastapi import Request

# Global in-memory storage: IP address -> list of failed attempt timestamps
failed_logins = defaultdict(list)


def check_rate_limit(request: Request, max_attempts: int = 5, window_seconds: int = 900) -> bool:
    """
    Checks whether the client IP has exceeded max_attempts within the time window.
    Default: max 5 failed attempts per 15-minute (900s) sliding window.
    Returns True if the request is permitted, False if rate-limited.
    """
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    # Retain only timestamps within the sliding window
    failed_logins[client_ip] = [t for t in failed_logins[client_ip] if now - t < window_seconds]
    return len(failed_logins[client_ip]) < max_attempts


def record_failed_login(request: Request):
    """Records a failed login attempt for the client IP."""
    client_ip = request.client.host if request.client else "unknown"
    failed_logins[client_ip].append(time.time())


def clear_failed_logins(request: Request):
    """Clears failed login records for the client IP upon successful login."""
    client_ip = request.client.host if request.client else "unknown"
    failed_logins.pop(client_ip, None)
