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
from qgis.PyQt.QtCore import QCoreApplication, QEvent, QObject, pyqtSignal, pyqtSlot

from ..util.messages import PLUGIN_LOG_TAG as LOG_TAG

# Wake main thread without Python QEvent subclasses (unreliable with postEvent).
_AUTH_WAKE_MAIN = QEvent.registerEventType()

BASE_URL = "https://planet.nika.eco"
KEYRING_ID_TOKEN = "nika-id-token"
KEYRING_REFRESH_TOKEN = "nika-refresh-token"
PORT_RANGE = range(9004, 9100)
LOGIN_TIMEOUT = 300  # seconds

# QgsSettings keys (fallback when keyring is unavailable, and user info)
_QS_PREFIX = "geoengine_cloud/"
_QS_ID_TOKEN = _QS_PREFIX + "id_token"
_QS_REFRESH_TOKEN = _QS_PREFIX + "refresh_token"
_QS_USER_INFO = _QS_PREFIX + "user_info"
_KEYRING_USERNAME = "nikauser"


# ---------------------------------------------------------------------------
# Keyring loader
# ---------------------------------------------------------------------------

def _ensure_vendored_keyring_backends_imported():
    """Register built-in KeyringBackend subclasses for the tree on sys.path.

    entry_points.txt matches upstream jaraco/keyring. On some QGIS builds
    ``importlib.metadata`` may attach ``keyring.backends`` to a different
    distribution; importing these modules unconditionally forces registration.
    """
    import importlib

    try:
        importlib.import_module("keyring.backends.chainer")
    except Exception:
        pass
    if sys.platform == "win32":
        for mod in ("keyring.backends.Windows",):
            try:
                importlib.import_module(mod)
            except Exception:
                pass
    elif sys.platform == "darwin":
        for mod in ("keyring.backends.macOS",):
            try:
                importlib.import_module(mod)
            except Exception:
                pass
    else:
        for mod in (
            "keyring.backends.SecretService",
            "keyring.backends.libsecret",
            "keyring.backends.kwallet",
        ):
            try:
                importlib.import_module(mod)
            except Exception:
                pass


def _get_keyring():
    """Try to import keyring from the bundled external/ folder, then system."""
    try:
        external_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "external"
        )
        if external_dir not in sys.path:
            sys.path.insert(0, external_dir)
        import keyring

        _ensure_vendored_keyring_backends_imported()
        return keyring
    except Exception:
        return None


_keyring = _get_keyring()


def debug_log_keyring_backends():
    """Print and log all discoverable keyring backends (for diagnosing 'No recommended backend')."""
    try:
        external_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "external"
        )
        if external_dir not in sys.path:
            sys.path.insert(0, external_dir)
        import keyring  # noqa: F401

        _ensure_vendored_keyring_backends_imported()
        from keyring.backend import get_all_keyring

        rings = get_all_keyring()
        print("[GeoEngine Cloud] keyring.backend.get_all_keyring():", rings, flush=True)
        lines = [f"[{i}] {type(b).__module__}.{type(b).__qualname__}: {b!r}" for i, b in enumerate(rings)]
        QgsMessageLog.logMessage(
            "Keyring backends (get_all_keyring):\n" + "\n".join(lines) if lines else "Keyring backends: (empty list)",
            LOG_TAG,
            Qgis.Info if rings else Qgis.Warning,
        )
    except Exception as exc:
        print("[GeoEngine Cloud] keyring backend debug failed:", exc, flush=True)
        QgsMessageLog.logMessage(
            f"Keyring backend debug failed: {exc}",
            LOG_TAG,
            Qgis.Warning,
        )


# ---------------------------------------------------------------------------
# Token storage abstraction
# ---------------------------------------------------------------------------

