# Config Entry unload ownership

When `async_unload_platforms` returns `False`, the entry must retain its
client and entry data and report that unloading failed. Deinitializing the
client in this situation leaves surviving platform entities without their
communication owner. A subsequent unload can finish the normal cleanup.

This fix only changes the failed-unload path. Successful unload still removes
entry-local entities/devices, awaits client cleanup and leaves other entries
alone. It does not install or reload a production integration.

`test/test_entry_unload.py` invokes the actual integration unload function
with a real Home Assistant and Config Entry. Only platform-unload results
and client cleanup are mocked. It covers failure, a successful subsequent
attempt, normal success and isolation of another entry. Platform internals
and real client network shutdown have separate regression tests.
