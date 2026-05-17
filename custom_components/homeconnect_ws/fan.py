"""Fan entities."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, NamedTuple

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.percentage import percentage_to_ranged_value, ranged_value_to_percentage
from homeconnect_websocket.message import Action, Message

from .const import DOMAIN
from .entity import HCEntity
from .helpers import create_entities, error_decorator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import Entity as HcEntity

    from . import HCConfigEntry, HCData
    from .entity_descriptions.descriptions_definitions import HCFanEntityDescription

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0

PRESET_AUTO = "auto"


class SpeedMapping(NamedTuple):
    """Mapping of entity name / value and speed."""

    entity_name: str
    entity_value: int
    speed: int


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up fan platform."""
    runtime_data = config_entry.runtime_data
    fan_descriptions = runtime_data.available_entity_descriptions.get("fan", [])

    entities: set[HCEntity] = set()
    for description in fan_descriptions:
        cls = HCHoodFan if description.venting_program else HCFan
        _LOGGER.debug("Creating Entity %s (%s)", description.key, cls.__name__)
        try:
            entities.add(cls(entity_description=description, runtime_data=runtime_data))
        except Exception:
            _LOGGER.exception("Failed to create Entity %s", description.key)
    async_add_entites(entities)


class HCFan(HCEntity, FanEntity):
    """Fan Entity (writes option values directly)."""

    entity_description: HCFanEntityDescription
    _speed_entities: dict[str, HcEntity] | None = None
    _speed_range: range = None
    _speed_mapping: list[SpeedMapping]

    def __init__(
        self,
        entity_description: HCFanEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        self._attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_OFF
        self._speed_mapping = []
        self._speed_entities = {}
        self._attr_speed_count = 0
        for entity_name in entity_description.entities:
            entity = self._runtime_data.appliance.entities[entity_name]
            self._speed_entities[entity_name] = entity
            for option in entity.enum:
                if option != 0:
                    self._attr_speed_count += 1
                    self._speed_mapping.append(
                        SpeedMapping(
                            entity_name=entity_name,
                            entity_value=option,
                            speed=self._attr_speed_count,
                        )
                    )

        self._speed_range = (1, self._attr_speed_count)

    @property
    def percentage(self) -> int | None:
        for speed in self._speed_mapping:
            if self._speed_entities[speed.entity_name].value_raw == speed.entity_value:
                return ranged_value_to_percentage(self._speed_range, speed.speed)
        return 0

    @error_decorator
    async def async_set_percentage(self, percentage: int) -> None:
        new_speed = math.ceil(percentage_to_ranged_value(self._speed_range, percentage))
        new_speed_entity: str = None
        new_speed_value: int = None
        for speed in self._speed_mapping:
            if speed.speed == new_speed:
                new_speed_entity = speed.entity_name
                new_speed_value = speed.entity_value
        if new_speed_entity or new_speed == 0:
            data = []
            for entity in self._speed_entities.values():
                if entity.name == new_speed_entity:
                    data.append({"uid": entity.uid, "value": new_speed_value})
                else:
                    data.append({"uid": entity.uid, "value": 0})
            message = Message(
                resource="/ro/values",
                action=Action.POST,
                data=data,
            )
            await self._runtime_data.appliance.session.send_sync(message)
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="speed_invalid",
                translation_placeholders={"percentage", percentage},
            )

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:
        data = [{"uid": entity.uid, "value": 0} for entity in self._speed_entities.values()]
        message = Message(
            resource="/ro/values",
            action=Action.POST,
            data=data,
        )
        await self._runtime_data.appliance.session.send_sync(message)


