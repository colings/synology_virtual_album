"""Expose Synology Virtual Album as a media source."""

from __future__ import annotations

from logging import getLogger
import mimetypes
from typing import TYPE_CHECKING

from homeassistant.components.media_player import MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
)
from homeassistant.components.synology_dsm.const import SHARED_SUFFIX
from homeassistant.components.synology_dsm.media_source import SynologyPhotosMediaSource
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

if TYPE_CHECKING:
    from . import SynologyVirtualAlbumConfigEntry

from .const import (
    CONF_VIRTUAL_ALBUM_ID,
    CONF_VIRTUAL_ALBUM_NAME,
    CONF_SYNOLOGY_DSM,
    DOMAIN,
)
from .synology_photos import get_dsm_config

LOGGER = getLogger(__name__)


async def async_get_media_source(hass: HomeAssistant) -> MediaSource:
    """Set up Synology media source."""
    entries = hass.config_entries.async_entries(
        DOMAIN, include_disabled=False, include_ignore=False
    )
    return SynologyVirtualAlbumMediaSource(hass, entries)


class SynologyVirtualAlbumMediaSource(SynologyPhotosMediaSource):
    """Provide Virtual Album as media sources."""

    name = "Synology Virtual Album"

    def __init__(self, hass: HomeAssistant, entries: list[ConfigEntry]) -> None:
        """Initialize virtual album source."""
        super().__init__(hass, entries)
        self.domain = DOMAIN

    async def async_browse_media(
        self,
        item: MediaSourceItem,
    ) -> BrowseMediaSource:
        """Return media."""
        # if not self.hass.config_entries.async_loaded_entries(DOMAIN):
        #    raise BrowseError("Diskstation not initialized")
        return BrowseMediaSource(
            domain=DOMAIN,
            identifier=None,
            media_class=MediaClass.DIRECTORY,
            media_content_type=MediaClass.IMAGE,
            title="Synology Virtual Album",
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.DIRECTORY,
            children=[
                *await self._async_build_album(item),
            ],
        )

    async def _async_build_album(
        self, item: MediaSourceItem
    ) -> list[BrowseMediaSource]:
        if not item.identifier:
            return [
                BrowseMediaSource(
                    domain=DOMAIN,
                    identifier=entry.data.get(CONF_VIRTUAL_ALBUM_ID),
                    media_class=MediaClass.DIRECTORY,
                    media_content_type=MediaClass.IMAGE,
                    title=entry.data.get(CONF_VIRTUAL_ALBUM_NAME),
                    can_play=False,
                    can_expand=True,
                )
                for entry in self.entries
            ]

        entry: SynologyVirtualAlbumConfigEntry | None = next(
            (
                entry
                for entry in self.hass.config_entries.async_entries(DOMAIN)
                if entry.data.get(CONF_VIRTUAL_ALBUM_ID) == item.identifier
            ),
            None,
        )

        assert entry
        assert entry.runtime_data is not None

        dsm_device_id = entry.data.get(CONF_SYNOLOGY_DSM)
        assert dsm_device_id
        dsm_config = get_dsm_config(self.hass, dsm_device_id)
        assert dsm_config

        album_items = await entry.runtime_data.get_virtual_album_items()

        ret = []

        for album_item in album_items:
            mime_type, _ = mimetypes.guess_type(album_item.file_name)
            if isinstance(mime_type, str) and mime_type.startswith("image/"):
                # Force small small thumbnails
                album_item.thumbnail_size = "sm"
                suffix = ""
                if album_item.is_shared:
                    suffix = SHARED_SUFFIX
                ret.append(
                    BrowseMediaSource(
                        domain=DOMAIN,
                        identifier=(
                            f"{dsm_config.unique_id}/"
                            f"{album_item.source_album_id}_{album_item.passphrase}/"
                            f"{album_item.thumbnail_cache_key}/"
                            f"{album_item.file_name}{suffix}"
                        ),
                        media_class=MediaClass.IMAGE,
                        media_content_type=mime_type,
                        title=album_item.file_name,
                        can_play=True,
                        can_expand=False,
                        thumbnail=await self.async_get_thumbnail(
                            album_item, dsm_config.runtime_data
                        ),
                    ),
                )

        return ret
