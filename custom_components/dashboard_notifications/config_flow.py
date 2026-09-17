"""Config and options flows for Dashboard Notifications."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, OptionsFlow
from homeassistant.core import callback

from .const import CONF_TOPIC_ID, CONF_TOPIC_NAME, CONF_TOPICS, DOMAIN


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

    def _save_topics(self, topics: list[dict[str, str]]):
        # The options-flow manager writes this data to ConfigEntry.options when
        # the flow completes. Updating the entry directly here would be
        # overwritten by the empty completion payload.
        return self.async_create_entry(title="", data={CONF_TOPICS: topics})

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init", menu_options=["add_topic", "rename_topic", "remove_topic"]
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
