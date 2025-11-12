"""Device tracker for current photo."""

from __future__ import annotations

from homeassistant.components.device_tracker import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    CONF_CURRENT_IMAGE,
    CONF_VIRTUAL_ALBUM_ID,
    CONF_VIRTUAL_ALBUM_NAME,
    EVENT_CURRENT_PHOTO_CHANGED,
)

ADDRESS_ATTRS = [
    "country",
    "state",
    "county",
    "city",
    "town",
    "district",
    "village",
    "route",
    "landmark",
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the current photo tracker from config entry."""
    if config_entry.data.get(CONF_CURRENT_IMAGE):
        async_add_entities([CurrentPhotoDeviceTracker(hass, config_entry)], True)


class CurrentPhotoDeviceTracker(TrackerEntity):
    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the Tracker."""
        super().__init__()
        self._attr_should_poll = False
        self._attr_has_entity_name = True
        self._attr_translation_key = "current_photo_location"
        self._attr_unique_id = config_entry.data.get(CONF_VIRTUAL_ALBUM_ID)
        self._attr_translation_placeholders = {
            "album_name": config_entry.data.get(CONF_VIRTUAL_ALBUM_NAME)
        }
        self._attr_extra_state_attributes = dict.fromkeys(ADDRESS_ATTRS)

        hass.bus.async_listen(
            EVENT_CURRENT_PHOTO_CHANGED, self._async_update_image_location
        )

    @callback
    def _async_update_image_location(self, event: Event[EventStateChangedData]) -> None:
        # First clear out all the attributes, so if this image doesn't have any of them they won't be using old values
        self._attr_latitude = self._attr_longitude = None
        self._attr_extra_state_attributes = dict.fromkeys(ADDRESS_ATTRS)

        if additional := event.data.get("additional"):
            if gps := additional.get("gps"):
                self._attr_latitude = gps.get("latitude")
                self._attr_longitude = gps.get("longitude")
            if address := additional.get("address"):
                self._attr_extra_state_attributes = {
                    attr: address.get(attr) for attr in ADDRESS_ATTRS
                }

        self.async_write_ha_state()
