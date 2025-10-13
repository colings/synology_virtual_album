"""Helpers for interacting with the Synology DSM integration."""

from asyncio import Task
from calendar import isleap
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
    CONF_VIRTUAL_ALBUM_ID,
    CONF_WEEKLY_PERCENT,
    DOMAIN,
)
from .synology_dsm_photos_ex import SynoPhotosEx, SynoPhotosItemEx

_LOGGER = logging.getLogger(__name__)
STORE_INTERVAL_SECONDS = 10 * 60


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


def create_store(hass: HomeAssistant, config_entry: ConfigEntry) -> Store | None:
    if album_id := config_entry.data.get(CONF_VIRTUAL_ALBUM_ID):
        store_key = DOMAIN + "_" + album_id
        return Store[dict[int, float]](hass, 1, store_key)
    return None


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
        self._current_album_items: list[SynoPhotosItemEx] = []
        # Quick lookup for the current virtual album items, from a thumbnail id to a capture time and item id
        self._thumbnails: dict[str, tuple[datetime.datetime, int]] = {}
        self._last_viewed: dict[int, float] = {}
        self._last_store: datetime.datetime = None
        self._running_store: Task = None

        if dsm_device_id := self.config_entry.data.get(CONF_SYNOLOGY_DSM):
            self._photos = get_photos(self._hass, dsm_device_id)

        self._store = create_store(hass, config_entry)

    async def shutdown(self):
        if self._running_store:
            await self._running_store

    async def _read_store(self) -> dict[int, float] | None:
        # JSON only supports string keys, so convert any loaded ones back to integers
        if last_used := await self._store.async_load():
            return {int(k): v for k, v in last_used.items()}
        return None

    async def _write_store(self, latest: dict[int, float]):
        if current_data := await self._read_store():
            current_data.update(latest)
        else:
            current_data = latest

        await self._store.async_save(current_data)

        self._running_store = None

    def _queue_cache_write(self):
        if self._last_store is None:
            self._last_store = datetime.datetime.now()
        else:
            time_since_last_store = datetime.datetime.now() - self._last_store
            if time_since_last_store.total_seconds() > STORE_INTERVAL_SECONDS:
                if self._running_store is None:
                    _LOGGER.info(
                        "Writing last viewed cache with %d items",
                        len(self._last_viewed),
                    )
                    self._last_store = datetime.datetime.now()
                    self._running_store = self._hass.loop.create_task(
                        self._write_store(self._last_viewed)
                    )
                    self._last_viewed = {}
                else:
                    _LOGGER.warning("Store is still running when next store triggered")

    def get_image_date_from_url(self, image_url: str) -> datetime.datetime | None:
        url = urlparse(image_url)

        # This is similar to SynologyPhotosMediaSourceIdentifier, but not quite. Just parse it out manually.
        # http://[host]/synology_dsm/[server_id]]/[thumbnail_key]/[image_name]/?authSig=[key]
        parts = url.path.split("/")
        if len(parts) > 3:
            thumbnail_cache_key = parts[3]

            if thumbnail_cache_key in self._thumbnails:
                (capture_time, item_id) = self._thumbnails.get(thumbnail_cache_key)

                _LOGGER.debug("Getting info for item %d", item_id)

                self._last_viewed[item_id] = datetime.datetime.now().timestamp()
                self._queue_cache_write()

                return capture_time

        _LOGGER.warning("Couldn't find cached info for image: %s", image_url)
        return None

    def _get_subset(
        self, photos: list[SynoPhotosItemEx], max_count: int
    ) -> list[SynoPhotosItemEx]:
        if len(photos) <= max_count:
            return photos

        return photos[:max_count]

    async def rebuild_virtual_album(self) -> None:
        _LOGGER.debug("Rebuilding album")

        config_data = self.config_entry.data

        source_items: list[SynoPhotosItemEx] = []

        # Build up a list of all the photos in the source albums. This could be thousands of items,
        # so it can take seconds for this to complete.
        if source_albums := config_data.get(CONF_SOURCE_ALBUMS):
            for source_album_str in source_albums:
                source_album_id = int(source_album_str)

                if source_album := await self._photos.get_album(source_album_id):
                    async for items in self._photos.get_items_from_album_chunked(
                        source_album
                    ):
                        source_items.extend(items)

        _LOGGER.debug("Found %d source items", len(source_items))

        # Shuffle the items. We're about to sort them in the next step, but it's a stable sort, so this takes care of
        # randomizing the order of anything that's never been viewed.
        random.shuffle(source_items)

        # Load the last viewed times and sort the items so the most recently viewed are last
        if last_used := await self._read_store():
            _LOGGER.debug("Found %d last used times", len(last_used))
            source_items.sort(key=lambda item: last_used.get(item.item_id, 0.0))

        max_album_items = int(config_data.get(CONF_MAX_ALBUM_ITEMS, 0))

        daily_percent = int(config_data.get(CONF_DAILY_PERCENT, 0))
        daily_max = int(max_album_items * (daily_percent / 100.0))

        weekly_percent = int(config_data.get(CONF_WEEKLY_PERCENT, 0))
        weekly_max = int(max_album_items * (weekly_percent / 100.0))

        new_items: list[SynoPhotosItemEx] = []

        def get_max_items(max_items):
            return min(max_items, max_album_items - len(new_items))

        if daily_max > 0 or weekly_max > 0:
            this_day_items: list[SynoPhotosItemEx] = []
            this_week_items: list[SynoPhotosItemEx] = []

            for item in source_items:
                if is_today(item.time.date()):
                    this_day_items.append(item)
                elif is_this_week(item.time.date()):
                    this_week_items.append(item)

            _LOGGER.debug(
                "Found %d items from this day and %d from this week",
                len(this_day_items),
                len(this_week_items),
            )

            new_items += self._get_subset(this_day_items, get_max_items(daily_max))
            new_items += self._get_subset(this_week_items, get_max_items(weekly_max))

            # Remove any images we used from the source, so we won't add them again
            unused_items: list[SynoPhotosItemEx] = []
            for item in source_items:
                if item not in new_items:
                    unused_items.append(item)
            source_items = unused_items

        # Add any remaining items up to the max
        new_items += self._get_subset(source_items, get_max_items(max_album_items))

        for item in new_items:
            self._thumbnails[item.thumbnail_cache_key] = (item.time, item.item_id)

        self._current_album_items = new_items

    async def get_virtual_album_items(self) -> list[SynoPhotosItemEx]:
        if not self._current_album_items:
            await self.rebuild_virtual_album()

        return self._current_album_items
