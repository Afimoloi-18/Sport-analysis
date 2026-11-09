"""Thin API-Football (api-sports.io v3) client: stdlib only, call budget + rate limiting."""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://v3.football.api-sports.io"


class ApiError(Exception):
    pass


class PlanError(ApiError):
    """The API refused because of the subscription plan (e.g. season not included)."""


class BudgetExceeded(Exception):
    pass


class Api:
    def __init__(self, key, budget=95, min_interval=6.5):
        self.key = key
        self.budget = budget
        self.min_interval = min_interval
        self.calls = 0
        self.remaining = None  # daily requests remaining as reported by the API
        self._last = 0.0

    def left(self):
        left = self.budget - self.calls
        if self.remaining is not None:
            left = min(left, self.remaining)
        return max(left, 0)

    def get(self, path, **params):
        if self.left() <= 0:
            raise BudgetExceeded(f"call budget used ({self.calls} calls)")
        for attempt in range(2):
            wait = self.min_interval - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
            req = urllib.request.Request(url, headers={"x-apisports-key": self.key})
            self._last = time.time()
            try:
                with urllib.request.urlopen(req, timeout=40) as r:
                    body = json.load(r)
                    rem = r.headers.get("x-ratelimit-requests-remaining")
            except urllib.error.HTTPError as e:
                raise ApiError(f"HTTP {e.code} on {path}") from e
            self.calls += 1
            if rem is not None and rem.isdigit():
                self.remaining = int(rem)
            errs = body.get("errors")
            if errs:
                text = json.dumps(errs)
                if "rateLimit" in text and attempt == 0:
                    time.sleep(65)
                    continue
                low = text.lower()
                if "plan" in low or "season" in low or "subscription" in low:
                    raise PlanError(text)
                if "token" in low or "key" in low or "access" in low:
                    raise PlanError(text)
                raise ApiError(text)
            return body.get("response", [])
        raise ApiError(f"rate limited twice on {path}")
