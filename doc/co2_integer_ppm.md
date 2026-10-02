# CO₂ integer resolution for miaomiaoce.airm.co2

The verified instance
`urn:miot-spec-v2:device:air-monitor:0000A008:miaomiaoce-co2:1`, property
`3.1029`, declares a step of 100 ppm. OAuth cloud notifications can carry
finer integers. The existing entity precision conversion rounds them to that
step. The instance-specific rule uses `[400, 5000, 1]`, preserving valid
integer readings, including decreases. This is resolution, not ±1 ppm
measurement accuracy.

Only this complete instance/property rejects non-integer, boolean, string,
non-finite and out-of-range inputs before conversion. An invalid notification
is ignored and does not publish a new measurement; an invalid explicit read
returns `None`. The identity, property name, limits, permissions, ppm unit and
MEASUREMENT state class are retained. Other properties and models keep their
existing formatting. No additional entity, polling, restore or history repair
is introduced. A queued callback from a removed property subscription cannot
update a newly added entity using the same property key.

## Existing installations

Cached parsed specifications bypass updated modification rules. After
installing an approved build, use the integration's CONFIGURE option to update
entity conversion rules, then reload when requested. That option can refresh
multiple specifications in the selected entry. Do not delete production
storage as a workaround. Tests cover an existing step-100 cache, explicit
refresh, and dump/load. Reverting the rule also requires this existing refresh
path. The integration does not rewrite previous Recorder history.

## Evidence and limits

The public specification fixtures have source links and hashes in
`test/fixtures/README.md`; tests use synthetic values such as 1217 and 1193.
The source observation establishes cloud notification resolution; local hub
GET and notify must be validated separately before claiming full local support.
A specification permission, discovered gateway or successful TLS handshake
alone cannot prove either operation. Both reference models use BLE and cannot
be adapted using a direct UDP LAN allowlist.

The sensor starts without a restored value. Failed initial reads leave it
unknown until a valid read/notification arrives. Preserving integers does not
make an unavailable source readable or guarantee instantaneous startup.
On-device sampling, BLE broadcasts, gateway forwarding, cloud notifications
and Home Assistant statistics have different cadences. No fixed 6-second or
60-second Home Assistant notification interval is promised.

## Tests

Run the existing `github` tests and rule format checks separately. The entity
regressions additionally require an actual Home Assistant installation; they
explicitly skip when it is absent. In an isolated Home Assistant environment,
`test_co2_entity.py` uses real MIoTDevice, Sensor, EntityPlatform, ConfigEntry
and registries, mocking only communication. It verifies metadata/identity,
user rename retention, add/remove/re-add, timer cancellation, late callbacks,
valid decreases, boundaries and invalid inputs. It does not connect devices
or run a production restart. An additional entry test calls the real
integration setup/unload/remove
functions across two setup cycles, using the real parser, storage, sensor
setup and registries. OAuth/client communication and platform forwarding are
mocked; other platform implementations and real certificate rotation are not
part of this test. Gateway routing has separate acceptance requirements.
