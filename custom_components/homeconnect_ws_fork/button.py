"""Button entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity
from homeconnect_websocket.entities import Execution

from .entity import HCEntity
from .helpers import create_entities, error_decorator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback
    from homeconnect_websocket.entities import ActiveProgram, Command, Program

    from . import HCConfigEntry
    from .entity_descriptions.descriptions_definitions import HCButtonEntityDescription

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    config_entry: HCConfigEntry,
    async_add_entites: AddEntitiesCallback,
) -> None:
    """Set up button platform."""
    entities = create_entities(
        {"button": HCButton, "start_button": HCStartButton}, config_entry.runtime_data
    )
    async_add_entites(entities)


class HCButton(HCEntity, ButtonEntity):
    """Command / Program-start Button Entity.

    If the entity description carries a ``program`` field, pressing starts that program
    with ``program_options`` (no shadow-value pollution). Otherwise it writes ``True``
    to the underlying Command entity.
    """

    entity_description: HCButtonEntityDescription
    _entity: Command | Program

    @error_decorator
    async def async_press(self) -> None:
        program_name = self.entity_description.program
        if program_name is not None:
            program: Program = self._runtime_data.appliance.programs[program_name]
            options = self.entity_description.program_options or {}
            await program.start(options=options, override_options=True)
            return
        await self._entity.set_value(True)


class HCStartButton(HCEntity, ButtonEntity):
    """Start Button Entity."""

    _entity: ActiveProgram
    entity_description: HCButtonEntityDescription

    @property
    def available(self) -> bool:
        available = super().available
        available &= self._runtime_data.appliance.selected_program is not None
        if self._runtime_data.appliance.selected_program is not None:
            available &= (
                self._runtime_data.appliance.selected_program.execution
                == Execution.SELECT_AND_START
            )
        return available

    @error_decorator
    async def async_press(self) -> None:
        await self._runtime_data.appliance.selected_program.start()