class _KeyringStore:
    """Store tokens in the OS keyring, keyed by (service=entry_name, user=_KEYRING_USERNAME).

    Matches the Rust ``keyring::Entry::new(entry, username)`` convention used
    by the GeoEngine CLI so both applications share the same credentials.
    """

    def __init__(self, kr):
        self._kr = kr

    def get(self, key):
        return self._kr.get_password(key, _KEYRING_USERNAME)

    def set(self, key, value):
        self._kr.set_password(key, _KEYRING_USERNAME, value)

    def delete(self, key):
        try:
            self._kr.delete_password(key, _KEYRING_USERNAME)
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

        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True}).encode())

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return

        params = parse_qs(parsed.query)
        data = {k: v[0] for k, v in params.items()}
        self.server.callback_data = data

        self.send_response(302)
        self._cors_headers()
        self.send_header("Location", f"{BASE_URL}/en/desktopClientLogin?success=true")
        self.end_headers()

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

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
        self._pending_login_error: str | None = None
        self._pending_exchange_tokens: dict | None = None

    def event(self, e):
        if e.type() == _AUTH_WAKE_MAIN:
            if self._pending_exchange_tokens is not None:
                self._finish_login_on_main()
            elif self._pending_login_error is not None:
                self._deliver_login_failed_msg()
            return True
        return super().event(e)

    def _wake_main_thread(self):
        # Plain QEvent(int); avoids PyQt5 vs PyQt6 QEvent.Type quirks.
        QCoreApplication.postEvent(self, QEvent(_AUTH_WAKE_MAIN))

    def _post_login_failed(self, message: str):
        self._pending_login_error = message
        self._wake_main_thread()

    @pyqtSlot()
    def _deliver_login_failed_msg(self):
        msg = self._pending_login_error or ""
        self._pending_login_error = None
        self.login_failed.emit(msg)

    @pyqtSlot()
    def _finish_login_on_main(self):
        """Runs on main thread: keyring + settings must not run from the login worker."""
        tokens = self._pending_exchange_tokens
        self._pending_exchange_tokens = None
        if tokens is None:
            QgsMessageLog.logMessage(
                "_finish_login_on_main: missing pending tokens "
                "(duplicate wake or scheduler issue)",
                LOG_TAG,
                Qgis.Warning,
            )
            return

        user_payload = tokens.get("user") or {}
        if not isinstance(user_payload, dict):
            user_payload = {}

        id_token = tokens.get("idToken")
        refresh_token = tokens.get("refreshToken")
        try:
            if id_token:
                _store.set(KEYRING_ID_TOKEN, id_token)
            if refresh_token:
                _store.set(KEYRING_REFRESH_TOKEN, refresh_token)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not persist tokens: {exc}", LOG_TAG, Qgis.Warning,
            )
            self.login_failed.emit(f"Could not save tokens: {exc}")
            return

        try:
            QgsSettings().setValue(_QS_USER_INFO, json.dumps(user_payload))
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Could not persist user info: {exc}", LOG_TAG, Qgis.Warning,
            )

        QgsMessageLog.logMessage(
            f"Login complete (user keys: {list(user_payload.keys())})", LOG_TAG, Qgis.Info,
        )
        self.login_succeeded.emit(user_payload)

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

    def try_restore_session(self) -> dict | None:
        """Check for stored tokens and return user info if session is valid.

        Returns the user info dict if a valid session was restored, or None.
        """
        QgsMessageLog.logMessage(
            "Checking keyring for existing session\u2026", LOG_TAG, Qgis.Info,
        )

        id_token = self.get_id_token()
        if not id_token:
            QgsMessageLog.logMessage(
                "No stored ID token found — no session to restore", LOG_TAG, Qgis.Info,
            )
            return None

        if self._is_token_expired(id_token):
            QgsMessageLog.logMessage(
                "Stored ID token is expired, attempting refresh\u2026", LOG_TAG, Qgis.Info,
            )
            id_token = self._refresh_id_token()
            if not id_token:
                QgsMessageLog.logMessage(
                    "Token refresh failed — session not restored", LOG_TAG, Qgis.Warning,
                )
                return None
            QgsMessageLog.logMessage(
                "Token refreshed successfully", LOG_TAG, Qgis.Info,
            )
        else:
            QgsMessageLog.logMessage(
                "Stored ID token is still valid", LOG_TAG, Qgis.Info,
            )

        user = None
        raw = QgsSettings().value(_QS_USER_INFO, None)
        if raw:
            try:
                user = json.loads(raw)
                if not isinstance(user, dict) or not user.get("username"):
                    user = None
            except (json.JSONDecodeError, ValueError):
                user = None

        # Tokens may have been written by the GeoEngine CLI, which doesn't
        # populate QgsSettings.  Fall back to the server ping endpoint.
        if user is None:
            QgsMessageLog.logMessage(
                "No stored user info — fetching from server\u2026", LOG_TAG, Qgis.Info,
            )
            user = self._fetch_user_info(id_token)
            if user:
                QgsSettings().setValue(_QS_USER_INFO, json.dumps(user))

        if not user:
            QgsMessageLog.logMessage(
                "Could not obtain user info — session not restored", LOG_TAG, Qgis.Warning,
            )
            return None

        QgsMessageLog.logMessage(
            f"Session restored for {user['username']}", LOG_TAG, Qgis.Info,
        )
        return user

    def logout(self):
        """Delete stored tokens and user info."""
        _store.delete(KEYRING_ID_TOKEN)
        _store.delete(KEYRING_REFRESH_TOKEN)
        QgsSettings().remove(_QS_USER_INFO)

    # ---- internals ---------------------------------------------------------

    @staticmethod
    def _fetch_user_info(id_token):
        """GET /api/auth/desktop/ping with the id_token and return the user dict."""
        url = f"{BASE_URL}/api/auth/desktop/ping"
        req = Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {id_token}")
        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                user = data.get("user")
                if isinstance(user, dict) and user.get("username"):
                    return user
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Failed to fetch user info from server: {exc}", LOG_TAG, Qgis.Warning,
            )
        return None

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
            self._post_login_failed(
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
            self._post_login_failed("Login timed out — no callback received.")
            return

        if "error" in data:
            desc = data.get("errorDescription", data.get("error", "Unknown error"))
            self._post_login_failed(f"Login error: {desc}")
            return

        if data.get("state") != state:
            self._post_login_failed("State mismatch — possible CSRF attack.")
            return

        exchange_code = data.get("exchangeCode")
        if not exchange_code:
            self._post_login_failed("No exchange code in callback.")
            return

        # Exchange code for tokens.
        try:
            tokens = self._exchange_code(exchange_code, code_verifier)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Token exchange failed: {exc}", LOG_TAG, Qgis.Warning,
            )
            self._post_login_failed(f"Token exchange failed: {exc}")
            return

        QgsMessageLog.logMessage(
            "Exchange OK — scheduling save + UI on main thread",
            LOG_TAG,
            Qgis.Info,
        )
        self._pending_exchange_tokens = tokens
        self._wake_main_thread()

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
                raw = resp.read()
                status = getattr(resp, "status", "?")
                QgsMessageLog.logMessage(
                    f"Exchange HTTP status={status}, body_len={len(raw)}",
                    LOG_TAG,
                    Qgis.Info,
                )
                try:
                    return json.loads(raw)
                except json.JSONDecodeError as jexc:
                    QgsMessageLog.logMessage(
                        f"Exchange response is not valid JSON: {jexc}",
                        LOG_TAG,
                        Qgis.Warning,
                    )
                    raise
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
