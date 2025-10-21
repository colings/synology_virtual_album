"""Helpers to add functionality to the SynoPhotos class in the Synology DSM integration.

Ideally this would be merged into the base library
"""

from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
import datetime

from synology_dsm.api.photos import SynoPhotos, SynoPhotosAlbum, SynoPhotosItem


@dataclass
class SynoPhotosItemEx(SynoPhotosItem):
    time: datetime
    source_album_id: int


class SynoPhotosEx(SynoPhotos):
    """An extension of the base Synology Photos, adding more functions."""

    BROWSE_NORMAL_ALBUM_API_KEY = "SYNO.Foto.Browse.NormalAlbum"

    async def get_info(self, item: SynoPhotosItem) -> dict | None:
        """Returns extended info for a photo item."""
        params = {
            "id": f"[{item.item_id}]",
            "additional": '["description","tag","exif","resolution","orientation","gps","video_meta","video_convert","thumbnail","address","geocoding_id","rating","motion_photo","provider_user_id","person"]',
        }

        if item.passphrase:
            params["passphrase"] = item.passphrase

        raw_data = await self._dsm.get(
            self.BROWSE_ITEM_API_KEY,
            "get",
            params,
        )
        if not isinstance(raw_data, dict):
            return None
        if (data := raw_data.get("data")) is None:
            return None
        if len(data["list"]) == 1:
            return data["list"][0]

        return None

    async def get_album(self, album_id: int) -> SynoPhotosAlbum | None:
        """Get an album by id."""
        raw_data = await self._dsm.get(
            self.BROWSE_ALBUMS_API_KEY,
            "get",
            {"id": f"[{album_id}]", "category": "normal_share_with_me"},
        )
        if not isinstance(raw_data, dict) or (data := raw_data.get("data")) is None:
            return None

        if len(data["list"]) == 1:
            album = data["list"][0]
            return SynoPhotosAlbum(
                album["id"],
                album["name"],
                album["item_count"],
                album["passphrase"],
            )

        # FIXME: Sometimes the above call does not find the album by ID. Why? As a temporary fix, iterate all albums in that case.
        async for album in self.get_albums_chunked():
            if album.album_id == album_id:
                return album

        return None

    async def get_items_from_album_ex(
        self, album: SynoPhotosAlbum, offset: int = 0, limit: int = 100
    ) -> list[SynoPhotosItemEx] | None:
        """Extension of get_items_from_album that also returns the capture time of the item."""
        params = {
            "offset": offset,
            "limit": limit,
            "additional": '["thumbnail"]',
        }
        if album.passphrase:
            params["passphrase"] = album.passphrase
        else:
            params["album_id"] = album.album_id

        raw_data = await self._dsm.get(
            self.BROWSE_ITEM_API_KEY,
            "list",
            params,
        )

        album_items = self._raw_data_to_items(raw_data, album.passphrase)

        ret: list[SynoPhotosItemEx] = []

        if album_items:
            for item, raw_item in zip(
                album_items, raw_data.get("data")["list"], strict=True
            ):
                ex = SynoPhotosItemEx(
                    item.item_id,
                    item.item_type,
                    item.file_name,
                    item.file_size,
                    item.thumbnail_cache_key,
                    item.thumbnail_size,
                    item.is_shared,
                    item.passphrase,
                    datetime.datetime.fromtimestamp(raw_item["time"]),
                    album.album_id,
                )
                ret.append(ex)

        return ret

    async def get_items_from_album_chunked(
        self, album: SynoPhotosAlbum, chunk_size=100
    ) -> AsyncIterator[list[SynoPhotosItemEx]]:
        """Replacement for get_items_from_album, to avoid the busywork of the caller managing the offset."""
        cur_offset = 0

        while items := await self.get_items_from_album_ex(
            album, cur_offset, chunk_size
        ):
            yield items
            cur_offset += len(items)

    async def get_albums_chunked(
        self, chunk_size=100
    ) -> AsyncGenerator[SynoPhotosAlbum]:
        """Replacement for get_albums, to avoid the busywork of the caller managing the offset."""
        cur_offset = 0

        while albums := await self.get_albums(cur_offset, chunk_size):
            for album in albums:
                yield album
            cur_offset += len(albums)
