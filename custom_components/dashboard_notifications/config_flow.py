"""Config and options flows for Dashboard Notifications."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_SEVERITY_COLORS,
    CONF_TOPIC_ID,
    CONF_TOPIC_NAME,
    CONF_TOPICS,
    DEFAULT_SEVERITY_COLORS,
    DOMAIN,
    SEVERITIES,
)


class DashboardNotificationsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the singleton Dashboard Notifications config entry."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return self.async_create_entry(title="Dashboard Notifications", data={})

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        # Home Assistant injects the config entry onto OptionsFlow before use.
        return DashboardNotificationsOptionsFlow()


class DashboardNotificationsOptionsFlow(OptionsFlow):
    """Manage the central topic registry one deliberate change at a time."""

    def _topics(self) -> list[dict[str, str]]:
        return list(self.config_entry.options.get(CONF_TOPICS, []))

    def _severity_colors(self) -> dict[str, str]:
        configured = self.config_entry.options.get(CONF_SEVERITY_COLORS, {})
        return {
            severity: self._as_hex_color(
                configured.get(severity), DEFAULT_SEVERITY_COLORS[severity]
            )
            for severity in SEVERITIES
        }

    @staticmethod
    def _as_hex_color(value: Any, default: str) -> str:
        """Read legacy RGB lists as a hex colour for the native picker."""
        if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value.lower()
        if isinstance(value, (list, tuple)) and len(value) == 3:
            try:
                channels = [max(0, min(255, int(channel))) for channel in value]
            except (TypeError, ValueError):
                return default
            return "#{:02x}{:02x}{:02x}".format(*channels)
        return default

    def _save_options(self, data: dict[str, Any]):
        """Preserve settings managed by other options-flow steps."""
        return self.async_create_entry(title="", data={**self.config_entry.options, **data})

    def _save_topics(self, topics: list[dict[str, str]]):
        return self._save_options({CONF_TOPICS: topics})

    async def async_step_init(self, user_input=None):
        return self.async_abort(reason="manage_in_settings_panel")

    async def async_step_severity_colors(self, user_input=None):
        if user_input is not None:
            return self._save_options({
                CONF_SEVERITY_COLORS: {
                    severity: user_input[severity] for severity in SEVERITIES
                }
            })
        colors = self._severity_colors()
        return self.async_show_form(
            step_id="severity_colors",
            data_schema=vol.Schema({
                vol.Required(severity, default=colors[severity]): selector.TextSelector(
                    {"type": "color"}
                )
                for severity in SEVERITIES
            }),
        )

    async def async_step_add_topic(self, user_input=None):
        errors = {}
        if user_input is not None:
            name = user_input[CONF_TOPIC_NAME].strip()
            if not name:
                errors[CONF_TOPIC_NAME] = "invalid_name"
            elif any(topic[CONF_TOPIC_NAME].casefold() == name.casefold() for topic in self._topics()):
                errors[CONF_TOPIC_NAME] = "duplicate_name"
            else:
                return self._save_topics(self._topics() + [{CONF_TOPIC_ID: str(uuid4()), CONF_TOPIC_NAME: name}])
        return self.async_show_form(
            step_id="add_topic",
            data_schema=vol.Schema({vol.Required(CONF_TOPIC_NAME): str}),
            errors=errors,
        )

    async def async_step_rename_topic(self, user_input=None):
        topics = self._topics()
        if not topics:
            return self.async_abort(reason="no_topics")
        errors = {}
        if user_input is not None:
            topic_id = user_input[CONF_TOPIC_ID]
            name = user_input[CONF_TOPIC_NAME].strip()
            if not name:
                errors[CONF_TOPIC_NAME] = "invalid_name"
            elif any(topic[CONF_TOPIC_ID] != topic_id and topic[CONF_TOPIC_NAME].casefold() == name.casefold() for topic in topics):
                errors[CONF_TOPIC_NAME] = "duplicate_name"
            else:
                return self._save_topics([
                    {**topic, CONF_TOPIC_NAME: name} if topic[CONF_TOPIC_ID] == topic_id else topic
                    for topic in topics
                ])
        return self.async_show_form(
            step_id="rename_topic",
            data_schema=vol.Schema({
                vol.Required(CONF_TOPIC_ID): vol.In({topic[CONF_TOPIC_ID]: topic[CONF_TOPIC_NAME] for topic in topics}),
                vol.Required(CONF_TOPIC_NAME): str,
            }),
            errors=errors,
        )

    async def async_step_remove_topic(self, user_input=None):
        topics = self._topics()
        if not topics:
            return self.async_abort(reason="no_topics")
        if user_input is not None:
            return self._save_topics([topic for topic in topics if topic[CONF_TOPIC_ID] != user_input[CONF_TOPIC_ID]])
        return self.async_show_form(
            step_id="remove_topic",
            data_schema=vol.Schema({vol.Required(CONF_TOPIC_ID): vol.In({topic[CONF_TOPIC_ID]: topic[CONF_TOPIC_NAME] for topic in topics})}),
        )
