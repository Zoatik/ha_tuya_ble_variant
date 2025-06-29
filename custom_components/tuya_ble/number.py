"""The Tuya BLE integration."""
from __future__ import annotations

from dataclasses import dataclass, field

import logging
from typing import Any, Callable

from homeassistant.components.number import (
    NumberEntityDescription,
    NumberMode,
)

from custom_components.tuya_ble.timer_utils import build_timer_raw, parse_timer_raw, set_timer_param, set_timer_day


from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    UnitOfTime,
    UnitOfVolume,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.components.bluetooth.passive_update_coordinator import PassiveBluetoothDataUpdateCoordinator
from .devices import TuyaBLEData, TuyaBLEEntity, TuyaBLEProductInfo, TuyaBLEPassiveCoordinator
from .const import DOMAIN
from .tuya_ble import TuyaBLEDataPointType, TuyaBLEDevice
from homeassistant.components.number.const import NumberDeviceClass

_LOGGER = logging.getLogger(__name__)

TuyaBLENumberGetter = (
    Callable[["TuyaBLENumber", TuyaBLEProductInfo], float | None] | None
)


TuyaBLENumberIsAvailable = (
    Callable[["TuyaBLENumber", TuyaBLEProductInfo], bool] | None
)


TuyaBLENumberSetter = (
    Callable[["TuyaBLENumber", TuyaBLEProductInfo, float], None] | None
)




@dataclass
class TuyaBLENumberMapping:
    dp_id: int
    description: NumberEntityDescription
    force_add: bool = True
    dp_type: TuyaBLEDataPointType | None = None
    coefficient: float = 1.0
    is_available: TuyaBLENumberIsAvailable = None
    getter: TuyaBLENumberGetter = None
    setter: TuyaBLENumberSetter = None
    mode: NumberMode = NumberMode.BOX


# -- 
def make_timer_param_getter(param: str):
    def getter(self, product):
        datapoint = self._device.datapoints[17]
        if datapoint and isinstance(datapoint.value, bytes):
            parsed = parse_timer_raw(datapoint.value)
            if parsed and param in parsed:
                return parsed[param]
        return None
    return getter

def make_timer_param_setter(param: str):
    def setter(self, product, value):
        set_timer_param(self, param, value)
    return setter

ldcdnigc_timer_numbers = [
    TuyaBLENumberMapping(
        dp_id=17,
        description=NumberEntityDescription(
            key="timer_hour",
            name="Timer Hour",
            icon="mdi:clock-outline",
            native_min_value=0,
            native_max_value=23,
            entity_category=EntityCategory.CONFIG,
        ),
        getter=make_timer_param_getter("hour"),
        setter=make_timer_param_setter("hour"),
        dp_type=TuyaBLEDataPointType.DT_RAW,
    ),
    TuyaBLENumberMapping(
        dp_id=17,
        description=NumberEntityDescription(
            key="timer_minute",
            name="Timer Minute",
            icon="mdi:clock-outline",
            native_min_value=0,
            native_max_value=59,
            entity_category=EntityCategory.CONFIG,
        ),
        getter=make_timer_param_getter("minute"),
        setter=make_timer_param_setter("minute"),
        dp_type=TuyaBLEDataPointType.DT_RAW,
    ),
    TuyaBLENumberMapping(
        dp_id=17,
        description=NumberEntityDescription(
            key="timer_duration",
            name="Timer Duration",
            icon="mdi:timer-outline",
            native_min_value=1,
            native_max_value=1439,
            entity_category=EntityCategory.CONFIG,
        ),
        getter=make_timer_param_getter("duration"),
        setter=make_timer_param_setter("duration"),
        dp_type=TuyaBLEDataPointType.DT_RAW,
    ),
]


