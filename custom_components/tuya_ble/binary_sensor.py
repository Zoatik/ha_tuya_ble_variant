"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass

import logging
from typing import Callable

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.components.bluetooth.passive_update_coordinator import PassiveBluetoothDataUpdateCoordinator

from .const import (
    DOMAIN,
)
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo, TuyaBLEPassiveCoordinator
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice

_LOGGER = logging.getLogger(__name__)

SIGNAL_STRENGTH_DP_ID = -1


TuyaBLEBinarySensorIsAvailable = (
    Callable[["TuyaBLEBinarySensor", TuyaBLEProductInfo], bool] | None
)


@dataclass
class TuyaBLEBinarySensorMapping:
    dp_id: int
    description: BinarySensorEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    getter: Callable[[TuyaBLEBinarySensor], None] | None = None
    bit: int | None = None
    #coefficient: float = 1.0
    #icons: list[str] | None = None
    is_available: TuyaBLEBinarySensorIsAvailable = None


@dataclass
class TuyaBLECategoryBinarySensorMapping:
    products: dict[str, list[TuyaBLEBinarySensorMapping]] | None = None
    mapping: list[TuyaBLEBinarySensorMapping] | None = None


mapping: dict[str, TuyaBLECategoryBinarySensorMapping] = {
    "wk": TuyaBLECategoryBinarySensorMapping(
        products={
            "drlajpqc": [  # Thermostatic Radiator Valve
                TuyaBLEBinarySensorMapping(
                    dp_id=105,
                    description=BinarySensorEntityDescription(
                        key="battery",
                        #icon="mdi:battery-alert",
                        device_class=BinarySensorDeviceClass.BATTERY,
                        entity_category=EntityCategory.DIAGNOSTIC,
                    ),
                ),
            ],
        },
    ),
    "ms": TuyaBLECategoryBinarySensorMapping(
        products={},
    ),
    "sfkzq": TuyaBLECategoryBinarySensorMapping(
        products={
            "ldcdnigc": [
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="low_battery",
                        device_class=BinarySensorDeviceClass.BATTERY,
                    ),
                    bit=0,
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="fault",
                        device_class=BinarySensorDeviceClass.PROBLEM,
                    ),
                    bit=1,
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="lack_water",
                        icon="mdi:water-off",
                    ),
                    bit=2,
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="sensor_fault",
                        device_class=BinarySensorDeviceClass.PROBLEM,
                    ),
                    bit=3,
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="motor_fault",
                        device_class=BinarySensorDeviceClass.PROBLEM,
                    ),
                    bit=4,
                ),
                TuyaBLEBinarySensorMapping(
                    dp_id=4,
                    description=BinarySensorEntityDescription(
                        key="low_temp",
                        device_class=BinarySensorDeviceClass.COLD,
                    ),
                    bit=5,
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLEBinarySensorMapping]:
    category = mapping.get(device.category)
    result: list[TuyaBLEBinarySensorMapping] = []
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            result.extend(product_mapping)
    if category is not None and category.mapping is not None:
        result.extend(category.mapping)
    return result


class TuyaBLEBinarySensor(RestoreEntity, TuyaBLEEntity, BinarySensorEntity):
    """Representation of a Tuya BLE binary sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLEBinarySensorMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self._attr_is_on is not None:
            return
        last_state = await self.async_get_last_state()
        if last_state is not None:
            self._attr_is_on = last_state.state == "on"
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        if self._mapping.getter is not None:
            self._mapping.getter(self)
        else:
            datapoint = self._device.datapoints[self._mapping.dp_id]
            if datapoint is not None and getattr(datapoint, "value", None) is not None:
                if self._mapping.bit is not None:
                    # Mandatory for bitwise sensors (like ZX-7378 that has 6 bits in one datapoint)
                    self._attr_is_on = bool((datapoint.value >> self._mapping.bit) & 1)
                else:
                    self._attr_is_on = bool(datapoint.value)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE binary sensors."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLEBinarySensor] = []
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLEBinarySensor(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
