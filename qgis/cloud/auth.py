import base64
import hashlib
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlencode, urlparse, parse_qs
from urllib.request import Request, urlopen

from qgis.core import QgsMessageLog, QgsSettings, Qgis
from qgis.PyQt.QtCore import QObject, pyqtSignal

BASE_URL = "https://planet.nika.eco"
KEYRING_SERVICE = "Geoengine + plugins"
KEYRING_ID_TOKEN = "nika-id-token"
KEYRING_REFRESH_TOKEN = "nika-refresh-token"
PORT_RANGE = range(9004, 9100)
LOGIN_TIMEOUT = 300  # seconds
LOG_TAG = "GeoEngine"

# QgsSettings keys (fallback when keyring is unavailable)
_QS_PREFIX = "geoengine_cloud/"
_QS_ID_TOKEN = _QS_PREFIX + "id_token"
_QS_REFRESH_TOKEN = _QS_PREFIX + "refresh_token"


# ---------------------------------------------------------------------------
# Keyring loader
# ---------------------------------------------------------------------------

def _get_keyring():
    """Try to import keyring from the bundled external/ folder, then system."""
    try:
        external_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "external"
        )
        if external_dir not in sys.path:
            sys.path.insert(0, external_dir)
        import keyring
        return keyring
    except Exception:
        return None


_keyring = _get_keyring()


# ---------------------------------------------------------------------------
# Token storage abstraction
# ---------------------------------------------------------------------------

class _KeyringStore:
    """Store tokens in the OS keyring via the keyring library."""

    def __init__(self, kr):
        self._kr = kr

    def get(self, key):
        return self._kr.get_password(KEYRING_SERVICE, key)

    def set(self, key, value):
        self._kr.set_password(KEYRING_SERVICE, key, value)

    def delete(self, key):
        try:
            self._kr.delete_password(KEYRING_SERVICE, key)
        except self._kr.errors.PasswordDeleteError:
            pass


class _QgsSettingsStore:
    """Fallback: store tokens in QgsSettings (plain-text config file)."""

    _KEY_MAP = {
        KEYRING_ID_TOKEN: _QS_ID_TOKEN,
        KEYRING_REFRESH_TOKEN: _QS_REFRESH_TOKEN,
    }

    def __init__(self):
        self._s = QgsSettings()

    def get(self, key):
        return self._s.value(self._KEY_MAP.get(key, key), None)

    def set(self, key, value):
        self._s.setValue(self._KEY_MAP.get(key, key), value)

    def delete(self, key):
        self._s.remove(self._KEY_MAP.get(key, key))


def _init_store():
    if _keyring is not None:
        QgsMessageLog.logMessage(
            "Token storage: OS keyring (via bundled keyring library)",
            LOG_TAG, Qgis.Info,
        )
        return _KeyringStore(_keyring)
    else:
        QgsMessageLog.logMessage(
            "Token storage: QgsSettings fallback (keyring not available)",
            LOG_TAG, Qgis.Warning,
        )
        return _QgsSettingsStore()


_store = _init_store()


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------

def _generate_pkce():
    """Generate PKCE code_verifier, code_challenge (S256), and state."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    state = secrets.token_hex(16)
    return code_verifier, code_challenge, state


# ---------------------------------------------------------------------------
# Localhost callback server
# ---------------------------------------------------------------------------

class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler for the localhost OAuth callback."""

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path not in ("/callback", "/"):
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            self.send_response(400)
            self.end_headers()
            return

        self.server.callback_data = data
        self.server.callback_cookies = self.headers.get("Cookie", "")
        redirect_url = data.get("redirectUrl", BASE_URL)

        self.send_response(302)
        self._cors_headers()
        self.send_header("Location", redirect_url)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        data = {k: v[0] for k, v in params.items()}
        self.server.callback_data = data
        redirect_url = data.get("redirectUrl", BASE_URL)

        self.send_response(302)
        self.send_header("Location", redirect_url)
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, format, *args):
        pass  # suppress console noise


# ---------------------------------------------------------------------------
# AuthManager
# ---------------------------------------------------------------------------

