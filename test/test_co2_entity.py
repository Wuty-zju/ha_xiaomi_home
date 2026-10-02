# -*- coding: utf-8 -*-
"""CO2 regressions with the installed Home Assistant entity implementation.

These run in a disposable Home Assistant image. The ordinary core-only test
job can skip them explicitly when Home Assistant is not installed.
"""
import asyncio
from datetime import timedelta
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
import pytest_asyncio
from test_spec_co2 import CO2_URN, NEW3PR_URN, co2_property
from test_spec_co2 import co2_parser_fixture  # pylint: disable=unused-import

# pylint: disable=import-outside-toplevel, protected-access, unused-import

pytest.importorskip('homeassistant')
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest_asyncio.fixture(name='co2_entity')
async def co2_entity_fixture(co2_parser, tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent))
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry, ConfigEntries
    from homeassistant.helpers.entity_platform import EntityPlatform
    from custom_components.xiaomi_home import sensor
    from custom_components.xiaomi_home.miot.miot_device import MIoTDevice
    from custom_components.xiaomi_home.miot.miot_spec import MIoTSpecInstance

    instance = MIoTSpecInstance.load((await co2_parser.parse(CO2_URN)).dump())
    callbacks = {}
    client = SimpleNamespace(
        main_loop=asyncio.get_running_loop(), area_name_rule='none',
        cloud_server='cn', display_binary_text=False,
        sub_device_state=Mock(), request_refresh_prop=Mock(),
        get_prop_async=AsyncMock(return_value=1217))

    def subscribe(did, handler, siid, piid):
        callbacks[(did, siid, piid)] = handler

    def unsubscribe(did, siid, piid):
        callbacks.pop((did, siid, piid), None)

    client.sub_prop = subscribe
    client.unsub_prop = unsubscribe
    device = MIoTDevice(client, {
        'did': 'blt.synthetic', 'name': 'Synthetic CO2', 'online': True,
        'model': 'miaomiaoce.airm.co2'}, instance)
    device.spec_transform()
    entity = sensor.Sensor(device, co2_property(instance))
    hass = HomeAssistant(str(tmp_path))
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(
        version=1, minor_version=1, domain='xiaomi_home', title='Synthetic',
        data={}, options={}, source='user', unique_id='synthetic',
        discovery_keys={}, subentries_data=[])
    # Register the real entry without starting OAuth or discovery.
    hass.config_entries._entries[entry.entry_id] = entry
    from homeassistant.helpers import entity_registry, device_registry
    device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    hass.config.components.add('sensor')
    platform = EntityPlatform(
        hass=hass, logger=logging.getLogger(__name__), domain='sensor',
        platform_name='xiaomi_home', platform=sensor,
        scan_interval=timedelta(seconds=30), entity_namespace=None)
    platform.config_entry = entry
    await platform.async_add_entities([entity])
    yield SimpleNamespace(entity=entity, device=device, client=client,
                          callbacks=callbacks, hass=hass, platform=platform,
                          sensor=sensor, instance=instance)
    await platform.async_reset()
    await hass.async_block_till_done()
    await hass.async_stop(force=True)


def emit(context, value):
    context.callbacks[('blt.synthetic', 3, 1029)](
        {'did': 'blt.synthetic', 'siid': 3, 'piid': 1029, 'value': value}, None)


async def test_precision_identity_and_ha_state(co2_entity):
    from homeassistant.components.sensor import SensorDeviceClass
    from homeassistant.components.sensor import SensorStateClass

    context = co2_entity
    entity = context.entity
    assert entity.native_value is None
    assert entity.device_class == SensorDeviceClass.CO2
    assert entity.native_unit_of_measurement == 'ppm'
    assert entity.state_class == SensorStateClass.MEASUREMENT
    identity = (entity.unique_id, entity.entity_id, entity.device_info)
    for value in [1217, 1193, 400, 5000]:
        emit(context, value)
        assert entity.native_value == value
    # The original step changes readings, but never property/device identity.
    co2_property(context.instance).value_range = [400, 5000, 100]
    old_entity = context.sensor.Sensor(context.device,
                                       co2_property(context.instance))
    assert (old_entity.unique_id, old_entity.entity_id,
            old_entity.device_info) == identity
    assert await entity.get_property_async() == 1200
    co2_property(context.instance).value_range = [400, 5000, 1]
    assert await entity.get_property_async() == 1217
    entity._pending_write_ha_state_timer.cancel()
    entity._pending_write_ha_state_timer = None
    entity.async_write_ha_state()
    assert context.hass.states.get(entity.entity_id).state == '5000'


@pytest.mark.parametrize('value', [None, True, False, '1217', '1217.6',
                                   1217.6, float('nan'), float('inf'),
                                   -float('inf'), 399, 5001, {}, []])
async def test_invalid_inputs_do_not_become_measurements(co2_entity, value):
    context = co2_entity
    emit(context, 1217)
    emit(context, value)
    assert context.entity.native_value == 1217
    context.client.get_prop_async.return_value = value
    assert await context.entity.get_property_async() is None


async def test_platform_unload_reload_and_user_rename(co2_entity):
    from homeassistant.helpers import entity_registry

    context = co2_entity
    registry = entity_registry.async_get(context.hass)
    entity = context.entity
    renamed_id = 'sensor.synthetic_user_co2'
    registry.async_update_entity(entity.entity_id, new_entity_id=renamed_id,
                                 name='User CO2 name')
    await context.hass.async_block_till_done()
    assert entity.entity_id == renamed_id
    refresh_count = context.client.request_refresh_prop.call_count
    late_handler = context.callbacks[('blt.synthetic', 3, 1029)]
    pending_timer = entity._pending_write_ha_state_timer
    await context.platform.async_reset()
    assert pending_timer.cancelled()
    assert not context.callbacks
    assert not context.device._value_sub_list
    assert not context.device._device_state_sub_list
    # A callback already queued before unsubscribe must be harmless.
    late_handler({'value': 1193}, None)
    replacement = context.sensor.Sensor(context.device,
                                        co2_property(context.instance))
    await context.platform.async_add_entities([replacement])
    assert replacement.entity_id == renamed_id
    assert registry.async_get(renamed_id).name == 'User CO2 name'
    assert len(context.callbacks) == 1
    late_handler({'value': 400}, None)
    assert replacement.native_value is None
    emit(context, 1193)
    assert replacement.native_value == 1193
    assert context.client.request_refresh_prop.call_count == refresh_count + 1


async def test_other_property_input_behavior_is_unchanged(co2_entity):
    context = co2_entity
    context.instance.urn = NEW3PR_URN
    context.client.get_prop_async.return_value = '1217'
    assert await context.entity.get_property_async() == 1217
    context.instance.urn = CO2_URN + ':0000D001'
    co2_property(context.instance).value_range = [400, 5000, 100]
    context.client.get_prop_async.return_value = 1217
    assert await context.entity.get_property_async() == 1200
