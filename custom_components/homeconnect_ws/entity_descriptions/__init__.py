"""Description for all supported Entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.sensor import SensorDeviceClass
from homeconnect_websocket.entities import Access

from .descriptions_definitions import (
    EntityDescriptions,
    HCBinarySensorEntityDescription,
    HCButtonEntityDescription,
    HCEntityDescription,
    HCFanEntityDescription,
    HCLightEntityDescription,
    HCNumberEntityDescription,
    HCSelectEntityDescription,
    HCSensorEntityDescription,
    HCSwitchEntityDescription,
    _EntityDescriptionsType,
)

if TYPE_CHECKING:
    from homeconnect_websocket import HomeAppliance


def _create_entity_description(entity_name: str, entity) -> tuple[str, HCEntityDescription] | None:
    """Create entity description from HomeConnect entity data based purely on entity properties."""
    # Generate a clean key from entity name  
    key = entity_name.lower().replace(".", "_")
    display_name = entity_name.split(".")[-1]
    
    # Get entity properties from the actual entity data
    access = getattr(entity, 'access', Access.READ)
    has_enum = getattr(entity, 'enum', None) is not None
    entity_value = getattr(entity, 'value', None)
    has_min_max = hasattr(entity, 'min') or hasattr(entity, 'max')
    
    # Determine entity type purely based on data characteristics
    
    # Write-only entities with no return value -> Buttons (Commands)
    if access == Access.WRITE_ONLY and not has_enum and not has_min_max:
        return ("button", HCButtonEntityDescription(
            key=key,
            entity=entity_name,
            name=display_name,
            translation_key=key,
        ))
    
    # Writable entities -> Interactive controls
    if access in (Access.READ_WRITE, Access.WRITE_ONLY):
        # Enum values -> Select
        if has_enum:
            return ("select", HCSelectEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Numeric with constraints -> Number
        elif has_min_max:
            return ("number", HCNumberEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Boolean values -> Switch  
        elif isinstance(entity_value, bool):
            return ("switch", HCSwitchEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Fallback writable -> Sensor (shouldn't happen often)
        else:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
    
    # Read-only entities -> Sensors or Binary Sensors
    else:
        # Boolean status -> Binary Sensor
        if isinstance(entity_value, bool):
            return ("binary_sensor", HCBinarySensorEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Enum values -> Enum Sensor
        elif has_enum:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
                device_class=SensorDeviceClass.ENUM,
            ))
        # Everything else -> Regular Sensor
        else:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))


def get_available_entities(appliance: HomeAppliance) -> EntityDescriptions:
    """Get all available Entity descriptions - auto-generated from profile."""
    available_entities: _EntityDescriptionsType = {
        "button": [],
        "active_program": [],
        "binary_sensor": [],
        "event_sensor": [],
        "number": [],
        "program": [],
        "select": [],
        "sensor": [],
        "start_button": [],
        "switch": [],
        "wifi": [],
        "light": [],
        "fan": [],
    }
    
    # Auto-generate entities from all available entities in the appliance
    for entity_name in appliance.entities:
        entity = appliance.entities[entity_name]
        entity_description = _create_entity_description(entity_name, entity)
        if entity_description:
            entity_type, description = entity_description
            available_entities[entity_type].append(description)
    
    return available_entities


__all__ = [
    "EntityDescriptions",
    "HCBinarySensorEntityDescription", 
    "HCButtonEntityDescription",
    "HCEntityDescription",
    "HCFanEntityDescription",
    "HCLightEntityDescription",
    "HCNumberEntityDescription",
    "HCSelectEntityDescription",
    "HCSensorEntityDescription",
    "HCSwitchEntityDescription",
    "_EntityDescriptionsType",
    "get_available_entities",
]
