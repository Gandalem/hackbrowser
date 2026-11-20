"""Disposable Keycloak authorization-code + PKCE S256 smoke helpers.

Drives Keycloak's real HTML login form using standard-library HTTP, preserving
first-party cookies and verifying state. Only sends disposable test credentials
to the expected loopback Keycloak origin. Never prints codes, tokens or passwords.
Not a substitute for the ChatGPT UI/connector consent flow.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit, urlencode
from urllib.request import (
    HTTPCookieProcessor, HTTPRedirectHandler, ProxyHandler, Request, build_opener,
)

_REDIRECT_CODES = {301, 302, 303, 307, 308}


class PKCEFlowError(RuntimeError):
    """Safe error without credentials or authorization codes."""


class _NoAutomaticRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, msg, headers, new_url):
        return None


class _LoginForm(HTMLParser):
    def __init__(self):
        super().__init__()
        self.action = None
        self.hidden = {}
        self._inside = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form" and attrs.get("id") == "kc-form-login":
            self._inside = True
            self.action = attrs.get("action")
        elif tag == "input" and self._inside:
            name = attrs.get("name")
            if name and attrs.get("type") == "hidden":
                self.hidden[name] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self._inside = False


def new_verifier():
    return secrets.token_urlsafe(48)


def s256_challenge(verifier):
    return base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")


def _localize_login_url(url, *, base_url, public_base, realm):
    parsed = urlsplit(url)
    local = urlsplit(base_url)
    public = urlsplit(public_base)
    expected_prefix = f"/auth/realms/{realm}/"
    if (parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {local.hostname, public.hostname}
            or not parsed.path.startswith(expected_prefix)
            or parsed.username is not None or parsed.password is not None):
        raise PKCEFlowError("Unexpected Keycloak redirect or login form origin")
    # Only loopback transport is used, even if Keycloak publishes a public
    # hostname in its login form. Never leak test credentials elsewhere.
    return urlunsplit((local.scheme, local.netloc, parsed.path,
                       parsed.query, parsed.fragment))


def authorization_code(
    *, base_url, public_base, realm, client_id, redirect_uri,
    username, password,
):
    """Get a Keycloak code after real form login; return (code, verifier).

    Redirect callbacks are intercepted (nothing is sent to a public website).
    """
    if not redirect_uri.startswith("http://127.0.0.1:"):
        raise ValueError("PKCE smoke redirect URI must use loopback")
    verifier = new_verifier()
    state = secrets.token_urlsafe(24)
    query = urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": f"openid mcp:hackbrowser",
        "code_challenge": s256_challenge(verifier),
        "code_challenge_method": "S256",
        "state": state,
        "nonce": secrets.token_urlsafe(24),
    })
    current = f"{base_url}/realms/{realm}/protocol/openid-connect/auth?{query}"
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()),
                          _NoAutomaticRedirect())
    method = "GET"
    payload = None
    submitted = False
    for _ in range(16):
        request = Request(current, data=payload, method=method, headers={
            "Accept": "text/html,application/xhtml+xml",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        try:
            with opener.open(request, timeout=12) as response:
                code = response.status
                body = response.read(1_000_000)
                location = response.headers.get("Location")
        except HTTPError as exc:
            code = exc.code
            location = exc.headers.get("Location")
            # Do not echo a possibly credential-containing Keycloak error page.
            body = b""
        except (URLError, TimeoutError) as exc:
            raise PKCEFlowError("Keycloak login request unavailable") from exc

        if code in _REDIRECT_CODES and location:
            destination = urljoin(current, location)
            redirect = urlsplit(destination)
            expected = urlsplit(redirect_uri)
            if (redirect.scheme, redirect.netloc, redirect.path) == (
                expected.scheme, expected.netloc, expected.path
            ):
                args = parse_qs(redirect.query)
                if args.get("state") != [state]:
                    raise PKCEFlowError("OAuth state did not match")
                if "error" in args or len(args.get("code", [])) != 1:
                    raise PKCEFlowError("Keycloak authorization-code callback denied")
                if not submitted:
                    raise PKCEFlowError("Authorization completed before test login")
                return args["code"][0], verifier
            current = _localize_login_url(
                destination, base_url=base_url, public_base=public_base,
                realm=realm,
            )
            method, payload = "GET", None
            continue

        if code != 200:
            raise PKCEFlowError(f"Keycloak authorization HTTP {code}")
        if submitted:
            raise PKCEFlowError("Keycloak login did not redirect to callback")
        form = _LoginForm()
        form.feed(body.decode("utf-8", errors="replace"))
        if not form.action:
            raise PKCEFlowError("Keycloak password login form not found")
        current = _localize_login_url(
            urljoin(current, form.action), base_url=base_url,
            public_base=public_base, realm=realm,
        )
        values = {**form.hidden, "username": username, "password": password}
        payload = urlencode(values).encode()
        method = "POST"
        submitted = True
    raise PKCEFlowError("Keycloak authentication exceeded redirect limit")
