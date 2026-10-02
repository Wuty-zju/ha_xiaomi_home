# -*- coding: utf-8 -*-
"""Offline property refresh regressions at the real client boundaries."""
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import pytest

# pylint: disable=import-outside-toplevel, protected-access
pytest.importorskip('homeassistant')
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


def make_client(tmp_path, monkeypatch, mode='auto'):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parent.parent))
    from custom_components.xiaomi_home.miot.miot_client import MIoTClient
    from custom_components.xiaomi_home.miot.miot_network import MIoTNetwork
    from custom_components.xiaomi_home.miot.miot_mdns import MipsService
    from custom_components.xiaomi_home.miot.miot_storage import MIoTStorage

    client = MIoTClient(
        entry_id='synthetic', entry_data={
            'uid': 'synthetic', 'cloud_server': 'cn', 'ctrl_mode': mode},
        network=Mock(spec=MIoTNetwork), storage=MIoTStorage(str(tmp_path)),
        mips_service=Mock(spec=MipsService),
        miot_lan=SimpleNamespace(init_done=False))
    client._network.network_status = True
    client._http = SimpleNamespace(get_props_async=AsyncMock(return_value=[]),
                                   get_prop_async=AsyncMock(return_value=None))
    client._device_list_cache = {'synthetic-a': {}, 'synthetic-b': {}}
    client._MIoTClient__on_prop_msg = Mock()
    return client


def queue(client, did='synthetic-a', siid=3, piid=1029):
    params = {'did': did, 'siid': siid, 'piid': piid}
    client._refresh_props_list[f'{did}|{siid}|{piid}'] = params
    return params


def cancel_timer(client):
    if client._refresh_props_timer:
        client._refresh_props_timer.cancel()
        client._refresh_props_timer = None


async def test_partial_cloud_response_keeps_errors_and_dispatches_once(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    first = queue(client)
    second = queue(client, did='synthetic-b')
    client._http.get_props_async.return_value = [
        {**first, 'code': -704220043},
        {**second, 'code': 0, 'value': 1217},
        {**second, 'code': 0, 'value': 1217}]
    assert await client._MIoTClient__refresh_props_from_cloud()
    assert list(client._refresh_props_list.values()) == [first]
    assert client._MIoTClient__on_prop_msg.call_count == 1
    await client._MIoTClient__refresh_props_from_cloud()
    assert client._MIoTClient__on_prop_msg.call_count == 1


@pytest.mark.parametrize('result', [
    None, {}, [], 'invalid', True,
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'value': 1217},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': 1, 'value': 1217},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': False,
     'value': 1217},
    {'did': 'other-device', 'siid': 3, 'piid': 1029, 'code': 0, 'value': 1217},
    {'did': 'synthetic-a', 'siid': '3', 'piid': 1029, 'code': 0,
     'value': 1217},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': 0, 'value': None},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': 0,
     'value': float('nan')},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': 0,
     'value': float('inf')},
    {'did': 'synthetic-a', 'siid': 3, 'piid': 1029, 'code': 0, 'value': {}},
])
async def test_invalid_cloud_result_keeps_request(
    tmp_path, monkeypatch, result
):
    client = make_client(tmp_path, monkeypatch)
    params = queue(client)
    client._http.get_props_async.return_value = [result]
    assert not await client._MIoTClient__refresh_props_from_cloud()
    assert list(client._refresh_props_list.values()) == [params]
    client._MIoTClient__on_prop_msg.assert_not_called()


@pytest.mark.parametrize('value', [0, False])
async def test_zero_and_false_are_valid(tmp_path, monkeypatch, value):
    client = make_client(tmp_path, monkeypatch)
    params = queue(client)
    client._http.get_props_async.return_value = [
        {**params, 'code': 0, 'value': value}]
    assert await client._MIoTClient__refresh_props_from_cloud()
    assert not client._refresh_props_list
    client._http.get_prop_async.return_value = value
    assert await client.get_prop_async(**params) is value


