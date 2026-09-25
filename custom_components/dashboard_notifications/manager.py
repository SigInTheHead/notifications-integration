"""Persist and manage the Dashboard Notifications feed."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
import re
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_EXPIRES_AT,
    ATTR_EXPIRES_IN,
    ATTR_ACTIONS,
    ATTR_ICON,
    ATTR_ID,
    ATTR_KEY,
    ATTR_MESSAGE,
    ATTR_PERSISTENT,
    ATTR_SEVERITY,
    ATTR_SHOW_TIMESTAMP,
    ATTR_TITLE,
    ATTR_TOPIC,
    CONF_TOPIC_ID,
    CONF_TOPIC_COLOR,
    CONF_TOPIC_ICON,
    CONF_TOPIC_NAME,
    DEFAULT_SEVERITY_COLORS,
    DEFAULT_ICONS,
    DOMAIN,
    SEVERITIES,
    SIGNAL_FEED_UPDATED,
    STORAGE_KEY_PREFIX,
    STORAGE_VERSION,
)

# Values emitted by Home Assistant's ui_color selector. Keep these as literal
# palette colours rather than theme variables: a configured notification colour
# must not change because a theme redefines (for example) --red-color.
UI_COLOR_HEX = {
    "red": "#f44336", "pink": "#e91e63", "purple": "#926bc7",
    "deep-purple": "#6e41ab", "indigo": "#3f51b5", "blue": "#2196f3",
    "light-blue": "#03a9f4", "cyan": "#00bcd4", "teal": "#009688",
    "green": "#4caf50", "light-green": "#8bc34a", "lime": "#cddc39",
    "yellow": "#ffeb3b", "amber": "#ffc107", "orange": "#ff9800",
    "deep-orange": "#ff6f22", "brown": "#795548", "light-grey": "#bdbdbd",
    "grey": "#9e9e9e", "dark-grey": "#606060", "blue-grey": "#607d8b",
    "black": "#000000", "white": "#ffffff",
}

_DURATION_RE = re.compile(
    r"^(?:(?P<days>\d+)d)?(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
)


def _utcnow() -> datetime:
    return dt_util.utcnow()


def _as_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _parse_duration(value: str | Mapping[str, int]) -> timedelta:
    """Parse a compact duration or Home Assistant duration-selector value."""
    if isinstance(value, Mapping):
        allowed = {"days", "hours", "minutes", "seconds", "milliseconds"}
        if not set(value).issubset(allowed):
            raise ServiceValidationError("expires_in contains unsupported duration fields")
        try:
            duration = timedelta(**{key: int(amount) for key, amount in value.items()})
        except (TypeError, ValueError) as err:
            raise ServiceValidationError("expires_in must be a valid duration") from err
        if duration <= timedelta():
            raise ServiceValidationError("expires_in must be greater than zero")
        return duration

    match = _DURATION_RE.fullmatch(value.strip())
    if not match or not any(match.groupdict().values()):
        raise ServiceValidationError(
            "expires_in must be a compact duration such as 2h03m45s"
        )
    duration = timedelta(**{name: int(part or 0) for name, part in match.groupdict().items()})
    if duration <= timedelta():
        raise ServiceValidationError("expires_in must be greater than zero")
    return duration


def _parse_expiry(data: dict[str, Any], now: datetime) -> str | None:
    """Validate and return a normalized UTC expiry timestamp or None."""
    has_duration = ATTR_EXPIRES_IN in data
    has_datetime = ATTR_EXPIRES_AT in data
    if has_duration and has_datetime:
        raise ServiceValidationError("Provide either expires_in or expires_at, not both")
    if has_duration:
        return _as_utc_iso(now + _parse_duration(data[ATTR_EXPIRES_IN]))
    if not has_datetime:
        return None
    try:
        parsed = datetime.fromisoformat(data[ATTR_EXPIRES_AT].replace("Z", "+00:00"))
    except (AttributeError, ValueError) as err:
        raise ServiceValidationError("expires_at must be an ISO-8601 timestamp") from err
    if parsed.tzinfo is None:
        raise ServiceValidationError("expires_at must include a timezone")
    parsed = parsed.astimezone(UTC)
    if parsed <= now:
        raise ServiceValidationError("expires_at must be in the future")
    return _as_utc_iso(parsed)


class NotificationManager:
    """Own the active notification feed for one config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        topics: Iterable[dict[str, str]],
        severity_colors: Mapping[str, Any] | None = None,
    ) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self._topics = self._normalise_topics(topics)
        self._configured_severity_colors = dict(severity_colors or {})
        self._severity_colors = self._normalise_severity_colors(self._configured_severity_colors)
        self._items: list[dict[str, Any]] = []
        self._store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{STORAGE_KEY_PREFIX}.{entry_id}")
        self._lock = asyncio.Lock()
        self._expiry_cancel: asyncio.TimerHandle | None = None

    @staticmethod
    def _normalise_topics(topics: Iterable[dict[str, str]]) -> dict[str, dict[str, str]]:
        normalised = {}
        for topic in topics:
            if not topic.get(CONF_TOPIC_ID) or not topic.get(CONF_TOPIC_NAME):
                continue
            item = {
                CONF_TOPIC_ID: topic[CONF_TOPIC_ID],
                CONF_TOPIC_NAME: topic[CONF_TOPIC_NAME],
            }
            if isinstance(topic.get(CONF_TOPIC_ICON), str) and topic[CONF_TOPIC_ICON]:
                item[CONF_TOPIC_ICON] = topic[CONF_TOPIC_ICON]
            if isinstance(topic.get(CONF_TOPIC_COLOR), str) and topic[CONF_TOPIC_COLOR]:
                item[CONF_TOPIC_COLOR] = topic[CONF_TOPIC_COLOR]
            normalised[topic[CONF_TOPIC_ID]] = item
        return normalised

    @staticmethod
    def _normalise_severity_colors(colors: Mapping[str, Any] | None) -> dict[str, str]:
        """Convert configured RGB values into safe CSS color values."""
        configured = colors or {}
        result = {}
        for severity, default in DEFAULT_SEVERITY_COLORS.items():
            value = configured.get(severity, default)
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                result[severity] = value.lower()
                continue
            if isinstance(value, str) and value in UI_COLOR_HEX:
                result[severity] = UI_COLOR_HEX[value]
                continue
            # Configured RGB lists were used by the first implementation;
            # retain them so users are not forced to re-enter their colours.
            if isinstance(value, (list, tuple)) and len(value) == 3:
                try:
                    red, green, blue = (max(0, min(255, int(channel))) for channel in value)
                    result[severity] = f"#{red:02x}{green:02x}{blue:02x}"
                    continue
                except (TypeError, ValueError):
                    pass
            result[severity] = default
        return result

    async def async_load(self) -> None:
        """Load saved items and remove entries no longer valid."""
        saved = await self._store.async_load() or {}
        self._items = saved.get("items", [])
        changed = await self.async_purge_expired(notify=False)
        invalid_topics = {item[ATTR_TOPIC] for item in self._items} - set(self._topics)
        if invalid_topics:
            self._items = [item for item in self._items if item[ATTR_TOPIC] not in invalid_topics]
            changed = True
        if changed:
            await self._async_save()
        self._schedule_expiry()

    @property
    def topics(self) -> list[dict[str, str]]:
        return list(self._topics.values())

    def feed(self) -> list[dict[str, Any]]:
        """Return active feed items in chronological order."""
        items = []
        for item in self._items:
            result = item.copy()
            topic_color = self._topics.get(item[ATTR_TOPIC], {}).get(CONF_TOPIC_COLOR)
            if topic_color:
                result["topic_color"] = self._as_css_color(topic_color)
            items.append(result)
        return sorted(items, key=lambda item: item["created_at"])

    @staticmethod
    def _as_css_color(value: str) -> str | None:
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value.lower()
        if value in UI_COLOR_HEX:
            return UI_COLOR_HEX[value]
        return None

    @property
    def severity_colors(self) -> dict[str, str]:
        """Return the integration-wide severity colours for dashboard cards."""
        return self._severity_colors.copy()

    async def async_update_configuration(
        self,
        topics: Iterable[dict[str, str]],
        severity_colors: Mapping[str, Any] | None,
    ) -> None:
        """Apply topic and severity-colour configuration changes."""
        async with self._lock:
            self._topics = self._normalise_topics(topics)
            self._configured_severity_colors = dict(severity_colors or {})
            self._severity_colors = self._normalise_severity_colors(self._configured_severity_colors)
            before = len(self._items)
            self._items = [item for item in self._items if item[ATTR_TOPIC] in self._topics]
            if len(self._items) != before:
                await self._async_save()
            self._schedule_expiry()
        self._notify()

    async def async_update_topics(self, topics: Iterable[dict[str, str]]) -> None:
        """Apply registry changes and delete feed items for removed topics."""
        await self.async_update_configuration(topics, self._configured_severity_colors)

    async def async_create(self, data: dict[str, Any]) -> str:
        """Create or replace a feed item and return its integration ID."""
        async with self._lock:
            topic_id = data[ATTR_TOPIC]
            if topic_id not in self._topics:
                raise ServiceValidationError("topic must be a registered Dashboard Notifications topic ID")
            now = _utcnow()
            expiry = _parse_expiry(data, now)
            item_id = str(uuid4())
            key = data.get(ATTR_KEY)
            if key is not None:
                for existing in self._items:
                    if existing.get(ATTR_KEY) == key:
                        item_id = existing[ATTR_ID]
                        self._items.remove(existing)
                        break
            item: dict[str, Any] = {
                ATTR_ID: item_id,
                ATTR_TOPIC: topic_id,
                ATTR_MESSAGE: data[ATTR_MESSAGE],
                ATTR_ICON: data.get(ATTR_ICON)
                or self._topics[topic_id].get(CONF_TOPIC_ICON)
                or DEFAULT_ICONS[data.get(ATTR_SEVERITY, "info")],
                ATTR_PERSISTENT: bool(data.get(ATTR_PERSISTENT, False)),
                ATTR_SHOW_TIMESTAMP: bool(data.get(ATTR_SHOW_TIMESTAMP, True)),
                "created_at": _as_utc_iso(now),
                "expires_at": expiry,
            }
            if data.get(ATTR_ACTIONS):
                item[ATTR_ACTIONS] = data[ATTR_ACTIONS]
            for attribute in (ATTR_KEY, ATTR_TITLE, ATTR_SEVERITY):
                if data.get(attribute) is not None:
                    item[attribute] = data[attribute]
            self._items.append(item)
            await self._async_save()
            self._schedule_expiry()
        self._notify()
        return item_id

    async def async_dismiss(self, *, item_id: str | None, key: str | None) -> bool:
        """Remove an item by ID or key. Returns whether an item was removed."""
        if (item_id is None) == (key is None):
            raise ServiceValidationError("Provide exactly one of id or key")
        async with self._lock:
            match_index = next(
                (
                    index
                    for index, item in enumerate(self._items)
                    if (item_id is not None and item[ATTR_ID] == item_id)
                    or (key is not None and item.get(ATTR_KEY) == key)
                ),
                None,
            )
            if match_index is None:
                return False
            self._items.pop(match_index)
            await self._async_save()
            self._schedule_expiry()
        self._notify()
        return True

    async def async_purge_expired(self, *, notify: bool = True) -> bool:
        """Delete expired items and return whether the feed changed."""
        now = _utcnow()
        async with self._lock:
            previous = len(self._items)
            self._items = [
                item
                for item in self._items
                if not item.get("expires_at")
                or datetime.fromisoformat(item["expires_at"]).astimezone(UTC) > now
            ]
            changed = previous != len(self._items)
            if changed:
                await self._async_save()
            self._schedule_expiry()
        if changed and notify:
            self._notify()
        return changed

    async def _async_save(self) -> None:
        await self._store.async_save({"items": self._items})

    def _schedule_expiry(self) -> None:
        if self._expiry_cancel:
            self._expiry_cancel.cancel()
            self._expiry_cancel = None
        expiries = [item["expires_at"] for item in self._items if item.get("expires_at")]
        if not expiries:
            return
        next_expiry = min(datetime.fromisoformat(value).astimezone(UTC) for value in expiries)
        delay = max(0, (next_expiry - _utcnow()).total_seconds())
        self._expiry_cancel = self.hass.loop.call_later(delay, self._async_expiry_callback)

    def _async_expiry_callback(self) -> None:
        self.hass.async_create_task(self.async_purge_expired())

    async def async_unload(self) -> None:
        """Release timers when the config entry unloads."""
        if self._expiry_cancel:
            self._expiry_cancel.cancel()
            self._expiry_cancel = None

    def _notify(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_FEED_UPDATED, self.entry_id)
