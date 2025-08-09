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
    HCTextEntityDescription,
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
    enum_values = getattr(entity, 'enum', {}) if has_enum else {}
    
    # Helper function to detect if enum represents a binary on/off state
    def _is_binary_enum(enum_dict: dict) -> bool:
        if len(enum_dict) != 2:
            return False
        values = list(enum_dict.values())
        # Check for common binary patterns
        binary_patterns = [
            {'Off', 'On'},
            {'False', 'True'}, 
            {'Inactive', 'Active'},
            {'Disabled', 'Enabled'},
        ]
        value_set = set(values)
        return any(value_set == pattern for pattern in binary_patterns)
    
    # Helper function to detect boolean entities based on schema data types
    def _is_boolean_entity(entity_obj) -> bool:
        # Check if entity has boolean data type from schema (refCID=01, refDID=00)
        if hasattr(entity_obj, '_uid'):  # Full entity object
            # Try to access the original description data if available
            if hasattr(entity_obj, '_appliance') and hasattr(entity_obj._appliance, 'description'):
                # Look up entity in device description by UID
                desc = entity_obj._appliance.description
                for section in ['status', 'setting', 'command', 'option']:
                    if section in desc:
                        for item in desc[section]:
                            if item.get('uid') == entity_obj._uid:
                                return (item.get('refCID') == 1 and item.get('refDID') == 0)
        
        # Fallback: check if current value is boolean
        return isinstance(entity_value, bool)
    
    # Helper function to detect color entities based on schema data types
    def _is_color_entity(entity_obj) -> bool:
        # Check if entity has color data type from schema (refCID=1E, refDID=AB)
        if hasattr(entity_obj, '_uid'):  # Full entity object
            # Try to access the original description data if available
            if hasattr(entity_obj, '_appliance') and hasattr(entity_obj._appliance, 'description'):
                # Look up entity in device description by UID  
                desc = entity_obj._appliance.description
                for section in ['status', 'setting', 'command', 'option']:
                    if section in desc:
                        for item in desc[section]:
                            if item.get('uid') == entity_obj._uid:
                                return (item.get('refCID') == 30 and item.get('refDID') == 171)  # 0x1E=30, 0xAB=171
        return False
    
    # Determine entity type based on data characteristics
    
    # Write-only entities -> Buttons (Commands)
    if access == Access.WRITE_ONLY:
        return ("button", HCButtonEntityDescription(
            key=key,
            entity=entity_name,
            name=display_name,
            translation_key=key,
        ))
    
    # Writable entities -> Interactive controls
    if access in (Access.READ_WRITE, Access.WRITE_ONLY):
        # True boolean entities (refCID=01, refDID=00) -> Switch
        if _is_boolean_entity(entity):
            return ("switch", HCSwitchEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Color entities (refCID=1E, refDID=AB) -> Text input for hex colors
        elif _is_color_entity(entity):
            return ("text", HCTextEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Any enum (including binary enums like On/Off) -> Select
        # This ensures enum values (like 1,2 for Off/On) are sent correctly
        elif has_enum:
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
        # Fallback writable -> Switch (assume boolean if no other info)
        else:
            return ("switch", HCSwitchEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
    
    # Read-only entities -> Sensors or Binary Sensors
    else:
        # Binary enum status -> Binary Sensor  
        if has_enum and _is_binary_enum(enum_values):
            return ("binary_sensor", HCBinarySensorEntityDescription(
                key=key,
                entity=entity_name,
                name=display_name,
                translation_key=key,
            ))
        # Boolean status -> Binary Sensor
        elif _is_boolean_entity(entity):
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
        "text": [],
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
    "HCTextEntityDescription",
    "_EntityDescriptionsType",
    "get_available_entities",
]