@pytest.mark.parametrize('mode', ['auto', 'cloud'])
async def test_partial_cloud_falls_back_only_in_auto(
    tmp_path, monkeypatch, mode
):
    client = make_client(tmp_path, monkeypatch, mode)
    first = queue(client)
    second = queue(client, did='synthetic-b')
    client._http.get_props_async.return_value = [
        {**first, 'code': -1}, {**second, 'code': 0, 'value': 1193}]
    gateway = SimpleNamespace(mips_state=True,
                              get_prop_async=AsyncMock(return_value=1217))
    client._mips_local['synthetic-group'] = gateway
    client._device_list_gateway[first['did']] = {
        'group_id': 'synthetic-group', 'online': True, 'specv2_access': True}
    await client._MIoTClient__refresh_props_handler()
    if mode == 'auto':
        gateway.get_prop_async.assert_awaited_once()
        assert not client._refresh_props_list
        assert client._MIoTClient__on_prop_msg.call_count == 2
    else:
        gateway.get_prop_async.assert_not_awaited()
        assert list(client._refresh_props_list.values()) == [first]
    cancel_timer(client)


@pytest.mark.parametrize('route', ['gw', 'lan'])
@pytest.mark.parametrize('value', [0, False])
async def test_local_partial_failure_and_device_throttle(
    tmp_path, monkeypatch, route, value
):
    client = make_client(tmp_path, monkeypatch)
    first = queue(client)
    second = queue(client, did='synthetic-b')
    third = queue(client, piid=1030)
    local = SimpleNamespace(mips_state=True, init_done=True,
                            get_prop_async=AsyncMock(side_effect=[value, None]))
    if route == 'gw':
        client._mips_local['synthetic-group'] = local
        client._device_list_gateway = {
            did: {'online': True, 'specv2_access': True,
                  'group_id': 'synthetic-group'} for did in [
                      first['did'], second['did']]}
    else:
        client._miot_lan = local
        client._device_list_lan = {did: {'online': True}
                                  for did in [first['did'], second['did']]}
    method = getattr(client, f'_MIoTClient__refresh_props_from_{route}')
    attempted, deferred = set(), set()
    assert await method(attempted, deferred)
    assert list(client._refresh_props_list.values()) == [second, third]
    assert len(attempted) == 2 and len(deferred) == 1
    assert local.get_prop_async.await_count == 2
    assert client._MIoTClient__on_prop_msg.call_count == 1
    result = client._MIoTClient__on_prop_msg.call_args.kwargs['params']
    assert result['value'] is value


@pytest.mark.parametrize('online, access, connected', [
    (False, True, True), (True, False, True), (True, True, False)])
async def test_gateway_qualification(tmp_path, monkeypatch,
                                     online, access, connected):
    client = make_client(tmp_path, monkeypatch)
    params = queue(client)
    gateway = SimpleNamespace(mips_state=connected,
                              get_prop_async=AsyncMock(return_value=1217))
    client._mips_local['synthetic-group'] = gateway
    client._device_list_gateway[params['did']] = {
        'group_id': 'synthetic-group', 'online': online,
        'specv2_access': access}
    assert not await client._MIoTClient__refresh_props_from_gw()
    gateway.get_prop_async.assert_not_awaited()
    assert len(client._refresh_props_list) == 1


