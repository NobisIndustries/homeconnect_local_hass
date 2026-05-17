"""Light entities."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.components.light.const import DEFAULT_MAX_KELVIN, DEFAULT_MIN_KELVIN
from homeassistant.util.color import (
    brightness_to_value,
    color_rgb_to_hex,
    match_max_scale,
    rgb_hex_to_rgb_list,
    value_to_brightness,
)
from homeassistant.util.scaling import scale_ranged_value_to_int_range
from homeconnect_websocket.errors import CodeResponsError
from homeconnect_websocket.message import Action
from homeconnect_websocket.message import Message as HC_Message

from .entity import HCEntity
from .helpers import create_entities, error_decorator

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import HCLightEntityDescription

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up light platform."""
    entities = create_entities({"light": HCLight}, config_entry.runtime_data)
    async_add_entites(entities)


class HCLight(HCEntity, LightEntity):
    """Light Entity."""

    entity_description: HCLightEntityDescription
    _brightness_entity: HcEntity | None = None
    _color_temperature_entity: HcEntity | None = None
    _color_entity: HcEntity | None = None
    _color_mode_entity: HcEntity | None = None
    _color_temp_inverted: bool = False
    # When the color-temp entity is a discrete enum (Bosch hoods), the slider maps
    # to value_raw 1..5 (warm..cold). The 0 = "custom" slot is read-only fallback.
    _color_temp_enum_range: tuple[int, int] | None = None

    def __init__(
        self,
        entity_description: HCLightEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        if entity_description.brightness_entity is not None:
            self._brightness_entity = self._runtime_data.appliance.entities[
                entity_description.brightness_entity
            ]
            self._entities.append(self._brightness_entity)

        if entity_description.color_temperature_entity is not None:
            self._color_temperature_entity = self._runtime_data.appliance.entities[
                entity_description.color_temperature_entity
            ]
            self._entities.append(self._color_temperature_entity)
            # Hood color temperature is the discrete ColorTemperature enum
            # (custom/warm/warmToNeutral/neutral/neutralToCold/cold, raw 0..5).
            # Map the kelvin slider to enum 1..5 (skipping custom). Warm = low
            # raw value but high kelvin — invert the axis.
            if self._color_temperature_entity.name == "Cooking.Hood.Setting.ColorTemperature":
                self._color_temp_enum_range = (1, 5)
                self._color_temp_inverted = True

        if entity_description.color_entity is not None:
            self._color_entity = self._runtime_data.appliance.entities[
                entity_description.color_entity
            ]
            self._entities.append(self._color_entity)

        if entity_description.color_mode_entity is not None:
            self._color_mode_entity = self._runtime_data.appliance.entities[
                entity_description.color_mode_entity
            ]
            self._entities.append(self._color_mode_entity)

        if self._color_entity:
            self._attr_supported_color_modes = {ColorMode.RGB}
            self._attr_color_mode = ColorMode.RGB
        elif self._color_temperature_entity and self._brightness_entity:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_max_color_temp_kelvin = DEFAULT_MAX_KELVIN
            self._attr_min_color_temp_kelvin = DEFAULT_MIN_KELVIN
        elif self._brightness_entity:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    @property
    def available(self) -> bool:
        # Don't gate the light on its entities' `available` flags. Bosch hoods
        # routinely flip both the primary `Cooking.Common.Setting.Lighting` and
        # the secondary brightness/color/color-temp entities to available=false
        # (e.g. when PowerState=Off, or for ColorTemperaturePercent as a static
        # DDF quirk). The user can still turn the light on; the appliance will
        # accept the write. We only gate on session connectivity; write failures
        # are handled in async_turn_on's retry path.
        return (
            self._runtime_data.coordinator.connected
            or self._runtime_data.appliance.session.connected
        )

    @property
    def is_on(self) -> bool | None:
        return bool(self._entity.value)

    @property
    def brightness(self) -> int | None:
        # Guard against backing entities reporting value=None (e.g. Bosch hood
        # entities flagged available=false): a crash here in state_attributes
        # rolls back optimistic state and reverts the light to off in the UI.
        if self._color_entity is not None and self._color_entity.value is not None:
            rgb = rgb_hex_to_rgb_list(self._color_entity.value.strip("#"))
            return max(rgb)
        if self._brightness_entity is not None and self._brightness_entity.value is not None:
            return value_to_brightness((1, 100), self._brightness_entity.value)
        return None

    @property
    def color_temp_kelvin(self) -> int | None:
        if self._color_temperature_entity is None:
            return None
        if self._color_temp_enum_range is not None:
            raw = self._color_temperature_entity.value_raw
            low, high = self._color_temp_enum_range
            if not isinstance(raw, int) or not (low <= raw <= high):
                # 0 (custom) or unset — no meaningful slider position.
                return None
            return scale_ranged_value_to_int_range(
                (high, low) if self._color_temp_inverted else (low, high),
                (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                raw,
            )
        value = self._color_temperature_entity.value
        if value is None:
            return None
        if self._color_temp_inverted:
            return scale_ranged_value_to_int_range(
                (101, 0),
                (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                value,
            )
        return scale_ranged_value_to_int_range(
            (1, 100),
            (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
            value,
        )

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        if self._color_entity is not None and self._color_entity.value is not None:
            rgb = rgb_hex_to_rgb_list(self._color_entity.value.strip("#"))
            return match_max_scale((255,), rgb)
        return None

    @error_decorator
    async def async_turn_on(self, **kwargs: Any) -> None:
        brightness = kwargs.get(ATTR_BRIGHTNESS, self.brightness)
        rgb = kwargs.get(ATTR_RGB_COLOR, self.rgb_color)

        data: list[dict] = []
        color_temp_payload: dict | None = None

        if self._attr_color_mode == ColorMode.RGB:
            rgb_with_brightness = tuple(color * brightness // 255 for color in rgb)
            data.append(
                {
                    "uid": self._color_entity.uid,
                    "value": "#" + color_rgb_to_hex(*rgb_with_brightness),
                }
            )
            if (
                self._color_mode_entity is not None
                and self._color_mode_entity.value != "CustomColor"
            ):
                color_mode_value = self._color_mode_entity._rev_enumeration["CustomColor"]  # noqa: SLF001
                data.append({"uid": self._color_mode_entity.uid, "value": color_mode_value})

        elif (
            self._attr_color_mode in (ColorMode.BRIGHTNESS, ColorMode.COLOR_TEMP)
            and ATTR_BRIGHTNESS in kwargs
        ):
            value_in_range = int(
                max(
                    brightness_to_value((1, 100), brightness),
                    self._brightness_entity.min,
                )
            )
            data.append({"uid": self._brightness_entity.uid, "value": value_in_range})

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            if self._color_temp_enum_range is not None:
                low, high = self._color_temp_enum_range
                target_range = (high, low) if self._color_temp_inverted else (low, high)
            else:
                target_range = (101, 0) if self._color_temp_inverted else (1, 100)
            value_in_range = int(
                scale_ranged_value_to_int_range(
                    (DEFAULT_MIN_KELVIN + 1, DEFAULT_MAX_KELVIN),
                    target_range,
                    kwargs[ATTR_COLOR_TEMP_KELVIN],
                )
            )
            color_temp_payload = {
                "uid": self._color_temperature_entity.uid,
                "value": value_in_range,
            }
            data.append(color_temp_payload)

        # Always include the on-write. On Bosch hoods the cached value of
        # Cooking.Common.Setting.Lighting can lag the physical state, so guarding
        # on `self._entity.value is not True` would suppress a legitimate turn-on.
        # Writing True when already on is a no-op on the appliance.
        data.append({"uid": self._entity.uid, "value": True})

        session = self._runtime_data.appliance.session
        try:
            await session.send_sync(
                HC_Message(resource="/ro/values", action=Action.POST, data=data)
            )
        except CodeResponsError:
            # If the color-temp write was the only thing rejected, retry without it
            # so on/off + brightness still take effect.
            if color_temp_payload is None:
                raise
            retry_data = [item for item in data if item is not color_temp_payload]
            if not retry_data:
                raise
            _LOGGER.debug("Light write rejected; retrying without color-temp payload")
            await session.send_sync(
                HC_Message(resource="/ro/values", action=Action.POST, data=retry_data)
            )

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._entity.set_value(False)
