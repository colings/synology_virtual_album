from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .services import setup_services
from .synology_photos import SynologyPhotos

PLATFORMS: list[Platform] = [Platform.SENSOR]

type SynologyVirtualAlbumConfigEntry = ConfigEntry[SynologyPhotos]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    setup_services(hass)

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SynologyVirtualAlbumConfigEntry
) -> bool:
    entry.runtime_data = SynologyPhotos(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SynologyVirtualAlbumConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