class HCHoodFan(HCEntity, FanEntity):
    """Hood Fan Entity — drives venting by starting the Hood.Venting program.

    Setting just the option values is a no-op on Bosch hoods; the venting program must
    be started with the chosen VentingLevel/IntensiveLevel as an option. Reading state
    happens through the active program's option entities.
    """

    entity_description: HCFanEntityDescription
    _speed_entities: dict[str, HcEntity]
    _speed_mapping: list[SpeedMapping]

    def __init__(
        self,
        entity_description: HCFanEntityDescription,
        runtime_data: HCData,
    ) -> None:
        super().__init__(entity_description, runtime_data)
        self._attr_supported_features = (
            FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_OFF | FanEntityFeature.TURN_ON
        )
        if entity_description.auto_program:
            self._attr_supported_features |= FanEntityFeature.PRESET_MODE
            self._attr_preset_modes = [PRESET_AUTO]

        self._speed_mapping = []
        self._speed_entities = {}
        self._attr_speed_count = 0
        for entity_name in entity_description.entities:
            entity = self._runtime_data.appliance.entities[entity_name]
            self._speed_entities[entity_name] = entity
            self._entities.append(entity)
            for option in sorted(k for k in entity.enum if k != 0):
                self._attr_speed_count += 1
                self._speed_mapping.append(
                    SpeedMapping(
                        entity_name=entity_name,
                        entity_value=option,
                        speed=self._attr_speed_count,
                    )
                )
        self._speed_range = (1, self._attr_speed_count)

        active_program_entity = runtime_data.appliance.entities.get(
            "BSH.Common.Root.ActiveProgram"
        )
        if active_program_entity is not None and active_program_entity not in self._entities:
            self._entities.append(active_program_entity)

    @property
    def _active_program_name(self) -> str | None:
        program = self._runtime_data.appliance.active_program
        return program.name if program is not None else None

    @property
    def is_on(self) -> bool | None:
        active = self._active_program_name
        if active == self.entity_description.auto_program:
            return True
        if active == self.entity_description.venting_program:
            # On if any speed entity reports a non-zero value
            return any(entity.value_raw for entity in self._speed_entities.values())
        return False

    @property
    def preset_mode(self) -> str | None:
        if self._active_program_name == self.entity_description.auto_program:
            return PRESET_AUTO
        return None

    @property
    def percentage(self) -> int | None:
        active = self._active_program_name
        if active == self.entity_description.auto_program:
            return None
        if active != self.entity_description.venting_program:
            return 0
        for speed in self._speed_mapping:
            if self._speed_entities[speed.entity_name].value_raw == speed.entity_value:
                return ranged_value_to_percentage(self._speed_range, speed.speed)
        return 0

    async def _start_venting(self, speed: int) -> None:
        """Start the Venting program with the given internal speed (0 = off)."""
        venting_name = self.entity_description.venting_program
        program = self._runtime_data.appliance.programs[venting_name]
        # Build options explicitly: every speed entity gets 0 except the chosen one.
        options: dict[int, int] = {}
        chosen: SpeedMapping | None = None
        if speed > 0:
            for mapping in self._speed_mapping:
                if mapping.speed == speed:
                    chosen = mapping
                    break
            if chosen is None:
                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="speed_invalid",
                    translation_placeholders={"percentage": str(speed)},
                )
        for entity_name, entity in self._speed_entities.items():
            options[entity.uid] = (
                chosen.entity_value if chosen and chosen.entity_name == entity_name else 0
            )
        await program.start(options=options, override_options=True)

    @error_decorator
    async def async_set_percentage(self, percentage: int) -> None:
        if percentage == 0:
            await self._start_venting(0)
            return
        new_speed = math.ceil(percentage_to_ranged_value(self._speed_range, percentage))
        await self._start_venting(new_speed)

    @error_decorator
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode != PRESET_AUTO or not self.entity_description.auto_program:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="speed_invalid",
                translation_placeholders={"percentage": preset_mode},
            )
        program = self._runtime_data.appliance.programs[self.entity_description.auto_program]
        await program.start(options={}, override_options=True)

    @error_decorator
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,  # noqa: ARG002
    ) -> None:
        if preset_mode:
            await self.async_set_preset_mode(preset_mode)
            return
        if percentage is None or percentage == 0:
            # Default to slowest speed on a bare turn-on.
            percentage = ranged_value_to_percentage(self._speed_range, 1)
        await self.async_set_percentage(percentage)

    @error_decorator
    async def async_turn_off(self, **kwargs: Any) -> None:  # noqa: ARG002
        await self._start_venting(0)
