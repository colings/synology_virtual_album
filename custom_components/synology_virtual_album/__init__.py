"""Support for the Synology virtual albums."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .services import setup_services
from .synology_photos import SynologyPhotos, create_store

PLATFORMS: list[Platform] = [Platform.SENSOR]

type SynologyVirtualAlbumConfigEntry = ConfigEntry[SynologyPhotos]


async def async_setup(hass: HomeAssistant, _: ConfigType) -> bool:
    """Set up the virtual album component."""
    setup_services(hass)

    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SynologyVirtualAlbumConfigEntry
) -> bool:
    """Set up virtual album integration from a config entry."""
    entry.runtime_data = SynologyPhotos(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SynologyVirtualAlbumConfigEntry
) -> bool:
    """Unload a config entry."""
    await entry.runtime_data.shutdown()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(
    hass: HomeAssistant, entry: SynologyVirtualAlbumConfigEntry
) -> None:
    """Handle removal of a config entry."""
    if temp_store := create_store(hass, entry):
        await temp_store.async_remove()
