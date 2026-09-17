"""Dashboard Notifications integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.service import async_set_service_schema
from homeassistant.components import websocket_api

from .const import (
    ATTR_EXPIRES_AT, ATTR_EXPIRES_IN, ATTR_ICON, ATTR_ID, ATTR_KEY, ATTR_MESSAGE,
    ATTR_SEVERITY, ATTR_TITLE, ATTR_TOPIC, CONF_TOPICS, DATA_MANAGERS, DOMAIN,
    PLATFORMS, SERVICE_CREATE, SERVICE_DISMISS, SEVERITIES, SIGNAL_FEED_UPDATED,
    WS_TYPE_LIST, WS_TYPE_SUBSCRIBE,
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
CREATE_SCHEMA = vol.Schema({
    vol.Required(ATTR_TOPIC): cv.string,
    vol.Required(ATTR_MESSAGE): cv.string,
    vol.Optional(ATTR_KEY): cv.string,
    vol.Optional(ATTR_TITLE): cv.string,
    vol.Optional(ATTR_ICON): cv.icon,
    vol.Optional(ATTR_SEVERITY, default="info"): vol.In(SEVERITIES),
    vol.Optional(ATTR_EXPIRES_IN): DURATION_SCHEMA,
    vol.Optional(ATTR_EXPIRES_AT): cv.string,
})


def _manager(hass: HomeAssistant) -> NotificationManager:
    managers = hass.data.get(DOMAIN, {}).get(DATA_MANAGERS, {})
    if not managers:
        raise HomeAssistantError("Dashboard Notifications is not configured")
    return next(iter(managers.values()))


def _feed_payload(manager: NotificationManager) -> dict[str, Any]:
    return {"topics": manager.topics, "items": manager.feed()}


def _async_update_create_description(
    hass: HomeAssistant, manager: NotificationManager
) -> None:
    """Publish the live topic registry to Home Assistant's action editor."""
    async_set_service_schema(
        hass,
        DOMAIN,
        SERVICE_CREATE,
        {
            "name": "Create notification",
            "description": "Add a feed item, or replace the existing item with the same key.",
            "fields": {
                ATTR_TOPIC: {
                    "name": "Topic",
                    "required": True,
                    "selector": {
                        "select": {
                            "options": [
                                {"label": topic["name"], "value": topic["id"]}
                                for topic in manager.topics
                            ]
                        }
                    },
                },
                ATTR_MESSAGE: {"name": "Message", "required": True, "selector": {"text": {"multiline": True}}},
                ATTR_KEY: {"name": "Key", "selector": {"text": {}}},
                ATTR_TITLE: {"name": "Title", "selector": {"text": {}}},
                ATTR_ICON: {"name": "Icon", "selector": {"icon": {}}},
                ATTR_SEVERITY: {
                    "name": "Severity",
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
                ATTR_EXPIRES_IN: {"name": "Expires in", "selector": {"duration": {}}},
                ATTR_EXPIRES_AT: {"name": "Expires at", "selector": {"datetime": {}}},
            },
        },
    )


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Register global actions and WebSocket commands."""
    hass.data.setdefault(DOMAIN, {DATA_MANAGERS: {}})

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

    websocket_api.async_register_command(hass, websocket_list)
    websocket_api.async_register_command(hass, websocket_subscribe)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured notification feed."""
    manager = NotificationManager(hass, entry.entry_id, entry.options.get(CONF_TOPICS, []))
    await manager.async_load()
    hass.data[DOMAIN][DATA_MANAGERS][entry.entry_id] = manager
    _async_update_create_description(hass, manager)

    async def async_options_updated(hass: HomeAssistant, updated_entry: ConfigEntry) -> None:
        await manager.async_update_topics(updated_entry.options.get(CONF_TOPICS, []))
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
