"""Dashboard Notifications integration."""

from __future__ import annotations

from typing import Any
from pathlib import Path
import re
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.components import frontend, websocket_api
from homeassistant.components.http import StaticPathConfig

from .const import (
    ATTR_EXPIRES_AT, ATTR_EXPIRES_IN, ATTR_ICON, ATTR_ID, ATTR_KEY, ATTR_MESSAGE,
    ATTR_PERSISTENT, ATTR_SEVERITY, ATTR_TITLE, ATTR_TOPIC, CONF_SEVERITY_COLORS, CONF_TOPIC_ID,
    CONF_TOPIC_COLOR, CONF_TOPIC_ICON, CONF_TOPIC_NAME, CONF_TOPICS,
    DATA_MANAGERS, DEFAULT_SEVERITY_COLORS, DOMAIN, PLATFORMS, SERVICE_CREATE, SERVICE_CREATE_SCHEDULED_EXPIRY,
    SERVICE_CREATE_TIMED, SERVICE_DISMISS, SEVERITIES, SIGNAL_FEED_UPDATED,
    WS_TYPE_LIST, WS_TYPE_SETTINGS, WS_TYPE_SETTINGS_ADD_TOPIC,
    WS_TYPE_SETTINGS_REMOVE_TOPIC, WS_TYPE_SETTINGS_RENAME_TOPIC,
    WS_TYPE_SETTINGS_SET_COLORS, WS_TYPE_SUBSCRIBE,
)
from .manager import NotificationManager

DISMISS_SCHEMA = vol.Schema({vol.Optional(ATTR_ID): cv.string, vol.Optional(ATTR_KEY): cv.string})
DURATION_SCHEMA = vol.Any(
    cv.string,
    vol.Schema({
        vol.Optional("days"): vol.Coerce(int),
        vol.Optional("hours"): vol.Coerce(int),
        vol.Optional("minutes"): vol.Coerce(int),
        vol.Optional("seconds"): vol.Coerce(int),
        vol.Optional("milliseconds"): vol.Coerce(int),
    }),
)
CREATE_FIELDS = {
    vol.Required(ATTR_TOPIC): cv.string,
    vol.Required(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_KEY): cv.string,
    vol.Optional(ATTR_TITLE): cv.string,
    vol.Optional(ATTR_ICON): cv.icon,
    vol.Optional(ATTR_SEVERITY, default="info"): vol.In(SEVERITIES),
    vol.Optional(ATTR_PERSISTENT, default=False): cv.boolean,
}
CREATE_SCHEMA = vol.Schema(CREATE_FIELDS)
CREATE_TIMED_SCHEMA = vol.Schema({
    **CREATE_FIELDS,
    vol.Required(ATTR_EXPIRES_IN): DURATION_SCHEMA,
})
CREATE_SCHEDULED_EXPIRY_SCHEMA = vol.Schema({
    **CREATE_FIELDS,
    vol.Required(ATTR_EXPIRES_AT): cv.string,
})


def _manager(hass: HomeAssistant) -> NotificationManager:
    managers = hass.data.get(DOMAIN, {}).get(DATA_MANAGERS, {})
    if not managers:
        raise HomeAssistantError("Dashboard Notifications is not configured")
    return next(iter(managers.values()))


