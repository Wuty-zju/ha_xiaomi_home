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
