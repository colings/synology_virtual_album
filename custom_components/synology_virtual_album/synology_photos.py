"""Helpers for interacting with the Synology DSM integration."""

from asyncio import Task
from calendar import isleap
import datetime
import logging
import random
from typing import TypedDict
from urllib.parse import urlparse

from homeassistant.components.synology_dsm import SynologyDSMConfigEntry
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.event import (
    Event,
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.helpers.storage import Store

from .const import (
    CONF_CURRENT_IMAGE,
    CONF_DAILY_IMAGES,
    CONF_MAX_ALBUM_IMAGES,
    CONF_SOURCE_ALBUMS,
    CONF_SYNOLOGY_DSM,
    CONF_VIRTUAL_ALBUM_ID,
    CONF_WEEKLY_IMAGES,
    DOMAIN,
    EVENT_CURRENT_PHOTO_CHANGED,
)
from .synology_dsm_photos_ex import SynoPhotosEx, SynoPhotosItemEx

_LOGGER = logging.getLogger(__name__)
STORE_INTERVAL_SECONDS = 10 * 60


class StorageData(TypedDict):
    # The item ids of the current album images
    current_album: list[int]
    # Mapping from an image id to the last viewed date, as an ordinal
    last_viewed: dict[int, int]


def get_dsm_config(
    hass: HomeAssistant, dsm_device_id: str
) -> SynologyDSMConfigEntry | None:
    """Given the device id for a DSM component instance, returns the config."""
    device_registry = dr.async_get(hass)
    device_entry = device_registry.async_get(dsm_device_id)
    if device_entry and device_entry.primary_config_entry:
        dsm_config_entry: SynologyDSMConfigEntry | None = (
            hass.config_entries.async_get_entry(device_entry.primary_config_entry)
        )
        return dsm_config_entry
    return None


def get_photos(hass: HomeAssistant, dsm_device_id: str) -> SynoPhotosEx | None:
    """Given the device id for a DSM component instance, returns a photos object."""
    if config_entry := get_dsm_config(hass, dsm_device_id):
        return SynoPhotosEx(config_entry.runtime_data.api.dsm)
    return None


def create_store(hass: HomeAssistant, config_entry: ConfigEntry) -> Store | None:
    if album_id := config_entry.data.get(CONF_VIRTUAL_ALBUM_ID):
        store_key = DOMAIN + "_" + album_id
        return Store[StorageData](hass, 1, store_key)
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
    """Return true if date is in the next 7 days, ignoring the year."""
    (today_clean, compare_clean) = _make_day_comparable(
        datetime.date.today(), compare_date
    )

    # First, get the day of the year (1-365/366 depending on if both are leap years)
    today_day = today_clean.timetuple().tm_yday
    compare_day = compare_clean.timetuple().tm_yday

    # We're looking for photos in the coming week, so if the compare day is before today, change it to a negative day.
    # This is to handle the wraparound case (for example, Dec 30th to January 2nd).
    if compare_day < today_day:
        days_in_year = today_clean.replace(month=12, day=31).timetuple().tm_yday
        today_day = today_day - days_in_year

    delta = compare_day - today_day

    return delta <= 7


class SynologyPhotos:
    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
    ) -> None:
        # If we aren't able to get the DSM component there's no point in running, so exit now
        if not (dsm_device_id := config_entry.data.get(CONF_SYNOLOGY_DSM)) or not (
            photos := get_photos(hass, dsm_device_id)
        ):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_loaded",
                translation_placeholders={"target": config_entry.title},
            )

        # The only way we should fail to create the store is if our configuration is bad, so exit in that case
        if not (store := create_store(hass, config_entry)):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="not_loaded",
                translation_placeholders={"target": config_entry.title},
            )

        self._hass = hass
        self.config_entry = config_entry
        self._photos: SynoPhotosEx = photos
        self._current_album_items: list[SynoPhotosItemEx] = []
        self._last_viewed: dict[int, int] = {}
        self._store = store
        self._last_store: datetime.datetime | None = None
        self._running_store: Task | None = None
        self._photos = photos

        if current_image := self.config_entry.data.get(CONF_CURRENT_IMAGE):
            async_track_state_change_event(
                hass,
                current_image,
                self._async_update_current_image,
            )

        self._running_store = self._hass.loop.create_task(self._async_init())

    async def shutdown(self):
        if self._running_store:
            await self._running_store

    async def _async_init(self):
        if stored_data := await self._read_store():
            current_album = stored_data["current_album"]

            if current_album:
                _LOGGER.debug(
                    "Found %d items from previously generated album", len(current_album)
                )

                source_items = await self._get_source_items()

                _LOGGER.debug("Found %d source items", len(source_items))

                for item_id in current_album:
                    item = next(
                        (item for item in source_items if item.item_id == item_id), None
                    )
                    if item:
                        self._current_album_items.append(item)

                _LOGGER.debug("Matched %d items", len(self._current_album_items))
            else:
                _LOGGER.debug("No previously generated album items found")

        self._running_store = None

    async def _read_store(self) -> StorageData | None:
        stored = await self._store.async_load()

        # JSON only supports string keys, so convert any loaded item ids back to integers
        if stored and "last_viewed" in stored:
            cleaned = {int(k): v for k, v in stored["last_viewed"].items()}
            stored["last_viewed"] = cleaned

        return stored

    async def _write_store(
        self, last_viewed: dict[int, int] | None, album_items: list[int] | None
    ):
        current_data = await self._read_store()

        if not current_data:
            current_data = {"last_viewed": {}, "current_album": []}

        if last_viewed:
            current_data["last_viewed"].update(last_viewed)
        if album_items:
            current_data["current_album"] = album_items

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
                        self._write_store(self._last_viewed, None)
                    )
                    self._last_viewed = {}
                else:
                    _LOGGER.warning("Store is still running when next store triggered")

    async def _async_update_current_image(
        self, event: Event[EventStateChangedData]
    ) -> None:
        if not (new_state := event.data.get("new_state")):
            return

        image_url = new_state.state
        url = urlparse(image_url)

        item: SynoPhotosItemEx | None = None

        # This is similar to SynologyPhotosMediaSourceIdentifier, but not quite. Just parse it out manually.
        # http://[host]/synology_dsm/[server_id]]/[thumbnail_key]/[image_name]/?authSig=[key]
        parts = url.path.split("/")
        if len(parts) > 3:
            thumbnail_cache_key = parts[3]

            item = next(
                (
                    item
                    for item in self._current_album_items
                    if item.thumbnail_cache_key == thumbnail_cache_key
                ),
                None,
            )

        if item:
            self._last_viewed[item.item_id] = datetime.date.today().toordinal()
            self._queue_cache_write()

            _LOGGER.debug("Getting info for item %d", item.item_id)

            photo_info = await self._photos.get_info(item)

            if not photo_info:
                photo_info = {}

            self._hass.bus.fire(EVENT_CURRENT_PHOTO_CHANGED, photo_info)
        else:
            _LOGGER.warning("Couldn't find cached info for image: %s", image_url)

    def _get_subset(
        self, photos: list[SynoPhotosItemEx], max_count: int
    ) -> list[SynoPhotosItemEx]:
        if len(photos) <= max_count:
            return photos

        return photos[:max_count]

    async def _get_source_items(self) -> list[SynoPhotosItemEx]:
        source_items: list[SynoPhotosItemEx] = []

        # Build up a list of all the photos in the source albums. This could be thousands of items,
        # so it can take seconds for this to complete.
        if source_albums := self.config_entry.data.get(CONF_SOURCE_ALBUMS):
            for source_album_str in source_albums:
                source_album_id = int(source_album_str)

                if source_album := await self._photos.get_album(source_album_id):
                    async for items in self._photos.get_items_from_album_chunked(
                        source_album
                    ):
                        source_items.extend(items)

        return source_items

    async def rebuild_virtual_album(self) -> None:
        _LOGGER.debug("Rebuilding album")

        config_data = self.config_entry.data

        source_items = await self._get_source_items()

        _LOGGER.debug("Found %d source items", len(source_items))

        # Shuffle the items. We're about to sort them in the next step, but it's a stable sort, so this takes care of
        # randomizing the order of anything that's never been viewed.
        random.shuffle(source_items)

        # Load the last viewed dates and sort the items so the most recently viewed are last
        if stored_data := await self._read_store():
            if last_viewed := stored_data.get("last_viewed"):
                _LOGGER.debug("Found %d last viewed times", len(last_viewed))
                source_items.sort(key=lambda item: last_viewed.get(item.item_id, 0))

        max_album_items = int(config_data.get(CONF_MAX_ALBUM_IMAGES, 0))
        daily_max = min(config_data.get(CONF_DAILY_IMAGES, 0), max_album_items)
        weekly_max = min(config_data.get(CONF_WEEKLY_IMAGES, 0), max_album_items)

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
                "Found %d items from this day and %d from this week (%d day max, %d week max)",
                len(this_day_items),
                len(this_week_items),
                daily_max,
                weekly_max,
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

        self._current_album_items = new_items

        new_ids = [item.item_id for item in new_items]
        last_viewed = None

        # If there isn't a current image we assume _async_update_current_image won't be getting called to cache off the
        # viewed date. In that case, mark all the new album items as viewed today.
        if CONF_CURRENT_IMAGE not in self.config_entry.data:
            cur_date = datetime.date.today().toordinal()
            last_viewed = dict.fromkeys(new_ids, cur_date)

        await self._write_store(last_viewed, new_ids)

    async def get_virtual_album_items(self) -> list[SynoPhotosItemEx]:
        if not self._current_album_items:
            await self.rebuild_virtual_album()

        return self._current_album_items
