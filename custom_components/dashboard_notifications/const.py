"""Constants for Dashboard Notifications."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "dashboard_notifications"
PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_CREATE = "create"
SERVICE_CREATE_TIMED = "create_timed"
SERVICE_CREATE_SCHEDULED_EXPIRY = "create_scheduled_expiry"
SERVICE_DISMISS = "dismiss"

ATTR_ID = "id"
ATTR_KEY = "key"
ATTR_TOPIC = "topic"
ATTR_MESSAGE = "message"
ATTR_TITLE = "title"
ATTR_ICON = "icon"
ATTR_SEVERITY = "severity"
ATTR_EXPIRES_IN = "expires_in"
ATTR_EXPIRES_AT = "expires_at"
ATTR_PERSISTENT = "persistent"

CONF_TOPICS = "topics"
CONF_TOPIC_ID = "id"
CONF_TOPIC_NAME = "name"

SEVERITIES = ("info", "success", "warning", "error")
DEFAULT_ICONS = {
    "info": "mdi:information-outline",
    "success": "mdi:check-circle-outline",
    "warning": "mdi:alert-outline",
    "error": "mdi:alert-circle-outline",
}
STORAGE_VERSION = 1
STORAGE_KEY_PREFIX = f"{DOMAIN}.feed"

DATA_MANAGERS = "managers"
SIGNAL_FEED_UPDATED = f"{DOMAIN}_feed_updated"

WS_TYPE_LIST = f"{DOMAIN}/list"
WS_TYPE_SUBSCRIBE = f"{DOMAIN}/subscribe"
