"""Password protection for the website and API.

Set TU_PASSWORD on the host (never in a file on GitHub). Then every /api/ call needs a login,
except /api/health (for the host's uptime checks) and the login endpoints themselves.
Without TU_PASSWORD the site stays open, which is fine on your own computer only.

A login gives a signed cookie valid for `TU_SESSION_DAYS` (default 7). It is HttpOnly (page
scripts can't read it) and SameSite=Strict (other websites can't use it). Changing the password
logs everyone out. Five wrong passwords from one address in 15 minutes lock that address out
for the rest of the 15 minutes.

HTTPS (the padlock) still has to come from the host, e.g. Render, or Caddy in front of the app.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from collections import defaultdict, deque

COOKIE = "tu_session"
OPEN_PATHS = frozenset({"/api/health", "/api/auth", "/api/login", "/api/logout"})
MAX_FAILURES, FAILURE_WINDOW_S = 5, 15 * 60


class Auth:
    def __init__(self, password: str | None = None, session_days: float | None = None, secret: str | None = None,
                 clock=time.time) -> None:
        self.password = os.environ.get("TU_PASSWORD", "") if password is None else password
        days = float(os.environ.get("TU_SESSION_DAYS", "7")) if session_days is None else session_days
        self.session_s = days * 86400
        extra = os.environ.get("TU_SECRET", "") if secret is None else secret
        self._key = hashlib.sha256(f"tu-session\0{extra}\0{self.password}".encode()).digest()
        self._clock = clock
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def required(self) -> bool:
        return bool(self.password)

    # ---- session tokens: "<expiry>.<signature>" --------------------------------

    def _sign(self, expiry: int) -> str:
        return hmac.new(self._key, str(expiry).encode(), hashlib.sha256).hexdigest()

    def issue(self) -> str:
        expiry = int(self._clock() + self.session_s)
        return f"{expiry}.{self._sign(expiry)}"

    def valid(self, token: str | None) -> bool:
        if not self.required:
            return True
        if not token or "." not in token:
            return False
        exp, sig = token.split(".", 1)
        if not exp.isdigit():
            return False
        return hmac.compare_digest(sig, self._sign(int(exp))) and int(exp) > self._clock()

    # ---- login with a simple lockout -----------------------------------------------

    def locked(self, who: str) -> bool:
        with self._lock:
            q = self._failures[who]
            while q and q[0] < self._clock() - FAILURE_WINDOW_S:
                q.popleft()
            return len(q) >= MAX_FAILURES

    def check_password(self, who: str, password: str) -> bool:
        ok = hmac.compare_digest(password.encode(), self.password.encode())
        if not ok:
            with self._lock:
                self._failures[who].append(self._clock())
        return ok
