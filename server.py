#!/usr/bin/env python3
"""OAuth login server for ChatGPT subscription authentication.

Deploy as a Railway service (see railway.toml) so you can authenticate
from any browser by visiting your Railway URL at /login.

Railway sets RAILWAY_PUBLIC_DOMAIN automatically; the server uses it to
build the correct redirect_uri for the OAuth callback.

Usage (local):
    python server.py          # visit http://localhost:8080/login

Usage (Railway):
    Deploy as the 'auth' service — visit https://<your-domain>/login
"""

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import chatgpt_auth

# ── Redirect URI ──────────────────────────────────────────────────────────────
# Railway injects RAILWAY_PUBLIC_DOMAIN, e.g. myapp.up.railway.app
_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
if _domain:
    REDIRECT_URI = f"https://{_domain}/auth/callback"
else:
    REDIRECT_URI = chatgpt_auth.REDIRECT_URI  # http://127.0.0.1:1455/auth/callback

# ── In-memory PKCE state (single-user auth server) ───────────────────────────
_pending: dict = {}
_lock = threading.Lock()


class _Handler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/login":
            self._handle_login()
        elif path == "/auth/callback":
            self._handle_callback()
        else:
            self._respond(404, "Not found")

    # ── /login ────────────────────────────────────────────────────────────────

    def _handle_login(self):
        verifier, challenge = chatgpt_auth._generate_pkce()
        state = chatgpt_auth._random_state()

        with _lock:
            _pending["verifier"] = verifier
            _pending["state"] = state

        params = urlencode({
            "client_id":             chatgpt_auth.CLIENT_ID,
            "redirect_uri":          REDIRECT_URI,
            "response_type":         "code",
            "scope":                 chatgpt_auth.SCOPES,
            "state":                 state,
            "code_challenge":        challenge,
            "code_challenge_method": "S256",
        })
        auth_url = f"{chatgpt_auth.AUTHORIZE_URL}?{params}"

        self.send_response(302)
        self.send_header("Location", auth_url)
        self.end_headers()

    # ── /auth/callback ────────────────────────────────────────────────────────

    def _handle_callback(self):
        params = parse_qs(urlparse(self.path).query)
        code  = params.get("code",  [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]

        if error:
            self._respond(400, f"OAuth error: {error}")
            return

        with _lock:
            expected_state = _pending.get("state")
            verifier       = _pending.get("verifier")

        if not code or state != expected_state:
            self._respond(400, "State mismatch or missing code — possible CSRF")
            return

        try:
            tokens = chatgpt_auth._exchange_code(code, verifier, REDIRECT_URI)
        except Exception as exc:
            self._respond(500, f"Token exchange failed: {exc}")
            return

        creds = {
            "access":    tokens["access_token"],
            "refresh":   tokens.get("refresh_token"),
            "expires":   time.time() + tokens["expires_in"],
            "accountId": chatgpt_auth._extract_account_id(tokens["access_token"]),
        }
        chatgpt_auth.save_credentials(creds)

        with _lock:
            _pending.clear()

        self._respond(
            200,
            f"Authenticated as {creds['accountId']}.\n"
            "Credentials saved. You can close this tab.",
        )

    # ── helpers ───────────────────────────────────────────────────────────────

    def _respond(self, status, body):
        encoded = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt, *args):
        pass  # suppress per-request stdout noise


def main():
    port = int(os.environ.get("PORT", 8080))
    httpd = HTTPServer(("0.0.0.0", port), _Handler)
    base = f"https://{_domain}" if _domain else f"http://127.0.0.1:{port}"
    print(f"Auth server listening on port {port}")
    print(f"Visit {base}/login to authenticate with your ChatGPT subscription")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
