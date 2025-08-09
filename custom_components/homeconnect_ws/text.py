"""Text entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.text import TextEntity

from .entity import HCEntity
from .helpers import create_entities

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.device_registry import DeviceInfo
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket import HomeAppliance

    from . import HCConfigEntry
    from .entity_descriptions.descriptions_definitions import HCTextEntityDescription

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up text platform."""
    entities = create_entities({"text": HCText}, config_entry.runtime_data)
    async_add_entities(entities)


class HCText(HCEntity, TextEntity):
    """Text Entity."""

    entity_description: HCTextEntityDescription

    def __init__(
        self,
        entity_description: HCTextEntityDescription,
        appliance: HomeAppliance,
        device_info: DeviceInfo,
    ) -> None:
        super().__init__(entity_description, appliance, device_info)
        # Set text entity properties
        self._attr_native_max = 255  # Default max length for hex colors
        self._attr_pattern = r"^#?[0-9A-Fa-f]{6}$"  # Hex color pattern

    @property
    def native_value(self) -> str | None:
        """Return current value."""
        value = self._entity.value
        if value is None:
            return None
        return str(value)

    async def async_set_native_value(self, value: str) -> None:
        """Set new text value."""
        await self._entity.set_value(value)