class AuthManager(QObject):
    """Manages the GeoEngine PKCE login flow and token lifecycle."""

    login_succeeded = pyqtSignal(dict)  # user info dict
    login_failed = pyqtSignal(str)  # error message

    def __init__(self):
        super().__init__()

    # ---- public API --------------------------------------------------------

    def login(self):
        """Kick off the browser-based login flow in a background thread."""
        threading.Thread(target=self._login_flow, daemon=True).start()

    @staticmethod
    def get_id_token():
        """Return the stored ID token, or None."""
        return _store.get(KEYRING_ID_TOKEN)

    @staticmethod
    def get_refresh_token():
        """Return the stored refresh token, or None."""
        return _store.get(KEYRING_REFRESH_TOKEN)

    def ensure_valid_token(self):
        """Return a valid ID token, refreshing if expired. None on failure."""
        token = self.get_id_token()
        if token and not self._is_token_expired(token):
            return token
        return self._refresh_id_token()

    def logout(self):
        """Delete stored tokens."""
        _store.delete(KEYRING_ID_TOKEN)
        _store.delete(KEYRING_REFRESH_TOKEN)

    # ---- internals ---------------------------------------------------------

    def _login_flow(self):
        code_verifier, code_challenge, state = _generate_pkce()

        # Start a one-shot HTTP server on the first available port.
        server = None
        for port in PORT_RANGE:
            try:
                server = HTTPServer(("127.0.0.1", port), _CallbackHandler)
                server.callback_data = None
                break
            except OSError:
                continue

        if server is None:
            self.login_failed.emit(
                "Could not bind to any port in 9004-9099 for the login callback."
            )
            return

        port = server.server_address[1]

        # Open the browser login page.
        login_url = (
            f"{BASE_URL}/en/desktopClientLogin?"
            + urlencode(
                {
                    "port": port,
                    "state": state,
                    "codeChallenge": code_challenge,
                }
            )
        )
        webbrowser.open(login_url)

        # Serve requests until the callback arrives or we time out.
        deadline = time.time() + LOGIN_TIMEOUT
        while server.callback_data is None and time.time() < deadline:
            server.timeout = max(1, deadline - time.time())
            server.handle_request()

        data = server.callback_data
        server.server_close()

        if data is None:
            self.login_failed.emit("Login timed out — no callback received.")
            return

        if "error" in data:
            desc = data.get("errorDescription", data.get("error", "Unknown error"))
            self.login_failed.emit(f"Login error: {desc}")
            return

        if data.get("state") != state:
            self.login_failed.emit("State mismatch — possible CSRF attack.")
            return

        exchange_code = data.get("exchangeCode")
        if not exchange_code:
            self.login_failed.emit("No exchange code in callback.")
            return

        # Exchange code for tokens.
        try:
            tokens = self._exchange_code(exchange_code, code_verifier)
        except Exception as exc:
            self.login_failed.emit(f"Token exchange failed: {exc}")
            return

        import tempfile
        dbg = os.path.join(tempfile.gettempdir(), "geoengine_login_debug.txt")
        with open(dbg, "w") as f:
            f.write(f"Exchange response keys: {list(tokens.keys())}\n")
            f.write(f"Has idToken: {'idToken' in tokens}\n")
            f.write(f"Has user: {'user' in tokens}\n")
            if "user" in tokens:
                f.write(f"User: {tokens['user']}\n")

        # Persist tokens.
        id_token = tokens.get("idToken")
        refresh_token = tokens.get("refreshToken")
        if id_token:
            _store.set(KEYRING_ID_TOKEN, id_token)
        if refresh_token:
            _store.set(KEYRING_REFRESH_TOKEN, refresh_token)

        self.login_succeeded.emit(tokens.get("user", {}))

    @staticmethod
    def _exchange_code(exchange_code, code_verifier):
        from urllib.error import HTTPError

        url = f"{BASE_URL}/api/auth/desktop/exchange"
        payload = {"exchangeCode": exchange_code, "codeVerifier": code_verifier}
        body = json.dumps(payload).encode()

        QgsMessageLog.logMessage(
            f"Exchange request: code={exchange_code[:8]}… "
            f"verifier_len={len(code_verifier)}",
            LOG_TAG, Qgis.Info,
        )

        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            QgsMessageLog.logMessage(
                f"Exchange error response: {raw}", LOG_TAG, Qgis.Warning,
            )
            try:
                detail = json.loads(raw).get("message", "")
            except Exception:
                detail = raw
            raise RuntimeError(
                f"{exc.code} {exc.reason}" + (f" — {detail}" if detail else "")
            ) from None

    @staticmethod
    def _is_token_expired(token):
        try:
            payload_b64 = token.split(".")[1]
            pad = 4 - len(payload_b64) % 4
            if pad != 4:
                payload_b64 += "=" * pad
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            return time.time() >= payload.get("exp", 0)
        except Exception:
            return True

    def _refresh_id_token(self):
        refresh_token = self.get_refresh_token()
        if not refresh_token:
            return None
        url = f"{BASE_URL}/api/auth/desktop/refresh"
        body = json.dumps({"refreshToken": refresh_token}).encode()
        req = Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                new_token = data.get("idToken")
                if new_token:
                    _store.set(KEYRING_ID_TOKEN, new_token)
                return new_token
        except Exception:
            return None
