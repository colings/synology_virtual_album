"""Constants for Synology Virtual Album."""

from typing import Final

DOMAIN: Final = "synology_virtual_album"

CONF_SYNOLOGY_DSM: Final = "synology_dsm_device"
CONF_VIRTUAL_ALBUM_NAME: Final = "virtual_album_name"
CONF_VIRTUAL_ALBUM_ID: Final = "virtual_album_id"
CONF_SOURCE_ALBUMS: Final = "source_albums"
CONF_CURRENT_IMAGE: Final = "wallpanel_image_url_entity"
CONF_MAX_ALBUM_ITEMS: Final = "max_album_items"
CONF_DAILY_PERCENT: Final = "daily_percent"
CONF_WEEKLY_PERCENT: Final = "weekly_percent"
SERVICE_REBUILD_VIRTUAL_ALBUM: Final = "rebuild_virtual_album"
EVENT_CURRENT_PHOTO_CHANGED: Final = "synology_virtual_album_current_photo_changed"
