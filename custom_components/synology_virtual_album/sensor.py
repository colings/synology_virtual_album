from datetime import date, datetime
import zoneinfo

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.dt import get_age

from .const import (
    CONF_CURRENT_IMAGE,
    CONF_VIRTUAL_ALBUM_ID,
    CONF_VIRTUAL_ALBUM_NAME,
    EVENT_CURRENT_PHOTO_CHANGED,
)
from .synology_photos import is_this_week, is_today

ATTR_DESCRIPTION = "Description"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    if config_entry.data.get(CONF_CURRENT_IMAGE):
        async_add_entities([PhotoDateSensor(hass, config_entry)], True)


class PhotoDateSensor(SensorEntity):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._attr_device_class = SensorDeviceClass.DATE
        self._attr_should_poll = False
        self._attr_has_entity_name = True
        self._attr_translation_key = "current_photo_date"
        self._attr_unique_id = (
            entry.data.get(CONF_VIRTUAL_ALBUM_ID) + "_current_photo_date"
        )
        self._attr_translation_placeholders = {
            "album_name": entry.data.get(CONF_VIRTUAL_ALBUM_NAME)
        }
        self._attr_extra_state_attributes = {
            ATTR_DESCRIPTION: None,
        }
        self._state: date | None = None

        hass.bus.async_listen(
            EVENT_CURRENT_PHOTO_CHANGED, self._async_update_image_description
        )

    @property
    def state(self) -> date | None:
        """Return the current state."""
        return self._state

    @callback
    def _async_update_image_description(
        self, event: Event[EventStateChangedData]
    ) -> None:
        photo_date = None

        if time_str := event.data.get("time"):
            photo_date = datetime.fromtimestamp(time_str)

        date_text = ""

        if photo_date:
            today = date.today()
            years_ago = today.year - photo_date.year

            date_with_timezone = photo_date.replace(tzinfo=zoneinfo.ZoneInfo("UTC"))

            date_text = get_age(date_with_timezone) + " ago"

            if is_today(photo_date.date()):
                if years_ago == 0:
                    date_text = "Today"
                else:
                    date_text += " today"
            elif is_this_week(photo_date.date()):
                years_ago = today.year - photo_date.year
                if years_ago == 0:
                    date_text = "This week"
                else:
                    date_text = "This week " + date_text

        self._state = photo_date
        self._attr_extra_state_attributes[ATTR_DESCRIPTION] = date_text

        self.async_write_ha_state()
