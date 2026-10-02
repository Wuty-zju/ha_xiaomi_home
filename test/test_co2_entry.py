# -*- coding: utf-8 -*-
"""Entry lifecycle with the real parser, sensor platform and registries."""
import asyncio
import logging
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest
from test_spec_co2 import CO2_URN
from test_spec_co2 import co2_parser_fixture  # pylint: disable=unused-import

# pylint: disable=import-outside-toplevel, protected-access
pytest.importorskip('homeassistant')
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest.mark.parametrize('co2_parser', ['custom_components.xiaomi_home.miot'],
                         indirect=True)
async def test_entry_reload_unload_and_remove(
    co2_parser, tmp_path, monkeypatch
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent))
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry, ConfigEntries
    from homeassistant.helpers import device_registry, entity_registry
    from homeassistant.helpers.entity_platform import EntityPlatform
    from custom_components import xiaomi_home as integration
    from custom_components.xiaomi_home import sensor
    from custom_components.xiaomi_home.miot.miot_storage import (
        DeviceManufacturer, MIoTStorage)

    hass = HomeAssistant(str(tmp_path / 'hass'))
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(
        version=1, minor_version=1, domain='xiaomi_home', title='Synthetic',
        data={'uid': 'synthetic', 'cloud_server': 'cn'}, options={},
        source='user', unique_id='synthetic', discovery_keys={},
        subentries_data=[])
    hass.config_entries._entries[entry.entry_id] = entry
    device_registry.async_setup(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    hass.config.components.add('sensor')
    store = MIoTStorage(str(tmp_path / 'integration'))
    await store.save_async(
        domain=DeviceManufacturer.DOMAIN, name='manufacturer',
        data={'data': {}, 'ts': int(time.time())})
    await store.update_user_config_async(
        'synthetic', 'cn', {'devices_remove': []})
    await integration.async_setup(hass, {})
    hass.data['xiaomi_home']['miot_storage'] = store
    platform = EntityPlatform(
        hass=hass, logger=logging.getLogger(__name__), domain='sensor',
        platform_name='xiaomi_home', platform=sensor,
        scan_interval=timedelta(seconds=30), entity_namespace=None)
    platform.config_entry = entry
    clients = []
    callbacks = {}

    async def client_factory(**unused_kwargs):
        client = SimpleNamespace(
            main_loop=asyncio.get_running_loop(), miot_storage=store,
            area_name_rule='none', cloud_server='cn',
            hide_non_standard_entities=False, display_binary_text=False,
            display_binary_bool=True, action_debug=False,
            sub_device_state=Mock(), request_refresh_prop=Mock(),
            deinit_async=AsyncMock(), device_list={'blt.synthetic': {
                'did': 'blt.synthetic', 'name': 'Synthetic', 'online': True,
                'model': 'miaomiaoce.airm.co2', 'urn': CO2_URN}})

        def subscribe(did, handler, siid, piid):
            callbacks[(did, siid, piid)] = handler

        def unsubscribe(did, siid, piid):
            callbacks.pop((did, siid, piid), None)

        client.sub_prop = subscribe
        client.unsub_prop = unsubscribe
        hass.data['xiaomi_home']['miot_clients'][entry.entry_id] = client
        clients.append(client)
        return client

    async def forward(config_entry, platforms):
        assert 'sensor' in platforms
        entities = []
        await sensor.async_setup_entry(hass, config_entry, entities.extend)
        await platform.async_add_entities(entities)

    async def unload(config_entry, platforms):
        assert config_entry is entry and 'sensor' in platforms
        await platform.async_reset()
        return True

    monkeypatch.setattr(integration, 'get_miot_instance_async', client_factory)
    monkeypatch.setattr(integration, 'MIoTSpecParser',
                        lambda **unused_kwargs: co2_parser)
    monkeypatch.setattr(
        hass.config_entries, 'async_forward_entry_setups', forward)
    monkeypatch.setattr(hass.config_entries, 'async_unload_platforms', unload)
    identity = None
    try:
        for value in [1217, 1193]:
            assert await integration.async_setup_entry(hass, entry)
            entity = next(e for e in platform.entities.values()
                          if e.spec.service.iid == 3 and e.spec.iid == 1029)
            assert entity.native_value is None
            current = (entity.unique_id, entity.entity_id, entity.device_info)
            if identity is None:
                identity = current
            else:
                assert current == identity
            callbacks[('blt.synthetic', 3, 1029)]({
                'did': 'blt.synthetic', 'siid': 3, 'piid': 1029,
                'value': value}, None)
            assert entity.native_value == value
            entities = list(platform.entities.values())
            timers = [e._pending_write_ha_state_timer for e in entities]
            assert await integration.async_unload_entry(hass, entry)
            clients[-1].deinit_async.assert_awaited_once()
            assert not callbacks
            assert all(timer is None or timer.cancelled() for timer in timers)
            assert entry.entry_id not in hass.data['xiaomi_home']['devices']
            assert entry.entry_id not in (
                hass.data['xiaomi_home']['miot_clients'])
        assert await integration.async_remove_entry(hass, entry)
        assert await store.load_user_config_async('synthetic', 'cn') == {}
    finally:
        await platform.async_reset()
        await hass.async_block_till_done()
        await hass.async_stop(force=True)