def is_fingerbot_in_program_mode(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 2
    return result


def is_fingerbot_not_in_program_mode(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value != 2
    return result


def is_fingerbot_in_push_mode(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> bool:
    result: bool = True
    if product.fingerbot:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 0
    return result


def is_fingerbot_repeat_count_available(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> bool:
    result: bool = True
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.mode]
        if datapoint:
            result = datapoint.value == 2
        if result:
            datapoint = self._device.datapoints[product.fingerbot.program]
            if datapoint and type(datapoint.value) is bytes:
                repeat_count = int.from_bytes(datapoint.value[0:2], "big")
                result = repeat_count != 0xFFFF

    return result


def get_fingerbot_program_repeat_count(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> float | None:
    result: float | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            repeat_count = int.from_bytes(datapoint.value[0:2], "big")
            result = repeat_count * 1.0

    return result


def set_fingerbot_program_repeat_count(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
    value: float,
) -> None:
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            new_value = (
                int.to_bytes(int(value), 2, "big") +
                datapoint.value[2:]
            )
            self._hass.create_task(datapoint.set_value(new_value))


def get_fingerbot_program_position(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
) -> float | None:
    result: float | None = None
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            result = datapoint.value[2] * 1.0

    return result


def set_fingerbot_program_position(
    self: TuyaBLENumber,
    product: TuyaBLEProductInfo,
    value: float,
) -> None:
    if product.fingerbot and product.fingerbot.program:
        datapoint = self._device.datapoints[product.fingerbot.program]
        if datapoint and type(datapoint.value) is bytes:
            new_value = bytearray(datapoint.value)
            new_value[2] = int(value)
            self._hass.create_task(datapoint.set_value(new_value))


@dataclass
class TuyaBLEDownPositionDescription(NumberEntityDescription):
    key: str = "down_position"
    icon: str = "mdi:arrow-down-bold"
    native_max_value: float = 100
    native_min_value: float = 51
    native_unit_of_measurement: str = PERCENTAGE
    native_step: float = 1
    entity_category: EntityCategory = EntityCategory.CONFIG


@dataclass
class TuyaBLEUpPositionDescription(NumberEntityDescription):
    key: str = "up_position"
    icon: str = "mdi:arrow-up-bold"
    native_max_value: float = 50
    native_min_value: float = 0
    native_unit_of_measurement: str = PERCENTAGE
    native_step: float = 1
    entity_category: EntityCategory = EntityCategory.CONFIG


@dataclass
class TuyaBLEHoldTimeDescription(NumberEntityDescription):
    key: str = "hold_time"
    icon: str = "mdi:timer"
    native_max_value: float = 10
    native_min_value: float = 0
    native_unit_of_measurement: str = UnitOfTime.SECONDS
    native_step: float = 1
    entity_category: EntityCategory = EntityCategory.CONFIG


@dataclass
class TuyaBLEHoldTimeMapping(TuyaBLENumberMapping):
    description: NumberEntityDescription = field(
        default_factory=lambda: TuyaBLEHoldTimeDescription()
    )
    is_available: TuyaBLENumberIsAvailable = is_fingerbot_in_push_mode


@dataclass
class TuyaBLECategoryNumberMapping:
    products: dict[str, list[TuyaBLENumberMapping]] | None = None
    mapping: list[TuyaBLENumberMapping] | None = None


mapping: dict[str, TuyaBLECategoryNumberMapping] = {
    "sfkzq": TuyaBLECategoryNumberMapping( # Smart valve
        products={
            "ldcdnigc": [   # ZX-7378 Smart Irrigation Controller
                TuyaBLENumberMapping(
                    dp_id=11,
                    description=NumberEntityDescription(
                        key="countdown",
                        name="Countdown",
                        icon="mdi:timer",
                        native_max_value=86400,
                        native_min_value=0,
                        native_unit_of_measurement="s",
                        native_step=1,
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
                *ldcdnigc_timer_numbers,
            ],
        },
    ),
    "co2bj": TuyaBLECategoryNumberMapping(
        products={
            "59s19z5m": [  # CO2 Detector
                TuyaBLENumberMapping(
                    dp_id=17,
                    description=NumberEntityDescription(
                        key="brightness",
                        icon="mdi:brightness-percent",
                        native_max_value=100,
                        native_min_value=0,
                        native_unit_of_measurement=PERCENTAGE,
                        native_step=1,
                        entity_category=EntityCategory.CONFIG,
                    ),
                    mode=NumberMode.SLIDER,
                ),
                TuyaBLENumberMapping(
                    dp_id=26,
                    description=NumberEntityDescription(
                        key="carbon_dioxide_alarm_level",
                        icon="mdi:molecule-co2",
                        native_max_value=5000,
                        native_min_value=400,
                        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
                        native_step=100,
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "szjqr": TuyaBLECategoryNumberMapping(
        products={
            **dict.fromkeys(
                ["3yqdo5yt", "xhf790if"],  # CubeTouch 1s and II
                [
                    TuyaBLEHoldTimeMapping(dp_id=3),
                    TuyaBLENumberMapping(
                        dp_id=5,
                        description=TuyaBLEUpPositionDescription(
                            native_max_value=100,
                        ),
                    ),
                    TuyaBLENumberMapping(
                        dp_id=6,
                        description=TuyaBLEDownPositionDescription(
                            native_min_value=0,
                        ),
                    ),
                ],
            ),
            **dict.fromkeys(
                [
                    "blliqpsj",
                    "ndvkgsrm",
                    "yiihr7zh",
                    "neq16kgd"
                ],  # Fingerbot Plus
                [
                    TuyaBLENumberMapping(
                        dp_id=9,
                        description=TuyaBLEDownPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                    TuyaBLEHoldTimeMapping(dp_id=10),
                    TuyaBLENumberMapping(
                        dp_id=15,
                        description=TuyaBLEUpPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=121,
                        description=NumberEntityDescription(
                            key="program_repeats_count",
                            icon="mdi:repeat",
                            native_max_value=0xFFFE,
                            native_min_value=1,
                            native_step=1,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_repeat_count_available,
                        getter=get_fingerbot_program_repeat_count,
                        setter=set_fingerbot_program_repeat_count,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=121,
                        description=NumberEntityDescription(
                            key="program_idle_position",
                            icon="mdi:repeat",
                            native_max_value=100,
                            native_min_value=0,
                            native_step=1,
                            native_unit_of_measurement=PERCENTAGE,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_in_program_mode,
                        getter=get_fingerbot_program_position,
                        setter=set_fingerbot_program_position,
                    ),
                ],
            ),
            **dict.fromkeys(
                [
                    "ltak7e1p",
                    "y6kttvd6",
                    "yrnk7mnn",
                    "nvr2rocq",
                    "bnt7wajf",
                    "rvdceqjh",
                    "5xhbk964",
                ],  # Fingerbot
                [
                    TuyaBLENumberMapping(
                        dp_id=9,
                        description=TuyaBLEDownPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=10,
                        description=TuyaBLEHoldTimeDescription(
                            native_step=0.1,
                        ),
                        coefficient=10.0,
                        is_available=is_fingerbot_in_push_mode,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=15,
                        description=TuyaBLEUpPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                ],
            ),
        },
    ),
    "kg": TuyaBLECategoryNumberMapping(
        products={
            **dict.fromkeys(
                [
                    "mknd4lci",
                    "riecov42"
                ],  # Fingerbot Plus
                [
                    TuyaBLENumberMapping(
                        dp_id=102,
                        description=TuyaBLEDownPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                    TuyaBLEHoldTimeMapping(dp_id=103),
                    TuyaBLENumberMapping(
                        dp_id=106,
                        description=TuyaBLEUpPositionDescription(),
                        is_available=is_fingerbot_not_in_program_mode,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=109,
                        description=NumberEntityDescription(
                            key="program_repeats_count",
                            icon="mdi:repeat",
                            native_max_value=0xFFFE,
                            native_min_value=1,
                            native_step=1,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_repeat_count_available,
                        getter=get_fingerbot_program_repeat_count,
                        setter=set_fingerbot_program_repeat_count,
                    ),
                    TuyaBLENumberMapping(
                        dp_id=109,
                        description=NumberEntityDescription(
                            key="program_idle_position",
                            icon="mdi:repeat",
                            native_max_value=100,
                            native_min_value=0,
                            native_step=1,
                            native_unit_of_measurement=PERCENTAGE,
                            entity_category=EntityCategory.CONFIG,
                        ),
                        is_available=is_fingerbot_in_program_mode,
                        getter=get_fingerbot_program_position,
                        setter=set_fingerbot_program_position,
                    ),
                ],
            ),
        },
    ),
    "wk": TuyaBLECategoryNumberMapping(
        products={
            **dict.fromkeys(
                [
                    "drlajpqc",
                    "nhj2j7su",
                    "zmachryv",
                ],  # Thermostatic Radiator Valve
                [
                    TuyaBLENumberMapping(
                        dp_id=27,
                        description=NumberEntityDescription(
                            key="temperature_calibration",
                            icon="mdi:thermometer-lines",
                            native_max_value=6,
                            native_min_value=-6,
                            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
                            native_step=1,
                            entity_category=EntityCategory.CONFIG,
                        ),
                    ),
                ],
            ),
        },
    ),
    "wsdcg": TuyaBLECategoryNumberMapping(
        products={
            "ojzlzzsw": [  # Soil moisture sensor
                TuyaBLENumberMapping(
                    dp_id=17,
                    description=NumberEntityDescription(
                        key="reporting_period",
                        icon="mdi:timer",
                        native_max_value=120,
                        native_min_value=1,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        native_step=1,
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "znhsb": TuyaBLECategoryNumberMapping(
        products={
            "cdlandip":  # Smart water bottle
            [
                TuyaBLENumberMapping(
                    dp_id=103,
                    description=NumberEntityDescription(
                        key="recommended_water_intake",
                        device_class=NumberDeviceClass.WATER,
                        native_max_value=5000,
                        native_min_value=0,
                        native_unit_of_measurement=UnitOfVolume.MILLILITERS,
                        native_step=1,
                        entity_category=EntityCategory.CONFIG,
                    ),
                ),
            ],
        },
    ),
    "ggq": TuyaBLECategoryNumberMapping(
        products={
            "6pahkcau": [  # Irrigation computer PARKSIDE PPB A1
                TuyaBLENumberMapping(
                    dp_id=5,
                    description=NumberEntityDescription(
                        key="countdown_duration",
                        icon="mdi:timer",
                        native_max_value=1440,
                        native_min_value=1,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        native_step=1,
                    ),
                ),
            ],
            "hfgdqhho": [  # Irrigation computer SGW08
                TuyaBLENumberMapping(
                    dp_id=106,
                    description=NumberEntityDescription(
                        key="countdown_duration_1",
                        name="CH1 Countdown",
                        icon="mdi:timer",
                        native_max_value=1440,
                        native_min_value=1,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        native_step=1,
                    ),
                ),
                TuyaBLENumberMapping(
                    dp_id=103,
                    description=NumberEntityDescription(
                        key="countdown_duration_2",
                        name="CH2 Countdown",
                        icon="mdi:timer",
                        native_max_value=1440,
                        native_min_value=1,
                        native_unit_of_measurement=UnitOfTime.MINUTES,
                        native_step=1,
                    ),
                ),
            ],
        },
    ),
}


def get_mapping_by_device(device: TuyaBLEDevice) -> list[TuyaBLENumberMapping]:
    category = mapping.get(device.category)
    result: list[TuyaBLENumberMapping] = []
    if category is not None and category.products is not None:
        product_mapping = category.products.get(device.product_id)
        if product_mapping is not None:
            result.extend(product_mapping)
    if category is not None and category.mapping is not None:
        result.extend(category.mapping)
    return result


class TuyaBLENumber(TuyaBLEEntity, NumberEntity):
    """Representation of a Tuya BLE Number."""

    _attr_entity_category = None
    _attr_native_min_value = None
    _attr_native_max_value = None
    _attr_native_step = None
    _attr_native_unit_of_measurement = None
    _attr_mode = None

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: TuyaBLEPassiveCoordinator,
        device: TuyaBLEDevice,
        product: TuyaBLEProductInfo,
        mapping: TuyaBLENumberMapping,
    ) -> None:
        super().__init__(hass, coordinator, device, product, mapping.description)
        self._mapping = mapping
        self._attr_mode = mapping.mode
        self._attr_native_min_value = mapping.description.native_min_value
        self._attr_native_max_value = mapping.description.native_max_value
        self._attr_native_step = mapping.description.native_step
        self._attr_native_unit_of_measurement = mapping.description.native_unit_of_measurement
        self._attr_entity_category = mapping.description.entity_category

    @property
    def min_value(self) -> float:
        return self._attr_native_min_value if self._attr_native_min_value is not None else 0.0

    @property
    def max_value(self) -> float:
        return self._attr_native_max_value if self._attr_native_max_value is not None else 0.0
    
    @property
    def native_value(self) -> float | None:
        if self._mapping.getter is not None:
            return self._mapping.getter(self, self._product)
        datapoint = self._device.datapoints[self._mapping.dp_id]
        if datapoint and isinstance(datapoint.value, (int, float)):
            return datapoint.value / self._mapping.coefficient
        return self._mapping.description.native_min_value

    async def async_set_native_value(self, value: float) -> None:
        if self._mapping.setter is not None:
            self._mapping.setter(self, self._product, value)
            return
        int_value = int(value * self._mapping.coefficient)
        datapoint = self._device.datapoints.get_or_create(
            self._mapping.dp_id,
            TuyaBLEDataPointType.DT_VALUE,
            int(int_value),
        )
        if datapoint:
            await datapoint.set_value(int_value)



async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Tuya BLE numbers."""
    data: TuyaBLEData = hass.data[DOMAIN][entry.entry_id]
    mappings = get_mapping_by_device(data.device)
    entities: list[TuyaBLENumber] = []
    for mapping in mappings:
        if mapping.force_add or data.device.datapoints.has_id(
            mapping.dp_id, mapping.dp_type
        ):
            entities.append(
                TuyaBLENumber(
                    hass,
                    data.coordinator,
                    data.device,
                    data.product,
                    mapping,
                )
            )
    async_add_entities(entities)
