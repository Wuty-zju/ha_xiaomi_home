# Public CO₂ specifications

These are anonymous official MIoT instance responses, fetched 2026-10-03.
They contain product definitions, not private device observations. The tests
use synthetic readings only. Fixture bytes are preserved for verification.
The source is Xiaomi's public specification service; these are factual
specifications used by the integration, not code copied from Xiaomi MIoT.

- `miaomiaoce_co2.json`: [official instance](https://miot-spec.org/miot-spec-v2/instance?type=urn%3Amiot-spec-v2%3Adevice%3Aair-monitor%3A0000A008%3Amiaomiaoce-co2%3A1),
  SHA-256 `5dfc633e45dcedd0d2d199657947b9cdfba688295606ac0b9b64a90c130436ab`.
- `xiaomi_new3pr.json`: [official instance](https://miot-spec.org/miot-spec-v2/instance?type=urn%3Amiot-spec-v2%3Adevice%3Atemperature-humidity-sensor%3A0000A00A%3Axiaomi-new3pr%3A1%3A0000D063),
  SHA-256 `4e1ac0233a7c82477bd35fd23817a40422cb92a96ae89deea31237aab9ddd37c`.

The CO₂ step override is an independent implementation at the target's
existing spec modification point. No source-repository client or credentials
are copied. Keep the applicable root LICENSE.md and LegalNotice.md when
redistributing this integration.
