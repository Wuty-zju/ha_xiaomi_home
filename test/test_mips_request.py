# -*- coding: utf-8 -*-
"""Local MIPS request completion without connecting a gateway."""
import asyncio
from unittest.mock import Mock
import pytest
import pytest_asyncio

# pylint: disable=import-outside-toplevel, protected-access
pytestmark = [pytest.mark.github, pytest.mark.asyncio]


@pytest_asyncio.fixture(name='mips_request')
async def mips_request_fixture(monkeypatch):
    from miot.miot_mips import MipsLocalClient

    loop = asyncio.get_running_loop()
    client = MipsLocalClient(
        did='synthetic', host='synthetic.invalid', group_id='synthetic',
        ca_file='', cert_file='', key_file='')
    register = Mock(return_value=True)
    monkeypatch.setattr(client, '_MipsLocalClient__request_external', register)
    errors = []
    previous_handler = loop.get_exception_handler()
    loop.set_exception_handler(lambda unused_loop, context:
                               errors.append(context))
    try:
        yield client, register, errors
        assert client._mips_thread is None
    finally:
        loop.set_exception_handler(previous_handler)


async def begin_request(client, register):
    task = asyncio.create_task(client.get_prop_async(
        did='blt.synthetic', siid=3, piid=1029))
    await asyncio.sleep(0)
    registration = register.call_args.kwargs
    assert registration['topic'] == 'proxy/get'
    return task, registration['on_reply'], registration['on_reply_ctx']


@pytest.mark.parametrize('reply_before_cancel', [False, True])
async def test_cancelled_request_ignores_late_reply(
    mips_request, reply_before_cancel
):
    client, register, errors = mips_request
    task, callback, context = await begin_request(client, register)
    if reply_before_cancel:
        callback('{"value":1217}', context)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    if not reply_before_cancel:
        callback('{"value":1217}', context)
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert context.cancelled()
    assert not errors


async def test_completed_request_ignores_duplicate_reply(mips_request):
    client, register, errors = mips_request
    task, callback, context = await begin_request(client, register)
    callback('{"value":1217}', context)
    callback('{"value":1193}', context)
    assert await task == 1217
    await asyncio.sleep(0)
    assert not errors


async def test_reply_from_transport_thread_completes_request(mips_request):
    client, register, errors = mips_request
    task, callback, context = await begin_request(client, register)
    await asyncio.to_thread(callback, '{"value":1193}', context)
    assert await task == 1193
    assert not errors


@pytest.mark.parametrize('response', [
    None, [], {}, {'code': -1, 'value': 1217},
    {'code': False, 'value': 1217}, {'code': '0', 'value': 1217},
    {'error': {'code': -1}, 'value': 1217},
    {'did': 'blt.other', 'value': 1217}, {'did': None, 'value': 1217},
    {'siid': 4, 'value': 1217}, {'siid': 3.0, 'value': 1217},
    {'piid': 1028, 'value': 1217}, {'piid': '1029', 'value': 1217}])
async def test_native_get_rejects_explicit_errors_and_conflicting_identity(
    mips_request, response
):
    import json

    client, register, errors = mips_request
    task, callback, context = await begin_request(client, register)
    callback(json.dumps(response), context)
    assert await task is None
    assert not errors


@pytest.mark.parametrize('value',
                         [1217, 1193, 400, 5000, 0, False, 'synthetic'])
@pytest.mark.parametrize('include_identity', [False, True])
async def test_native_get_keeps_value_ts_contract_and_other_value_types(
    mips_request, value, include_identity
):
    import json

    client, register, errors = mips_request
    task, callback, context = await begin_request(client, register)
    response = {'value': value, 'ts': 1700000000}
    if include_identity:
        response.update(did='blt.synthetic', siid=3, piid=1029, code=0)
    callback(json.dumps(response), context)
    result = await task
    assert type(result) is type(value) and result == value
    assert not errors


@pytest.mark.parametrize('payload', [
    'bad JSON', 'null', '[]', '{}',
    '{"did":"blt.other","siid":3,"piid":1029,"value":1217}',
    '{"did":"blt.synthetic","siid":true,"piid":1029,"value":1217}',
    '{"did":"blt.synthetic","siid":3,"piid":"1029","value":1217}',
    '{"did":"blt.synthetic","siid":4,"piid":1029,"value":1217}',
    '{"did":"blt.synthetic","siid":3,"piid":1028,"value":1217}',
    '{"did":"blt.synthetic","siid":3,"piid":1029}'])
async def test_native_notify_rejects_bad_payload_or_subscription_identity(
    mips_request, monkeypatch, payload
):
    client, unused_register, errors = mips_request
    broadcast = Mock(return_value=True)
    handler = Mock()
    monkeypatch.setattr(client, '_MipsLocalClient__reg_broadcast_external',
                        broadcast)
    client.sub_prop('blt.synthetic', handler, siid=3, piid=1029)
    callback = broadcast.call_args.kwargs['handler']
    callback('synthetic', payload, None)
    handler.assert_not_called()
    assert not errors


@pytest.mark.parametrize('wildcard', [False, True])
@pytest.mark.parametrize('value', [1193, 0, False, 'synthetic'])
async def test_native_notify_preserves_valid_property_value_types(
    mips_request, monkeypatch, wildcard, value
):
    import json

    client, unused_register, errors = mips_request
    broadcast = Mock(return_value=True)
    handler = Mock()
    monkeypatch.setattr(client, '_MipsLocalClient__reg_broadcast_external',
                        broadcast)
    client.sub_prop('blt.synthetic', handler,
                    siid=None if wildcard else 3,
                    piid=None if wildcard else 1029)
    callback = broadcast.call_args.kwargs['handler']
    response = {'did': 'blt.synthetic', 'siid': 3, 'piid': 1029,
                'value': value}
    callback('synthetic', json.dumps(response), None)
    handler.assert_called_once_with(response, None)
    assert not errors


async def test_native_wildcard_accepts_other_property_identifiers(
    mips_request, monkeypatch
):
    import json

    client, unused_register, errors = mips_request
    broadcast = Mock(return_value=True)
    handler = Mock()
    monkeypatch.setattr(client, '_MipsLocalClient__reg_broadcast_external',
                        broadcast)
    client.sub_prop('blt.synthetic', handler)
    callback = broadcast.call_args.kwargs['handler']
    response = {'did': 'blt.synthetic', 'siid': 4, 'piid': 2, 'value': False}
    callback('synthetic', json.dumps(response), None)
    handler.assert_called_once_with(response, None)
    assert not errors
