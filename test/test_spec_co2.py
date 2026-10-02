# -*- coding: utf-8 -*-
"""Offline regression tests for the verified CO2 instance override."""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
import pytest_asyncio

# pylint: disable=import-outside-toplevel, protected-access

CO2_URN = 'urn:miot-spec-v2:device:air-monitor:0000A008:miaomiaoce-co2:1'
NEW3PR_URN = (
    'urn:miot-spec-v2:device:temperature-humidity-sensor:0000A00A:'
    'xiaomi-new3pr:1:0000D063')


@pytest_asyncio.fixture(name='co2_parser')
async def co2_parser_fixture(tmp_path, monkeypatch):
    from miot.common import MIoTHttp
    from miot.miot_spec import MIoTSpecParser
    from miot.miot_storage import MIoTStorage

    fixture_path = Path(__file__).parent / 'fixtures'
    instances = {
        CO2_URN: json.loads((fixture_path / 'miaomiaoce_co2.json').read_text()),
        NEW3PR_URN: json.loads(
            (fixture_path / 'xiaomi_new3pr.json').read_text())}

    async def get_json(url, params=None, **_kwargs):
        if url.endswith('/instance'):
            urn = params['type']
            instance = copy.deepcopy(instances.get(urn, instances[CO2_URN]))
            instance['type'] = urn
            return instance
        if url.endswith('/instance/v2/multiLanguage'):
            return {'data': {}}
        # This test has no dependency on current network translations.
        return {}

    monkeypatch.setattr(MIoTHttp, 'get_json_async', get_json)
    parser = MIoTSpecParser(lang='en', storage=MIoTStorage(str(tmp_path)))
    monkeypatch.setattr(parser._std_lib, 'refresh_async',
                        AsyncMock(return_value=True))
    await parser.init_async()
    yield parser
    await parser.deinit_async()


def co2_property(instance, siid=3):
    return next(prop for service in instance.services if service.iid == siid
                for prop in service.properties if prop.iid == 1029)


@pytest.mark.github
@pytest.mark.asyncio
async def test_co2_rule_and_round_trip(co2_parser):
    from miot.miot_spec import MIoTSpecInstance

    instance = await co2_parser.parse(CO2_URN)
    prop = co2_property(instance)
    assert prop.value_range.dump() == {'min': 400, 'max': 5000, 'step': 1}
    assert prop.unit == 'ppm'
    assert prop.format_ is int
    assert set(prop.access) == {'read', 'notify'}
    assert prop.name == 'co2-density'
    for value in [1217, 1193, 400, 5000]:
        assert prop.value_precision(value) == value
    loaded = MIoTSpecInstance.load(instance.dump())
    assert loaded.dump() == instance.dump()
    assert co2_property(loaded).value_precision(1193) == 1193


@pytest.mark.github
@pytest.mark.asyncio
async def test_existing_cache_needs_explicit_refresh(co2_parser):
    instance = await co2_parser.parse(CO2_URN)
    prop = co2_property(instance)
    prop.value_range = [400, 5000, 100]
    assert await co2_parser._MIoTSpecParser__cache_set(CO2_URN, instance.dump())
    cached = await co2_parser.parse(CO2_URN)
    assert co2_property(cached).value_precision(1217) == 1200
    assert await co2_parser.refresh_async([CO2_URN]) == 1
    refreshed = await co2_parser.parse(CO2_URN)
    assert co2_property(refreshed).value_precision(1217) == 1217
    # All other properties retain the existing conversion metadata.
    before = instance.dump()
    after = refreshed.dump()
    cached_prop = next(p for s in before['services'] if s['iid'] == 3
                       for p in s['properties'] if p['iid'] == 1029)
    cached_prop['value_range']['step'] = 1
    assert before == after


@pytest.mark.github
@pytest.mark.asyncio
@pytest.mark.parametrize('urn', [CO2_URN.replace(':1', ':2'),
                                CO2_URN + ':0000D001'])
async def test_other_instances_keep_step100(co2_parser, urn):
    instance = await co2_parser.parse(urn)
    assert co2_property(instance).value_range.step == 100
    assert co2_property(instance).value_precision(1217) == 1200


@pytest.mark.github
@pytest.mark.asyncio
async def test_new3pr_is_unchanged(co2_parser):
    instance = await co2_parser.parse(NEW3PR_URN)
    prop = co2_property(instance, siid=8)
    assert prop.value_range.step == 1
    assert prop.value_precision(1217) == 1217
    assert prop.value_precision(1193) == 1193
