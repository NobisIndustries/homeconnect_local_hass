"""Description for all supported Entities."""

from __future__ import annotations

from typing import TYPE_CHECKING

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
    """Create entity description from HomeConnect entity data."""
    # Generate a clean key from entity name  
    key = entity_name.lower().replace(".", "_")
    
    # Determine entity type based on name patterns and access
    access = getattr(entity, 'access', Access.READ)
    
    # Commands -> Buttons
    if ".Command." in entity_name:
        return ("button", HCButtonEntityDescription(
            key=key,
            entity=entity_name,
            name=entity_name.split(".")[-1],
            translation_key=key,
        ))
    
    # Programs -> Select (if writable) or Sensor (if read-only)  
    if ".Program." in entity_name:
        if access in (Access.READ_WRITE, Access.WRITE_ONLY):
            return ("select", HCSelectEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
        else:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
    
    # Status -> Sensors (read-only)
    if ".Status." in entity_name:
        # Check if it's a boolean-like status for binary sensor
        if hasattr(entity, 'value') and isinstance(entity.value, bool):
            return ("binary_sensor", HCBinarySensorEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
        else:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
    
    # Settings -> Switches/Selects/Numbers based on type and access
    if ".Setting." in entity_name:
        if access in (Access.READ_WRITE, Access.WRITE_ONLY):
            # Check if it has enumeration values (Select)
            if hasattr(entity, 'constraints') and hasattr(entity.constraints, 'allowedvalues'):
                return ("select", HCSelectEntityDescription(
                    key=key,
                    entity=entity_name,
                    name=entity_name.split(".")[-1],
                    translation_key=key,
                ))
            # Check if it's boolean (Switch)
            elif hasattr(entity, 'value') and isinstance(entity.value, bool):
                return ("switch", HCSwitchEntityDescription(
                    key=key,
                    entity=entity_name,
                    name=entity_name.split(".")[-1],
                    translation_key=key,
                ))
            # Check if it's numeric (Number)
            elif hasattr(entity, 'value') and isinstance(entity.value, (int, float)):
                return ("number", HCNumberEntityDescription(
                    key=key,
                    entity=entity_name,
                    name=entity_name.split(".")[-1],
                    translation_key=key,
                ))
            # Fallback to sensor for writable but unknown types
            else:
                return ("sensor", HCSensorEntityDescription(
                    key=key,
                    entity=entity_name,
                    name=entity_name.split(".")[-1],
                    translation_key=key,
                ))
        else:
            # Read-only settings -> Sensors
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
    
    # Options -> Numbers or Selects based on type
    if ".Option." in entity_name:
        if hasattr(entity, 'constraints') and hasattr(entity.constraints, 'allowedvalues'):
            return ("select", HCSelectEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
        elif hasattr(entity, 'value') and isinstance(entity.value, (int, float)):
            return ("number", HCNumberEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
        else:
            return ("sensor", HCSensorEntityDescription(
                key=key,
                entity=entity_name,
                name=entity_name.split(".")[-1],
                translation_key=key,
            ))
    
    # Events -> Event Sensors
    if ".Event." in entity_name:
        return ("event_sensor", HCSensorEntityDescription(
            key=key,
            entity=entity_name,
            name=entity_name.split(".")[-1],
            translation_key=key,
        ))
    
    # Default fallback -> Sensor
    return ("sensor", HCSensorEntityDescription(
        key=key,
        entity=entity_name,
        name=entity_name.split(".")[-1],
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
