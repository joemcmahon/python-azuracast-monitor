"""Environment-driven settings, read and validated in one place (stdlib only)."""
import math
from dataclasses import dataclass
from typing import Mapping, Optional

DEFAULT_AUTODJ_NAME = "Spud the Ambient Robot"
WEBHOOK_PREFIX = "https://discord.com/api/webhooks/"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class SettingsError(ValueError):
    """Invalid configuration. Messages name the variable, never a webhook value."""


@dataclass(frozen=True)
class Settings:
    station_server: str
    station_shortcode: str
    station_name: str
    autodj_name: str
    status_board: bool
    webhook_url: str
    state_dir: str
    webhook_timeout: float
    sse_read_timeout: float
    dry_run: bool


def parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return default


def _text(environ: Mapping[str, str], name: str, default: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip()


def _positive_float(environ: Mapping[str, str], name: str, default: float) -> float:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        raise SettingsError(f"{name} must be a positive number") from None
    if not math.isfinite(value) or value <= 0:
        raise SettingsError(f"{name} must be a positive number")
    return value


def load_settings(environ: Mapping[str, str]) -> Settings:
    shortcode = _text(environ, "STATION_SHORTCODE", "radiospiral")
    status_board = parse_bool(environ.get("STATUS_BOARD"), False)
    dry_run = parse_bool(environ.get("DRY_RUN"), False)

    webhook_var = "STATUS_BOARD_WEBHOOK" if status_board else "NOW_PLAYING_WEBHOOK"
    webhook_url = (environ.get(webhook_var) or "").strip()
    if not dry_run:
        if not webhook_url:
            raise SettingsError(f"{webhook_var} is required")
        if not webhook_url.startswith(WEBHOOK_PREFIX):
            raise SettingsError(f"{webhook_var} must start with {WEBHOOK_PREFIX}")

    return Settings(
        station_server=_text(environ, "STATION_SERVER", "spiral.radio"),
        station_shortcode=shortcode,
        station_name=_text(environ, "STATION_NAME", shortcode),
        autodj_name=_text(environ, "AUTODJ_NAME", DEFAULT_AUTODJ_NAME),
        status_board=status_board,
        webhook_url=webhook_url,
        state_dir=_text(environ, "STATE_DIR", "."),
        webhook_timeout=_positive_float(environ, "WEBHOOK_TIMEOUT", 10.0),
        sse_read_timeout=_positive_float(environ, "SSE_READ_TIMEOUT", 300.0),
        dry_run=dry_run,
    )
