"""Topic summary sensor for Dashboard Notifications."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import (
    AddEntitiesCallback,
    async_get_current_platform,
)
from homeassistant.util import slugify

from .const import DATA_MANAGERS, DOMAIN, SIGNAL_FEED_UPDATED
from .manager import NotificationManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the topic summary sensor."""
    manager: NotificationManager = hass.data[DOMAIN][DATA_MANAGERS][entry.entry_id]
    topic_sensors = {
        topic["id"]: TopicNotificationCountSensor(manager, topic["id"])
        for topic in manager.topics
    }
    async_add_entities([
        DashboardNotificationTopicsSensor(manager),
        DashboardNotificationTotalCountSensor(manager),
        *topic_sensors.values(),
    ])
    platform = async_get_current_platform()

    @callback
    def async_refresh_topic_sensors(entry_id: str) -> None:
        """Synchronize sensor entities with topic registry/feed changes."""
        if entry_id != manager.entry_id:
            return

        active_ids = {topic["id"] for topic in manager.topics}
        added_ids = active_ids - topic_sensors.keys()
        if added_ids:
            new_sensors = {
                topic_id: TopicNotificationCountSensor(manager, topic_id)
                for topic_id in added_ids
            }
            topic_sensors.update(new_sensors)
            async_add_entities(new_sensors.values())

        removed_ids = topic_sensors.keys() - active_ids
        for topic_id in removed_ids:
            sensor = topic_sensors.pop(topic_id)
            hass.async_create_task(platform.async_remove_entity(sensor.entity_id))

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_FEED_UPDATED, async_refresh_topic_sensors)
    )


class DashboardNotificationTopicsSensor(SensorEntity):
    """Expose configured notification topics on the integration page."""

    _attr_has_entity_name = True
    _attr_name = "Topics"
    _attr_icon = "mdi:tag-multiple"

    def __init__(self, manager: NotificationManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry_id}_topics"

    @property
    def native_value(self) -> str:
        """Return topic names for direct visibility in the integration UI."""
        names = [topic["name"] for topic in self._manager.topics]
        if not names:
            return "No topics"
        value = ", ".join(names)
        # Home Assistant entity states are limited to 255 characters; the full
        # list remains available in the attributes below.
        return value if len(value) <= 255 else f"{value[:251]}…"

    @property
    def extra_state_attributes(self) -> dict[str, list[dict[str, str]]]:
        """Expose topic IDs and display names for inspection and templates."""
        return {"topics": self._manager.topics}

    async def async_added_to_hass(self) -> None:
        """Subscribe to topic registry changes."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FEED_UPDATED, self._handle_feed_updated
            )
        )

    @callback
    def _handle_feed_updated(self, entry_id: str) -> None:
        if entry_id == self._manager.entry_id:
            self.async_write_ha_state()


class DashboardNotificationTotalCountSensor(SensorEntity):
    """Expose the total number of active notification feed items."""

    _attr_has_entity_name = True
    _attr_name = "Active notifications"
    _attr_icon = "mdi:bell-badge-outline"

    def __init__(self, manager: NotificationManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{manager.entry_id}_active_notifications"
        self._attr_suggested_object_id = "dashboard_notifications_active"

    @property
    def native_value(self) -> int:
        """Return the total active feed-item count."""
        return len(self._manager.feed())

    async def async_added_to_hass(self) -> None:
        """Update promptly on any feed mutation."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FEED_UPDATED, self._handle_feed_updated
            )
        )

    @callback
    def _handle_feed_updated(self, entry_id: str) -> None:
        if entry_id == self._manager.entry_id:
            self.async_write_ha_state()


class TopicNotificationCountSensor(SensorEntity):
    """Expose the active-notification count for one configured topic."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:bell-badge-outline"

    def __init__(self, manager: NotificationManager, topic_id: str) -> None:
        self._manager = manager
        self._topic_id = topic_id
        topic = self._topic
        self._topic_name = topic["name"]
        self._attr_unique_id = f"{manager.entry_id}_{topic_id}_notifications"
        self._attr_suggested_object_id = f"{slugify(topic['name'])}_notifications"

    @property
    def _topic(self) -> dict[str, str] | None:
        return next(
            (topic for topic in self._manager.topics if topic["id"] == self._topic_id),
            None,
        )

    @property
    def name(self) -> str:
        """Return the current display name for this topic's notification count."""
        if topic := self._topic:
            self._topic_name = topic["name"]
        return f"{self._topic_name} notifications"

    @property
    def native_value(self) -> int:
        """Return active feed-item count for this topic."""
        return sum(item["topic"] == self._topic_id for item in self._manager.feed())

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose stable topic identity for templates and debugging."""
        if topic := self._topic:
            self._topic_name = topic["name"]
        return {"topic_id": self._topic_id, "topic_name": self._topic_name}

    async def async_added_to_hass(self) -> None:
        """Update promptly on any feed mutation."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_FEED_UPDATED, self._handle_feed_updated
            )
        )

    @callback
    def _handle_feed_updated(self, entry_id: str) -> None:
        if entry_id == self._manager.entry_id and self._topic is not None:
            self.async_write_ha_state()
