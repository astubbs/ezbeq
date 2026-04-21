---
title: "feat: Add load-profile convenience endpoint and mDNS service discovery"
type: feat
status: active
date: 2026-04-21
origin: /Users/astubbs/github/beqdesigner/docs/brainstorms/2026-04-21-push-to-ezbeq-requirements.md
---

# feat: Add load-profile convenience endpoint and mDNS service discovery

## Overview

Prepare ezBEQ to receive auto-generated BEQ profiles pushed from BEQ Designer. Two features: (1) a single API endpoint that loads biquad filters + sets master volume + activates a slot in one call, and (2) mDNS/Bonjour service advertisement so BEQ Designer can auto-discover ezBEQ on the local network.

## Problem Frame

BEQ Designer can now automatically generate BEQ filter profiles. To push a profile to a MiniDSP via ezBEQ, a client currently needs 3 separate API calls (load biquads, set gain, activate slot). A convenience endpoint reduces this to one call and simplifies the integration. mDNS discovery eliminates the need for users to manually find and enter the ezBEQ IP address.

(see origin: beqdesigner docs/brainstorms/2026-04-21-push-to-ezbeq-requirements.md)

## Requirements Trace

- R2. Load filter biquad coefficients into slot 1 on the target device
- R3. After loading, activate slot 1 so the filter takes effect immediately
- R4. Apply master volume adjustment (mv_adjust) alongside the biquad filters
- R5. Auto-discover ezBEQ instances on the local network (mDNS)

R1, R6-R9 are BEQ Designer side (deferred to separate tasks).

## Scope Boundaries

- ezBEQ changes only - no BEQ Designer modifications
- No Home Assistant, playback detection, or catalogue submission
- Single device support (first/only configured device)

### Deferred to Separate Tasks

- BEQ Designer push UI and CLI flag: separate PR in beqdesigner repo
- Home Assistant integration: future iteration

## Context & Research

### Relevant Code and Patterns

- `ezbeq/apis/devices.py` - all device API resources, Flask-RESTx namespace pattern
- `ezbeq/main.py:create_app()` - namespace registration via `decorate_ns()`, `resource_args` injection
- `ezbeq/device.py:DeviceRepository` - bridge between API layer and device drivers
- `ezbeq/minidsp.py:Minidsp.load_filter()` - has dead `mv_adjust` parameter (never applied for MiniDSP)
- `ezbeq/minidsp.py:MinidspBeqCommandGenerator.filt()` - generates biquad commands from catalogue entries
- `tests/test_minidsp_api.py` - API test patterns with `MinidspSpy` for command verification

### Institutional Learnings

- New API resources must use `**kwargs` injection from `resource_args` - no other dependency injection pattern
- `_hydrate_cache_broadcast(func)` is the standard pattern for all mutating device operations
- `__do_run()` auto-prepends `config N` (slot switch) when the device isn't already on the target slot
- Master volume gain range: `-127.0` to `0.0`
- No `docs/solutions/` exists for this project yet

## Key Technical Decisions

- **New dedicated endpoint over v3 PATCH composition**: A `PUT /api/1/devices/{device}/profile` endpoint is clearer than asking BEQ Designer to compose a v3 PATCH payload. It also encapsulates the biquad format transform (b[]/a[] arrays to b0/b1/b2/a1/a2 dicts) server-side.
- **Accept BEQ Designer's native format**: The endpoint accepts filters in the format BEQ Designer produces (type/freq/gain/q with biquads as `{b: [], a: []}` arrays). ezBEQ transforms internally. This puts the format knowledge in one place.
- **`zeroconf` library for mDNS**: Pure Python, no system daemon required. Works on Linux (Docker/RPi), macOS, and Windows. Twisted has no built-in mDNS support.
- **mDNS opt-in via config**: `mdns: true` in ezbeq.yml, defaulting to `false` to avoid surprises on existing installs.

## Open Questions

### Resolved During Planning

- **Should we fix the dead `mv_adjust` param in `load_filter()`?**: No - the convenience endpoint handles mv separately via `set_gain()`. Fixing dead params is a separate cleanup.
- **Which API version namespace?**: v1 - it's where the existing filter/biquad endpoints live. No need for a new version.

### Deferred to Implementation

- Exact `ServiceInfo` TXT record content for mDNS (what metadata to advertise beyond path and port)
- Whether `zeroconf` thread shutdown needs special Twisted reactor integration or if the shutdown hook is sufficient

## Implementation Units

- [ ] **Unit 1: Load-profile API endpoint**

**Goal:** Single endpoint that accepts an auto-BEQ profile, loads biquad filters into a specified slot, sets master volume, and activates the slot.

**Requirements:** R2, R3, R4

**Dependencies:** None

**Files:**
- Modify: `ezbeq/apis/devices.py` - add `LoadProfile` resource and model on `v1_api`
- Modify: `ezbeq/device.py` - add `load_profile()` method on `DeviceRepository` that orchestrates load + gain + activate
- Test: `tests/test_load_profile_api.py`

