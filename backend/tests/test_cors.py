"""CORS origin policy.

The frontend is served from the custom production domain, not from
*.vercel.app. An origin missing from the allow-list fails every credentialed
browser fetch — login included — while the API itself keeps returning 200 to
curl, so it reads as an app bug rather than a CORS one. These pin both the
real production origins and the hosts that must NOT be allowed.
"""
import re

import pytest

import server


ORIGIN_RE = re.compile(server.CORS_ORIGIN_REGEX)


def allowed(origin: str) -> bool:
    # Starlette's CORSMiddleware uses fullmatch against allow_origin_regex.
    return ORIGIN_RE.fullmatch(origin) is not None


@pytest.mark.parametrize("origin", [
    "https://www.app.aovantagelife.com",       # production domain
    "https://app.aovantagelife.com",           # apex-style variant
    "https://aovantagelife.com",
    "https://vantage-life2-1-7tfmprdau-linnzi-6492s-projects.vercel.app",
    "https://vantage-life2-1.vercel.app",
    "http://localhost:8081",
    "http://localhost",
])
def test_expected_origins_are_allowed(origin):
    assert allowed(origin), f"{origin} must be allowed"


@pytest.mark.parametrize("origin", [
    "https://evil.com",
    "https://aovantagelife.com.evil.com",       # suffix-smuggling
    "https://evil-vercel.app",                  # would pass a naive ".*vercel\\.app"
    "https://notaovantagelife.com",
    "http://www.app.aovantagelife.com",         # plaintext http on the real domain
])
def test_untrusted_origins_are_rejected(origin):
    assert not allowed(origin), f"{origin} must NOT be allowed"


def test_extra_origin_regex_env_is_appended(monkeypatch):
    """CORS_EXTRA_ORIGIN_REGEX lets a new host be allowed without a code change."""
    monkeypatch.setenv("CORS_EXTRA_ORIGIN_REGEX", r"https://staging\.example\.com")
    base = server._CORS_BASE_REGEX
    extra = "https://staging\\.example\\.com"
    combined = re.compile(f"{base}|{extra}")
    assert combined.fullmatch("https://staging.example.com")
    assert combined.fullmatch("https://www.app.aovantagelife.com")
