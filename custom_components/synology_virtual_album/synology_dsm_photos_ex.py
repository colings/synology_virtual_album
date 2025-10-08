from dataclasses import dataclass
import datetime

from synology_dsm.api.photos import SynoPhotos, SynoPhotosAlbum, SynoPhotosItem


@dataclass
class SynoPhotosItemEx(SynoPhotosItem):
    time: datetime
    source_album_id: int


class SynoPhotosEx(SynoPhotos):
    """An extension of the base Synology Photos, adding more functions.

    Ideally this would be merged into the library
    """

    BROWSE_NORMAL_ALBUM_API_KEY = "SYNO.Foto.Browse.NormalAlbum"

    async def get_exif(self, item: SynoPhotosItem) -> dict | None:
        raw_data = await self._dsm.get(
            self.BROWSE_ITEM_API_KEY,
            "get_exif",
            {"id": f"[{item.item_id}]"},
        )
        if not isinstance(raw_data, dict):
            return None
        if (data := raw_data.get("data")) is None:
            return None
        if len(data["list"]) == 1 and "exif" in data["list"][0]:
            return data["list"][0]["exif"]
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

        for album in await self.get_albums():
            if album.album_id == album_id:
                return album

        return None

    async def get_items_from_album_ex(
        self, album: SynoPhotosAlbum, offset: int = 0, limit: int = 100
    ) -> list[SynoPhotosItemEx] | None:
        """Get a list of all items from given album."""
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
