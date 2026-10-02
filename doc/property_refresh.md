# Partial property refresh results

A startup batch can return a value for one property and an error or no row for
another. Previously the cloud refresher removed the entire batch from the
queue and returned success, discarding missing properties. The coordinator's
boolean short circuit also skipped local fallback after any reported success.
Local refreshers had similar loss on partial success or missing device routes.

Requests now remain queued until a matching successful response is accepted.
Cloud reads require an integer success code of zero, matching DID/siid/piid,
and a finite scalar value. Duplicate or unsolicited results are ignored.
Zero and False are valid property values; a null, missing, non-finite or
structured value is not a successful read. This transport check is separate
from property-specific semantic validation (e.g. the CO₂ integer/range guard).

Only pending properties continue to the next existing route. CLOUD mode never
uses a local fallback. AUTO retains cloud-cache reads first, then an online,
Spec-V2-capable, connected central gateway. Existing LAN eligibility and the
central-gateway precedence remain. A local device is queried at most once per
cycle. This does not change the subscription-source priority or add polling.

Each pending property gets one initial attempt and up to three retry cycles.
Successes of other properties cannot reset its budget. Properties deferred by
the cloud batch limit or local per-device throttle do not spend their budget
until attempted; properties without a usable route also expire. Expired reads
leave the entity unknown (or preserve its last valid state); no value is made
up and no restoration is claimed as a fresh measurement.

The refresh task is retained and cancelled on client teardown. Responses are
matched to the original queued object, so a late response after teardown
cannot dispatch to a new generation. HTTP coalesced reads likewise check the
original request/Future, ignore completed or cancelled Futures, and shield
the shared Future from cancellation by one caller. Transport failures finish
waiting HTTP reads with None rather than leave dead Futures cached.

Offline regressions exercise the real MIoTClient and MIoTHttpClient methods
with mocked communication only. The MIoTClient cases need Home Assistant and
explicitly skip when it is absent; HTTP cases run with the existing core test
fixture. Tests cover partial errors/missing rows, bad identities/codes/shapes,
0/False, finite retry budgets, AUTO/CLOUD, qualification, batch/device limits,
exceptions, teardown and late replies. These tests do not prove a particular
physical device or gateway implements the requested property.
