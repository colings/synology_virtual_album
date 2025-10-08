import re
from typing import Any

import voluptuous as vol

from homeassistant.components.synology_dsm.const import DOMAIN as SYNOLOGY_DOMAIN
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_UNIT_OF_MEASUREMENT
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CURRENT_IMAGE,
    CONF_DAILY_PERCENT,
    CONF_MAX_ALBUM_ITEMS,
    CONF_SOURCE_ALBUMS,
    CONF_SYNOLOGY_DSM,
    CONF_VIRTUAL_ALBUM_ID,
    CONF_VIRTUAL_ALBUM_NAME,
    CONF_WEEKLY_PERCENT,
    DOMAIN,
)
from .synology_photos import get_photos


async def _build_schema(hass, options: dict[str, Any]) -> vol.Schema:
    if dsm_device_id := options.get(CONF_SYNOLOGY_DSM):
        photos = get_photos(hass, dsm_device_id)
        albums = await photos.get_albums()

    all_albums = [
        selector.SelectOptionDict(value=str(album.album_id), label=album.name)
        for album in albums
    ]

    return vol.Schema(
        {
            vol.Optional(CONF_SOURCE_ALBUMS): selector.SelectSelector(
                {
                    "options": all_albums,
                    "mode": "dropdown",
                    "multiple": True,
                    "sort": True,
                }
            ),
            vol.Optional(
                CONF_MAX_ALBUM_ITEMS,
                default=500,
            ): selector.NumberSelector(
                {
                    "min": 1,
                    "max": 500,
                    "mode": "slider",
                }
            ),
            vol.Optional(
                CONF_DAILY_PERCENT,
                default=50,
            ): selector.NumberSelector(
                {
                    "min": 1,
                    "max": 100,
                    "mode": "slider",
                    CONF_UNIT_OF_MEASUREMENT: "%",
                }
            ),
            vol.Optional(
                CONF_WEEKLY_PERCENT,
                default=25,
            ): selector.NumberSelector(
                {
                    "min": 1,
                    "max": 100,
                    "mode": "slider",
                    CONF_UNIT_OF_MEASUREMENT: "%",
                }
            ),
            vol.Optional(
                CONF_CURRENT_IMAGE,
            ): selector.EntitySelector({"domain": "input_text"}),
        }
    )


class SynoVirtualAlbumConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configuration flow."""

    VERSION = 1

    def __init__(self) -> None:
        self.config_data: dict[str, Any] = {}

    def _clean_name(self, name: str) -> str:
        """Returns a cleaned up version of the album name, suitable for unique ids or entity ids.

        TODO: Seems like there's probably a HA function to accomplish this already.
        """
        # First pass, lowercase and replace any spaces with underscores
        lower_name = name.lower().replace(" ", "_")

        # Remove anything non-alphanumeric or underscore, and strip any leading or trailing underscores
        return re.sub(r"[^\da-z_]", "", lower_name).strip("_")

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            data_schema = vol.Schema(
                {
                    vol.Required(CONF_SYNOLOGY_DSM): selector.DeviceSelector(
                        selector.DeviceSelectorConfig(integration=SYNOLOGY_DOMAIN)
                    ),
                    vol.Required(
                        CONF_VIRTUAL_ALBUM_NAME, default="Slideshow"
                    ): selector.TextSelector(),
                }
            )

            return self.async_show_form(data_schema=data_schema, last_step=False)

        unique_id = self._clean_name(user_input.get(CONF_VIRTUAL_ALBUM_NAME))

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        user_input[CONF_VIRTUAL_ALBUM_ID] = unique_id

        self.config_data.update(user_input)
        return await self.async_step_options()

    async def async_step_options(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            data_schema = await _build_schema(self.hass, self.config_data)

            return self.async_show_form(step_id="options", data_schema=data_schema)

        self.config_data.update(user_input)

        title = "Synology Virtual Album " + self.config_data.get(
            CONF_VIRTUAL_ALBUM_NAME
        )

        return self.async_create_entry(title=title, data=self.config_data)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ):
        """Return the options flow."""
        return SynoVirtualAlbumOptionsFlow()


class SynoVirtualAlbumOptionsFlow(OptionsFlowWithReload):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            # All the options are allowed to be set in the base config, this is really just a reconfigure. So, copy
            # over the options we don't allow to be changed and update the base config with the new settings, then
            # return empty options.
            base_entries = (
                CONF_SYNOLOGY_DSM,
                CONF_VIRTUAL_ALBUM_NAME,
                CONF_VIRTUAL_ALBUM_ID,
            )
            for entry in base_entries:
                user_input[entry] = self.config_entry.data.get(entry)

            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input
            )
            return self.async_create_entry(data={})

        data_schema = await _build_schema(self.hass, self.config_entry.data)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                data_schema, self.config_entry.data
            ),
        )
