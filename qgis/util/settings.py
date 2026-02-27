# QgsSettings wrappers
import os
from pathlib import Path


def _load_dotenv() -> dict[str, str]:
    """Read the .env file from the plugin repo root (parent of qgis/)."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    vals: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            vals[key.strip()] = value.strip()
    return vals


_dotenv = _load_dotenv()


def get_setting(key: str, default: str = "") -> str:
    """Return a setting value from the environment or .env file."""
    return os.environ.get(key, _dotenv.get(key, default))


def get_control_server_url() -> str:
    """Return the base URL for the geoengine-control server."""
    host = get_setting("GEOENGINE_CONTROL_SERVER", "localhost:8080")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}"
    return host
