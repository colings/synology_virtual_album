from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from . import SynologyVirtualAlbumConfigEntry
from .const import DOMAIN, SERVICE_REBUILD_VIRTUAL_ALBUM


def setup_services(hass: HomeAssistant) -> None:
    def get_config_entry(call: ServiceCall) -> SynologyVirtualAlbumConfigEntry:
        entry_id = call.data.get("album")
        if not (entry := hass.config_entries.async_get_entry(entry_id)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="integration_not_found",
                translation_placeholders={"target": DOMAIN},
            )
        if entry.state is not ConfigEntryState.LOADED:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_loaded",
                translation_placeholders={"target": entry.title},
            )
        return entry

    @callback
    async def rebuild_virtual_album(call: ServiceCall) -> None:
        entry: SynologyVirtualAlbumConfigEntry = get_config_entry(call)
        await entry.runtime_data.rebuild_virtual_album()

    hass.services.async_register(
        DOMAIN, SERVICE_REBUILD_VIRTUAL_ALBUM, rebuild_virtual_album
    )