**Approach:**
- Request model accepts: `slot` (string, default "1"), `masterVolume` (float, optional), `filters` (list of filter objects with `type`, `freq`, `gain`, `q`, `biquads`)
- Each filter's `biquads` field contains `{fs: {b: [b0,b1,b2], a: [a1,a2]}}` - the endpoint transforms to the `{b0,b1,b2,a1,a2}` format expected by `MinidspBeqCommandGenerator`
- `DeviceRepository.load_profile()` calls: (1) load biquads via existing command infrastructure, (2) set master gain if `masterVolume` provided, (3) activate the target slot
- Return the device state after all operations (same pattern as existing endpoints)

**Patterns to follow:**
- `ManageFilter` resource in `devices.py` for the endpoint structure
- `load_filter()` helper for error handling pattern (catch `InvalidRequestError` -> 400, `Exception` -> 500)
- `text_to_commands('bq', ...)` for biquad loading format

**Test scenarios:**
- Happy path: POST profile with 4 filters + mv_adjust -> verify biquad commands sent to device, master volume set, slot activated, response contains updated state
- Happy path: POST profile without mv_adjust -> verify filters loaded and slot activated, master volume unchanged
- Edge case: empty filters array -> verify slot still activated, no biquad commands sent
- Edge case: filters with different sample rates (96000 vs 48000) -> verify correct rate selected based on device descriptor
- Error path: unknown device name -> 404
- Error path: invalid slot id (e.g. "5") -> 400
- Error path: mv_adjust outside valid range (> 0 or < -127) -> 400
- Error path: malformed filter (missing biquads key) -> 400

**Verification:**
- All test scenarios pass
- Can manually POST a profile via curl and hear the filter take effect

- [ ] **Unit 2: mDNS service advertisement**

**Goal:** ezBEQ advertises itself via mDNS/Bonjour so clients can discover it on the local network without knowing the IP.

**Requirements:** R5

**Dependencies:** None (parallel with Unit 1)

**Files:**
- Modify: `pyproject.toml` - add `zeroconf` dependency
- Create: `ezbeq/mdns.py` - service registration and shutdown helpers
- Modify: `ezbeq/config.py` - add `is_mdns_enabled` property
- Modify: `ezbeq/main.py` - start mDNS after `endpoint.listen()`, shutdown hook before `reactor.run()`
- Test: `tests/test_mdns.py`

**Approach:**
- New `ezbeq/mdns.py` module with `register_service(port, name)` and `unregister()` functions wrapping `zeroconf.Zeroconf` and `ServiceInfo`
- Service type: `_ezbeq._tcp.local.` (custom type, more specific than generic `_http._tcp.local.`)
- Service name: derived from hostname, configurable via `mdns_name` in ezbeq.yml
- TXT record: `path=/api`, `version=<app_version>`
- Config property: `is_mdns_enabled` reading `config.get('mdns', False)`
- In `main.py`: conditionally start after `endpoint.listen(site)`, register shutdown via `reactor.addSystemEventTrigger('before', 'shutdown', ...)`

**Patterns to follow:**
- `is_access_logging` / `is_debug_logging` in `config.py` for the config property pattern
- `SafeSite` pattern in `main.py` for graceful error handling in infrastructure code

**Test scenarios:**
- Happy path: with mdns enabled, service is registered with correct port and service type
- Happy path: service info includes TXT records with path and version
- Happy path: on shutdown, service is unregistered and zeroconf is closed
- Edge case: mdns disabled in config -> no zeroconf instance created
- Error path: zeroconf registration fails (e.g. network unavailable) -> server still starts, warning logged
- Integration: a zeroconf browser on the same machine can discover the registered service

**Verification:**
- `dns-sd -B _ezbeq._tcp` (macOS) or `avahi-browse _ezbeq._tcp` (Linux) shows the service when enabled
- Server starts normally with `mdns: false` (default) - no zeroconf imported

## System-Wide Impact

- **API surface parity:** The new endpoint is additive - no existing endpoints change
- **Error propagation:** Follows existing pattern - `InvalidRequestError` -> 400, `Exception` -> 500, always return device state
- **State lifecycle:** Profile load uses the same `_hydrate_cache_broadcast` path as existing filter loads - no new state management
- **Unchanged invariants:** All existing v1/v2/v3 endpoints, WebSocket protocol, and catalogue behaviour are unchanged

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `zeroconf` library adds a new dependency | Pure Python, no native deps, widely used. Pin version in pyproject.toml |
| mDNS thread vs Twisted reactor interaction | Shutdown hook via `reactor.addSystemEventTrigger`. Test shutdown sequence explicitly |
| Biquad format transform correctness | Unit test with real BEQ Designer output against expected minidsp commands |

## Sources & References

- **Origin document:** beqdesigner `docs/brainstorms/2026-04-21-push-to-ezbeq-requirements.md`
- Related code: `ezbeq/apis/devices.py` (existing filter/biquad endpoints)
- Related code: `ezbeq/minidsp.py:MinidspBeqCommandGenerator` (biquad command generation)
- Related code: `ezbeq/main.py:create_app()` (namespace registration pattern)
