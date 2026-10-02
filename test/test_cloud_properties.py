# -*- coding: utf-8 -*-
"""Offline cloud property identity, error and Future regressions."""
import asyncio
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio

# pylint: disable=import-outside-toplevel, protected-access
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest_asyncio.fixture(name='property_http')
async def property_http_fixture():
    from miot.miot_cloud import MIoTHttpClient

    client = MIoTHttpClient(cloud_server='cn', client_id='synthetic',
                            access_token='synthetic', uuid='synthetic')
    client.get_props_async = AsyncMock(return_value=[])
    yield client
    await client.deinit_async()


PARAMS = {'did': 'synthetic-a', 'siid': 3, 'piid': 1029}


@pytest.mark.parametrize('result', [
    {**PARAMS, 'code': -1, 'value': 1217},
    {**PARAMS, 'value': 1217},
    {**PARAMS, 'code': 0, 'value': None},
    {**PARAMS, 'code': 0, 'did': 'synthetic-b', 'value': 1217},
    {**PARAMS, 'code': 0, 'siid': '3', 'value': 1217},
    {**PARAMS, 'code': 0, 'piid': True, 'value': 1217},
    {**PARAMS, 'code': 0, 'value': float('inf')},
    None, [], 'malformed'])
async def test_immediate_read_rejects_invalid_response(property_http, result):
    property_http.get_props_async.return_value = [result]
    result_value = await property_http.get_prop_async(
        **PARAMS, immediately=True)
    assert result_value is None


@pytest.mark.parametrize('value', [0, False, 1217, 'valid-string'])
async def test_immediate_read_keeps_valid_values(property_http, value):
    property_http.get_props_async.return_value = [{**PARAMS, 'code': 0,
                                                 'value': value}]
    result_value = await property_http.get_prop_async(
        **PARAMS, immediately=True)
    assert result_value == value


async def test_coalesced_caller_cancellation_does_not_cancel_shared_future(
    property_http
):
    first = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    second = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    await asyncio.sleep(0)
    property_http._get_prop_timer.cancel()
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    property_http.get_props_async.return_value = [
        {**PARAMS, 'code': 0, 'value': 1217},
        {**PARAMS, 'code': 0, 'value': 1217}]
    assert await property_http._MIoTHttpClient__get_prop_handler()
    assert await second == 1217
    assert not property_http._get_prop_list


async def test_partial_batch_error_with_value_is_not_success(property_http):
    first = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    other = {**PARAMS, 'did': 'synthetic-b'}
    second = asyncio.create_task(property_http.get_prop_async(**other))
    await asyncio.sleep(0)
    property_http._get_prop_timer.cancel()
    property_http.get_props_async.return_value = [
        {**PARAMS, 'code': -1, 'value': 1217},
        {**other, 'code': 0, 'value': False}]
    await property_http._MIoTHttpClient__get_prop_handler()
    assert await first is None
    assert await second is False


async def test_batch_exception_finishes_futures(property_http):
    task = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    await asyncio.sleep(0)
    property_http._get_prop_timer.cancel()
    property_http.get_props_async.side_effect = RuntimeError(
        'synthetic failure')
    await property_http._MIoTHttpClient__get_prop_handler()
    assert await task is None
    assert not property_http._get_prop_list


async def test_late_batch_does_not_complete_replacement_future(property_http):
    old = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    await asyncio.sleep(0)
    property_http._get_prop_timer.cancel()
    reply = asyncio.get_running_loop().create_future()

    async def delayed(unused_params):
        return await reply

    property_http.get_props_async.side_effect = delayed
    handler = asyncio.create_task(
        property_http._MIoTHttpClient__get_prop_handler())
    await asyncio.sleep(0)
    old_item = property_http._get_prop_list.pop('synthetic-a.3.1029')
    old_item['fut'].cancel()
    with pytest.raises(asyncio.CancelledError):
        await old
    new_future = asyncio.get_running_loop().create_future()
    property_http._get_prop_list['synthetic-a.3.1029'] = {
        'param': PARAMS, 'fut': new_future}
    reply.set_result([{**PARAMS, 'code': 0, 'value': 1217}])
    await handler
    assert not new_future.done()
    item = property_http._get_prop_list['synthetic-a.3.1029']
    assert item['fut'] is new_future


@pytest.mark.parametrize('batch', [None, {}, True, 'malformed'])
async def test_malformed_batch_finishes_future(property_http, batch):
    task = asyncio.create_task(property_http.get_prop_async(**PARAMS))
    await asyncio.sleep(0)
    property_http._get_prop_timer.cancel()
    property_http.get_props_async.return_value = batch
    await property_http._MIoTHttpClient__get_prop_handler()
    assert await task is None