async def test_failed_property_has_finite_budget_despite_other_success(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    failed = queue(client)
    for index in range(4):
        good = queue(client, did='synthetic-b', piid=index + 1)
        client._http.get_props_async.return_value = [
            {**failed, 'code': -1}, {**good, 'code': 0, 'value': False}]
        await client._MIoTClient__refresh_props_handler()
        cancel_timer(client)
    assert not client._refresh_props_list
    assert not client._refresh_props_retry_count
    assert client._MIoTClient__on_prop_msg.call_count == 4


async def test_batch_limit_does_not_exhaust_unattempted_keys(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    for piid in range(151):
        queue(client, piid=piid)
    attempted, deferred = set(), set()
    await client._MIoTClient__refresh_props_from_cloud(
        attempted=attempted, deferred=deferred)
    assert len(attempted) == 150
    assert deferred == {'synthetic-a|3|150'}
    assert len(client._refresh_props_list) == 151


async def test_exception_keeps_requests_and_late_result_is_ignored(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    params = queue(client)
    client._http.get_props_async.side_effect = RuntimeError('synthetic failure')
    assert not await client._MIoTClient__refresh_props_from_cloud()
    assert len(client._refresh_props_list) == 1
    future = asyncio.get_running_loop().create_future()

    async def delayed(**_kwargs):
        return await future

    client._http.get_props_async.side_effect = delayed
    task = asyncio.create_task(client._MIoTClient__refresh_props_from_cloud())
    await asyncio.sleep(0)
    client._refresh_props_list.clear()  # The teardown contract.
    future.set_result([{**params, 'code': 0, 'value': 1217}])
    assert not await task
    client._MIoTClient__on_prop_msg.assert_not_called()


async def test_local_exception_does_not_drop_other_properties(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    first = queue(client)
    second = queue(client, did='synthetic-b')
    gateway = SimpleNamespace(
        mips_state=True,
        get_prop_async=AsyncMock(
            side_effect=[RuntimeError('synthetic'), False]))
    client._mips_local['synthetic-group'] = gateway
    client._device_list_gateway = {
        did: {'group_id': 'synthetic-group', 'online': True,
              'specv2_access': True} for did in [first['did'], second['did']]}
    assert await client._MIoTClient__refresh_props_from_gw()
    assert list(client._refresh_props_list.values()) == [first]
    assert client._MIoTClient__on_prop_msg.call_count == 1


async def test_teardown_cancels_running_refresh_and_timer(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch, mode='cloud')
    queue(client)
    future = asyncio.get_running_loop().create_future()

    async def delayed(**_kwargs):
        return await future

    client._http.get_props_async.side_effect = delayed
    client._http.deinit_async = AsyncMock()
    client._oauth = SimpleNamespace(deinit_async=AsyncMock())
    client._mips_cloud = Mock()
    client._persistence_notify = Mock()
    client._MIoTClient__start_refresh_props()
    task = client._refresh_props_task
    await asyncio.sleep(0)
    timer = asyncio.get_running_loop().call_later(30, lambda: None)
    client._refresh_props_timer = timer
    await client.deinit_async()
    assert task.cancelled()
    assert future.cancelled()
    assert timer.cancelled()
    assert client._refresh_props_task is None
    assert client._refresh_props_timer is None
    assert not client._refresh_props_list
    client._MIoTClient__on_prop_msg.assert_not_called()


@pytest.mark.parametrize('value', [None, {}, [], float('nan'), float('inf')])
async def test_invalid_local_values_keep_request(tmp_path, monkeypatch, value):
    client = make_client(tmp_path, monkeypatch)
    params = queue(client)
    gateway = SimpleNamespace(mips_state=True,
                              get_prop_async=AsyncMock(return_value=value))
    client._mips_local['synthetic-group'] = gateway
    client._device_list_gateway[params['did']] = {
        'group_id': 'synthetic-group', 'online': True, 'specv2_access': True}
    assert not await client._MIoTClient__refresh_props_from_gw()
    assert list(client._refresh_props_list.values()) == [params]
    client._MIoTClient__on_prop_msg.assert_not_called()


async def test_handler_preserves_budget_of_deferred_batch(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch)
    for piid in range(151):
        queue(client, piid=piid)

    async def successful_batch(params):
        return [{**item, 'code': 0, 'value': 0} for item in params]

    client._http.get_props_async.side_effect = successful_batch
    await client._MIoTClient__refresh_props_handler()
    cancel_timer(client)
    assert len(client._refresh_props_list) == 1
    assert not client._refresh_props_retry_count
    await client._MIoTClient__refresh_props_handler()
    assert not client._refresh_props_list
    assert client._MIoTClient__on_prop_msg.call_count == 151


async def test_concurrent_request_keeps_budget_and_only_one_timer(
    tmp_path, monkeypatch
):
    client = make_client(tmp_path, monkeypatch, mode='cloud')
    first = queue(client)
    future = asyncio.get_running_loop().create_future()

    async def delayed(**_kwargs):
        return await future

    client._http.get_props_async.side_effect = delayed
    client._MIoTClient__start_refresh_props()
    task = client._refresh_props_task
    await asyncio.sleep(0)
    client.request_refresh_prop(did='synthetic-b', siid=3, piid=1029)
    concurrent_timer = client._refresh_props_timer
    future.set_result([{**first, 'code': 0, 'value': 1217}])
    await task
    assert concurrent_timer.cancelled()
    assert client._refresh_props_timer is not concurrent_timer
    assert not client._refresh_props_retry_count
    assert len(client._refresh_props_list) == 1
    cancel_timer(client)