def _config_entry(hass: HomeAssistant) -> ConfigEntry:
    """Return the singleton Dashboard Notifications config entry."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("Dashboard Notifications is not configured")
    return entries[0]


def _settings_payload(hass: HomeAssistant) -> dict[str, Any]:
    """Return editable global settings for the frontend panel."""
    entry = _config_entry(hass)
    colors = entry.options.get(CONF_SEVERITY_COLORS, {})
    return {
        "topics": entry.options.get(CONF_TOPICS, []),
        "severity_colors": {
            severity: _settings_color(
                colors.get(severity), DEFAULT_SEVERITY_COLORS[severity]
            )
            for severity in SEVERITIES
        },
    }


def _settings_color(value: Any, default: str) -> str:
    """Return a settings-panel value, including migrations from RGB lists."""
    if isinstance(value, str) and (
        re.fullmatch(r"#[0-9a-fA-F]{6}", value)
        or re.fullmatch(r"[a-z]+(?:-[a-z]+)*", value)
    ):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            red, green, blue = (max(0, min(255, int(channel))) for channel in value)
            return f"#{red:02x}{green:02x}{blue:02x}"
        except (TypeError, ValueError):
            pass
    return default


def _topic_defaults(data: dict[str, Any]) -> dict[str, str]:
    """Validate optional topic icon and colour values from the settings panel."""
    result: dict[str, str] = {}
    icon = data.get(CONF_TOPIC_ICON)
    if isinstance(icon, str) and icon:
        try:
            result[CONF_TOPIC_ICON] = cv.icon(icon)
        except vol.Invalid as err:
            raise HomeAssistantError("Icon must be a valid Home Assistant icon") from err
    color = data.get(CONF_TOPIC_COLOR)
    if isinstance(color, str) and color:
        if not (
            re.fullmatch(r"#[0-9a-fA-F]{6}", color)
            or re.fullmatch(r"[a-z]+(?:-[a-z]+)*", color)
        ):
            raise HomeAssistantError("Colour must be selected from the picker")
        result[CONF_TOPIC_COLOR] = color
    return result


def _async_update_settings(hass: HomeAssistant, **changes: Any) -> None:
    """Persist a partial update to the singleton config entry options."""
    entry = _config_entry(hass)
    hass.config_entries.async_update_entry(entry, options={**entry.options, **changes})


def _feed_payload(manager: NotificationManager) -> dict[str, Any]:
    return {
        "topics": manager.topics,
        "items": manager.feed(),
        "severity_colors": manager.severity_colors,
    }


def _async_update_create_description(
    hass: HomeAssistant, manager: NotificationManager
) -> None:
    """Publish the live topic registry to Home Assistant's action editor."""
    common_fields = {
        ATTR_TOPIC: {
            "name": "Topic",
            "required": True,
            "selector": {
                "select": {
                    "mode": "dropdown",
                    "options": [
                        {"label": topic["name"], "value": topic["id"]}
                        for topic in manager.topics
                    ],
                }
            },
        },
        ATTR_MESSAGE: {"name": "Message", "required": True, "selector": {"text": {}}},
        ATTR_KEY: {"name": "Key", "selector": {"text": {}}},
        ATTR_TITLE: {"name": "Title", "selector": {"text": {}}},
        ATTR_ICON: {"name": "Icon", "selector": {"icon": {}}},
        ATTR_SEVERITY: {
            "name": "Severity",
            "required": True,
            "default": "info",
            "selector": {
                "select": {
                    "mode": "dropdown",
                    "options": [
                        {"label": severity.title(), "value": severity}
                        for severity in SEVERITIES
                    ],
                }
            },
        },
        ATTR_PERSISTENT: {
            "name": "Persistent",
            "description": "Cannot be dismissed from a dashboard card.",
            "required": True,
            "default": False,
            "selector": {"boolean": {}},
        },
    }
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CREATE,
        {
            "name": "Create notification",
            "description": "Add a feed item with no automatic expiry, or replace one with the same key.",
            "fields": common_fields,
        },
    )
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CREATE_TIMED,
        {
            "name": "Create timed notification",
            "description": "Add a feed item that expires after a duration.",
            "fields": {
                **common_fields,
                ATTR_EXPIRES_IN: {
                    "name": "Expires in",
                    "required": True,
                    "selector": {"duration": {}},
                },
            },
        },
    )
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CREATE_SCHEDULED_EXPIRY,
        {
            "name": "Create scheduled expiry notification",
            "description": "Add a feed item that expires at a date and time.",
            "fields": {
                **common_fields,
                ATTR_EXPIRES_AT: {
                    "name": "Expires at",
                    "required": True,
                    "selector": {"datetime": {}},
                },
            },
        },
    )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register global actions and WebSocket commands."""
    hass.data.setdefault(DOMAIN, {DATA_MANAGERS: {}})
    await hass.http.async_register_static_paths([
        StaticPathConfig(
            "/dashboard-notifications-settings",
            str(Path(__file__).parent / "frontend"),
            cache_headers=False,
        )
    ])
    frontend.async_register_built_in_panel(
        hass,
        component_name="custom",
        sidebar_title="Dashboard Notifications",
        sidebar_icon="mdi:message-alert-outline",
        frontend_url_path="dashboard-notifications",
        require_admin=True,
        config={
            "_panel_custom": {
                "name": "dashboard-notifications-settings-panel",
                "embed_iframe": False,
                "trust_external": False,
                "module_url": "/dashboard-notifications-settings/dashboard-notifications-settings.js?v=16",
            }
        },
    )

    async def async_create(call: ServiceCall) -> dict[str, str]:
        data = dict(call.data)
        if not data[ATTR_MESSAGE].strip():
            raise HomeAssistantError("message must not be empty")
        item_id = await _manager(hass).async_create(data)
        return {ATTR_ID: item_id}

    async def async_dismiss(call: ServiceCall) -> None:
        await _manager(hass).async_dismiss(
            item_id=call.data.get(ATTR_ID), key=call.data.get(ATTR_KEY)
        )

    hass.services.async_register(DOMAIN, SERVICE_CREATE, async_create, schema=CREATE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_TIMED, async_create, schema=CREATE_TIMED_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_CREATE_SCHEDULED_EXPIRY, async_create, schema=CREATE_SCHEDULED_EXPIRY_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    hass.services.async_register(DOMAIN, SERVICE_DISMISS, async_dismiss, schema=DISMISS_SCHEMA)
    _register_websocket_commands(hass)
    return True


def _register_websocket_commands(hass: HomeAssistant) -> None:
    """Register one-time authenticated commands consumed by the card."""

    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_LIST})
    @websocket_api.async_response
    async def websocket_list(hass: HomeAssistant, connection, msg):
        connection.send_result(msg["id"], _feed_payload(_manager(hass)))

    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_SUBSCRIBE})
    @websocket_api.async_response
    async def websocket_subscribe(hass: HomeAssistant, connection, msg):
        manager = _manager(hass)

        def send_feed(entry_id: str) -> None:
            if entry_id == manager.entry_id:
                connection.send_event(msg["id"], _feed_payload(manager))

        connection.subscriptions[msg["id"]] = async_dispatcher_connect(hass, SIGNAL_FEED_UPDATED, send_feed)
        connection.send_result(msg["id"], _feed_payload(manager))

    @websocket_api.websocket_command({vol.Required("type"): WS_TYPE_SETTINGS})
    @websocket_api.require_admin
    @websocket_api.async_response
    async def websocket_settings(hass: HomeAssistant, connection, msg):
        connection.send_result(msg["id"], _settings_payload(hass))

    @websocket_api.websocket_command({
        vol.Required("type"): WS_TYPE_SETTINGS_ADD_TOPIC,
        vol.Required(CONF_TOPIC_NAME): cv.string,
        vol.Optional(CONF_TOPIC_ICON): vol.Any(cv.string, None),
        vol.Optional(CONF_TOPIC_COLOR): vol.Any(cv.string, None),
    })
    @websocket_api.require_admin
    @websocket_api.async_response
    async def websocket_add_topic(hass: HomeAssistant, connection, msg):
        name = msg[CONF_TOPIC_NAME].strip()
        if not name:
            connection.send_error(msg["id"], "invalid_name", "Enter a topic name")
            return
        settings = _settings_payload(hass)
        if any(topic[CONF_TOPIC_NAME].casefold() == name.casefold() for topic in settings[CONF_TOPICS]):
            connection.send_error(msg["id"], "duplicate_name", "A topic with this name already exists")
            return
        try:
            defaults = _topic_defaults(msg)
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "invalid_topic_default", str(err))
            return
        _async_update_settings(
            hass,
            **{CONF_TOPICS: settings[CONF_TOPICS] + [{CONF_TOPIC_ID: str(uuid4()), CONF_TOPIC_NAME: name, **defaults}]},
        )
        connection.send_result(msg["id"], _settings_payload(hass))

    @websocket_api.websocket_command({
        vol.Required("type"): WS_TYPE_SETTINGS_RENAME_TOPIC,
        # `id` is reserved for the WebSocket request ID. Do not reuse it for
        # the topic identifier: the frontend client replaces it before the
        # command reaches this handler.
        vol.Required("topic_id"): cv.string,
        vol.Required(CONF_TOPIC_NAME): cv.string,
        vol.Optional(CONF_TOPIC_ICON): vol.Any(cv.string, None),
        vol.Optional(CONF_TOPIC_COLOR): vol.Any(cv.string, None),
    })
    @websocket_api.require_admin
    @websocket_api.async_response
    async def websocket_rename_topic(hass: HomeAssistant, connection, msg):
        name = msg[CONF_TOPIC_NAME].strip()
        settings = _settings_payload(hass)
        if not name:
            connection.send_error(msg["id"], "invalid_name", "Enter a topic name")
            return
        if not any(topic[CONF_TOPIC_ID] == msg["topic_id"] for topic in settings[CONF_TOPICS]):
            connection.send_error(msg["id"], "not_found", "Topic was not found")
            return
        if any(topic[CONF_TOPIC_ID] != msg["topic_id"] and topic[CONF_TOPIC_NAME].casefold() == name.casefold() for topic in settings[CONF_TOPICS]):
            connection.send_error(msg["id"], "duplicate_name", "A topic with this name already exists")
            return
        try:
            defaults = _topic_defaults(msg)
        except HomeAssistantError as err:
            connection.send_error(msg["id"], "invalid_topic_default", str(err))
            return
        _async_update_settings(hass, **{CONF_TOPICS: [
            {CONF_TOPIC_ID: topic[CONF_TOPIC_ID], CONF_TOPIC_NAME: name, **defaults}
            if topic[CONF_TOPIC_ID] == msg["topic_id"] else topic
            for topic in settings[CONF_TOPICS]
        ]})
        connection.send_result(msg["id"], _settings_payload(hass))

    @websocket_api.websocket_command({
        vol.Required("type"): WS_TYPE_SETTINGS_REMOVE_TOPIC,
        vol.Required("topic_id"): cv.string,
    })
    @websocket_api.require_admin
    @websocket_api.async_response
    async def websocket_remove_topic(hass: HomeAssistant, connection, msg):
        settings = _settings_payload(hass)
        topics = [topic for topic in settings[CONF_TOPICS] if topic[CONF_TOPIC_ID] != msg["topic_id"]]
        if len(topics) == len(settings[CONF_TOPICS]):
            connection.send_error(msg["id"], "not_found", "Topic was not found")
            return
        _async_update_settings(hass, **{CONF_TOPICS: topics})
        connection.send_result(msg["id"], _settings_payload(hass))

    @websocket_api.websocket_command({
        vol.Required("type"): WS_TYPE_SETTINGS_SET_COLORS,
        vol.Required(CONF_SEVERITY_COLORS): dict,
    })
    @websocket_api.require_admin
    @websocket_api.async_response
    async def websocket_set_colors(hass: HomeAssistant, connection, msg):
        colors = msg[CONF_SEVERITY_COLORS]
        current = _settings_payload(hass)[CONF_SEVERITY_COLORS]
        # ui_color emits only the changed form value on some frontend versions.
        # Preserve any untouched colour rather than rejecting the full palette.
        _async_update_settings(hass, **{CONF_SEVERITY_COLORS: {
            severity: _settings_color(colors.get(severity), current[severity])
            for severity in SEVERITIES
        }})
        connection.send_result(msg["id"], _settings_payload(hass))

    websocket_api.async_register_command(hass, websocket_list)
    websocket_api.async_register_command(hass, websocket_subscribe)
    websocket_api.async_register_command(hass, websocket_settings)
    websocket_api.async_register_command(hass, websocket_add_topic)
    websocket_api.async_register_command(hass, websocket_rename_topic)
    websocket_api.async_register_command(hass, websocket_remove_topic)
    websocket_api.async_register_command(hass, websocket_set_colors)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured notification feed."""
    manager = NotificationManager(
        hass,
        entry.entry_id,
        entry.options.get(CONF_TOPICS, []),
        entry.options.get(CONF_SEVERITY_COLORS),
    )
    await manager.async_load()
    hass.data[DOMAIN][DATA_MANAGERS][entry.entry_id] = manager
    _async_update_create_description(hass, manager)

    async def async_options_updated(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        await manager.async_update_configuration(
            updated_entry.options.get(CONF_TOPICS, []),
            updated_entry.options.get(CONF_SEVERITY_COLORS),
        )
        _async_update_create_description(hass, manager)

    entry.async_on_unload(entry.add_update_listener(async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a notification feed."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        manager = hass.data[DOMAIN][DATA_MANAGERS].pop(entry.entry_id)
        await manager.async_unload()
    return unloaded
