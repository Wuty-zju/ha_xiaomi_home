# -*- coding: utf-8 -*-
"""Preserve entry ownership until all platforms have unloaded."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest

# pylint: disable=import-outside-toplevel
pytest.importorskip('homeassistant')
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest.mark.parametrize('unload_ok', [False, True])
async def test_unload_retains_client_until_platforms_finish(
    tmp_path, monkeypatch, unload_ok
):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent))
    from homeassistant.core import HomeAssistant
    from homeassistant.config_entries import ConfigEntry, ConfigEntries
    from custom_components.xiaomi_home import async_unload_entry
    from custom_components.xiaomi_home.miot.const import (
        DOMAIN, SUPPORTED_PLATFORMS)

    hass = HomeAssistant(str(tmp_path / 'hass'))
    hass.config_entries = ConfigEntries(hass, {})
    entry = ConfigEntry(
        version=1, minor_version=1, domain=DOMAIN, title='Synthetic',
        data={}, options={}, source='user', unique_id='synthetic',
        discovery_keys={}, subentries_data=[])
    client = SimpleNamespace(deinit_async=AsyncMock())
    other_client = SimpleNamespace(deinit_async=AsyncMock())
    entry_entities, entry_devices = [], []
    hass.data[DOMAIN] = {
        'entities': {entry.entry_id: entry_entities, 'other': []},
        'devices': {entry.entry_id: entry_devices, 'other': []},
        'miot_clients': {entry.entry_id: client, 'other': other_client}}
    unload = AsyncMock(return_value=unload_ok)
    monkeypatch.setattr(hass.config_entries, 'async_unload_platforms', unload)
    try:
        assert await async_unload_entry(hass, entry) is unload_ok
        unload.assert_awaited_once_with(entry, SUPPORTED_PLATFORMS)
        data = hass.data[DOMAIN]
        if unload_ok:
            assert all(entry.entry_id not in data[key]
                       for key in ['entities', 'devices', 'miot_clients'])
            client.deinit_async.assert_awaited_once()
        else:
            assert data['entities'][entry.entry_id] is entry_entities
            assert data['devices'][entry.entry_id] is entry_devices
            assert data['miot_clients'][entry.entry_id] is client
            client.deinit_async.assert_not_awaited()
            # A subsequent unload can finish cleanup of the retained entry.
            unload.return_value = True
            assert await async_unload_entry(hass, entry)
            client.deinit_async.assert_awaited_once()
        assert data['miot_clients']['other'] is other_client
        assert 'other' in data['entities'] and 'other' in data['devices']
        other_client.deinit_async.assert_not_awaited()
    finally:
        await hass.async_block_till_done()
        await hass.async_stop(force=True)
