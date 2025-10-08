from calendar import isleap
from collections.abc import AsyncIterator
import datetime
import logging
import random
from urllib.parse import urlparse

from homeassistant.components.synology_dsm import SynologyDSMConfigEntry
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DAILY_PERCENT,
    CONF_MAX_ALBUM_ITEMS,
    CONF_SOURCE_ALBUMS,
    CONF_SYNOLOGY_DSM,
    CONF_WEEKLY_PERCENT,
)
from .synology_dsm_photos_ex import SynoPhotosAlbum, SynoPhotosEx, SynoPhotosItemEx

_LOGGER = logging.getLogger(__name__)


def get_dsm_config(
    hass: HomeAssistant, dsm_device_id: str
) -> SynologyDSMConfigEntry | None:
    """Given the device id for a DSM component instance, returns the config."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(dsm_device_id)
    dsm_config_entry: SynologyDSMConfigEntry = hass.config_entries.async_get_entry(
        device_entry.primary_config_entry
    )
    return dsm_config_entry


def get_photos(hass: HomeAssistant, dsm_device_id: str) -> SynoPhotosEx:
    """Given the device id for a DSM component instance, returns a photos object."""
    return SynoPhotosEx(get_dsm_config(hass, dsm_device_id).runtime_data.api.dsm)


def _make_day_comparable(
    date1: datetime.date, date2: datetime.date
) -> tuple[datetime.date, datetime.date]:
    """If one date is a leap day and the other isn't a leap year, adjusts the leap day to be a non-leap day instead.

    This function may change the year on a date, so that should be disregarded.
    """
    if isleap(date1.year) != isleap(date2.year):
        if date1.month == 2 and date1.day == 29:
            date1 = date1.replace(day=28, year=date2.year)
        elif date2.month == 2 and date2.day == 29:
            date2 = date2.replace(day=28, year=date1.year)

        if isleap(date1.year):
            date1 = date1.replace(year=date2.year)
        if isleap(date2.year):
            date2 = date2.replace(year=date1.year)

    return date1, date2


def is_today(compare_date: datetime.date) -> bool:
    """Return true if date is the same month and day as today, ignoring the year."""
    (today_clean, compare_clean) = _make_day_comparable(
        datetime.date.today(), compare_date
    )

    return (
        compare_clean.month == today_clean.month
        and compare_clean.day == today_clean.day
    )


def is_this_week(compare_date: datetime.date):
    """Return true if date is within one week of today (+/- 7 days), ignoring the year."""
    # First, get the day of the year (1-365/366 depending on if both are leap years)
    (today_clean, compare_clean) = _make_day_comparable(
        datetime.date.today(), compare_date
    )
    today_day = today_clean.timetuple().tm_yday
    compare_day = compare_clean.timetuple().tm_yday

    delta = abs(today_day - compare_day)

    # If the difference is too large, check the wrap-around case
    # e.g., Dec 30th and Jan 2nd
    if delta > 7:
        days_in_year = today_clean.replace(month=12, day=31).timetuple().tm_yday

        if today_day < compare_day:
            early_date, late_date = today_day, compare_day
        else:
            early_date, late_date = compare_day, today_day

        # Calculate the difference by wrapping around
        delta = (early_date + days_in_year) - late_date

    return delta <= 7


class SynologyPhotos:
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        self._hass = hass
        self.config_entry = config_entry
        self._photos: SynoPhotosEx = None
        self._thumbnails: dict[str, datetime.datetime] = {}
        self._current_album_items: list[SynoPhotosItemEx] = []
        self._source_albums: list[int] = []
        self._max_album_items: int = 500
        self._daily_max: int = 0
        self._weekly_max: int = 0

        config_data = self.config_entry.data

        if dsm_device_id := config_data.get(CONF_SYNOLOGY_DSM):
            self._photos = get_photos(self._hass, dsm_device_id)

        if source_albums := config_data.get(CONF_SOURCE_ALBUMS):
            for source_album in source_albums:
                self._source_albums.append(int(source_album))

        if max_items := config_data.get(CONF_MAX_ALBUM_ITEMS):
            self._max_album_items = int(max_items)

        if daily_percent := config_data.get(CONF_DAILY_PERCENT):
            self._daily_max = int(self._max_album_items * (daily_percent / 100.0))

        if weekly_percent := config_data.get(CONF_WEEKLY_PERCENT):
            self._weekly_max = int(self._max_album_items * (weekly_percent / 100.0))

    def get_image_date_from_url(self, image_url: str) -> datetime.datetime | None:
        url = urlparse(image_url)

        # This is similar to SynologyPhotosMediaSourceIdentifier, but not quite. Just parse it out manually.
        # http://[host]/synology_dsm/[server_id]]/[thumbnail_key]/[image_name]/?authSig=[key]
        parts = url.path.split("/")
        if len(parts) > 3:
            cache_key = parts[3]

            if photo_date := self._thumbnails.get(cache_key):
                return photo_date

        _LOGGER.warning("Couldn't find cached info for image: %s", image_url)
        return None

    def _get_subset(
        self, photos: list[SynoPhotosItemEx], max_count: int
    ) -> list[SynoPhotosItemEx]:
        if len(photos) <= max_count:
            return photos

        random.shuffle(photos)

        return photos[:max_count]

    async def rebuild_virtual_album(self) -> None:
        source_items: list[SynoPhotosItemEx] = []

        for source_album_id in self._source_albums:
            if source_album := await self._photos.get_album(source_album_id):
                async for item in self.get_album_items_chunked(source_album):
                    source_items.extend(item)

        new_items: list[SynoPhotosItemEx] = []

        def get_max_items(max_items):
            return min(max_items, self._max_album_items - len(new_items))

        if self._daily_max or self._weekly_max:
            this_day_items: list[SynoPhotosItemEx] = []
            this_week_items: list[SynoPhotosItemEx] = []

            for item in source_items:
                if is_today(item.time.date()):
                    this_day_items.append(item)
                elif is_this_week(item.time.date()):
                    this_week_items.append(item)

            new_items += self._get_subset(
                this_day_items, get_max_items(self._daily_max)
            )
            new_items += self._get_subset(
                this_week_items, get_max_items(self._weekly_max)
            )

            # Remove any images we used from the source, so we won't add them again
            unused_items: list[SynoPhotosItemEx] = []
            for item in source_items:
                if item not in new_items:
                    unused_items.append(item)
            source_items = unused_items

        # Add any remaining items up to the max
        new_items += self._get_subset(
            source_items, get_max_items(self._max_album_items)
        )

        for item in new_items:
            self._thumbnails[item.thumbnail_cache_key] = item.time

        self._current_album_items = new_items

    async def get_virtual_album_items(self) -> list[SynoPhotosItemEx]:
        if not self._current_album_items:
            await self.rebuild_virtual_album()

        return self._current_album_items

    async def get_album_items_chunked(
        self, album: SynoPhotosAlbum, chunk_size=100
    ) -> AsyncIterator[SynoPhotosItemEx]:
        cur_offset = 0

        while items := await self._photos.get_items_from_album_ex(
            album, cur_offset, chunk_size
        ):
            yield items
            cur_offset += len(items)
