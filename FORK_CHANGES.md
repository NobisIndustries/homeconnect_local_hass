# Fork changes

Current fork version: **`1.0.5b10+hood.12`** (upstream baseline `1.0.5b10`, PEP-440
local-version `+hood.N`). Bump `hood.N` whenever fork changes ship.

Living catalogue of why this fork diverges from upstream
[chris-mc1/homeconnect_local_hass](https://github.com/chris-mc1/homeconnect_local_hass)
and what was changed. Append new entries at the bottom as work continues.

## Intent

Upstream supports Bosch/Siemens Home Connect appliances generically. Hood support is
shallow — only ambient light, basic power, and a few config sensors work end-to-end.
This fork's primary goal is to make a Bosch DWK91LT65 (and similar hoods) actually
controllable from Home Assistant: main light with brightness + color temperature, fan
speeds (3 normal + 2 intensive), program selection, and filter-saturation reset.

Changes are kept hood-scoped where possible so other appliance classes aren't affected.

## How the integration works (quick reference)

- Profiles are downloaded with the Home Connect Profile Downloader (openHAB target);
  the integration parses `*_DeviceDescription.xml` + `*_FeatureMapping.xml` via the
  `homeconnect_websocket` package into typed `Entity` / `Setting` / `Status` /
  `Command` / `Program` objects on a `HomeAppliance`.
- Each platform (`switch`, `light`, `fan`, `number`, `select`, `button`, `sensor`,
  `binary_sensor`) is declared by entity descriptions in
  `custom_components/homeconnect_ws/entity_descriptions/`. A descriptor references one
  or more `Entity` *names*; if all referenced entities exist in the parsed profile, an
  HA entity is created.
- Writes go over the WebSocket as `POST /ro/values` (entity value writes),
  `POST /ro/selectedProgram` (program select), or `POST /ro/activeProgram` (program
  start). The appliance can return `400 BadRequest` for many semantic reasons
  (unavailable, busy, options inconsistent, etc.).

## Changes

### 1. Hood filter reset buttons appear (and grease "dirtyness" reset works)

**Files:** `entity_descriptions/cooking.py`

The four `Cooking.Common.Command.Hood.*FilterReset` descriptor entries had
**trailing spaces** in their entity names (e.g.
`"Cooking.Common.Command.Hood.GreaseFilterReset "`), so they never matched the parsed
entity name and the buttons were silently dropped. Stripped the trailing spaces.
Translations and `services.yaml` were already in place, so the buttons now surface
with their existing names.

### 2. Hood main light: keep COLOR_TEMP mode and tolerate per-attribute rejection

**Files:** `entity_descriptions/cooking.py`, `light.py`

Upstream gated COLOR_TEMP mode on `ColorTemperaturePercent` being *present* in the
profile. For the DWK91LT65 the entity exists but the device reports
`available="false"`; despite that, the physical light supports color-temp adjustment
and the API often accepts the write. So:

- `generate_hood_light` still picks COLOR_TEMP mode when the entity is present;
  the `available=false` flag is treated as advisory, not authoritative.
- `light.async_turn_on` now bundles all writes into one `/ro/values` POST as before,
  but on `CodeResponsError` (4xx from the appliance) **retries without the
  color-temperature payload**. The light's on-state and brightness write still take
  effect — without the retry, HA was rolling back the optimistic on-state because
  the whole POST failed, producing the "switch flips back off" behaviour.

The retry is conservative: it only strips the color-temp payload, and only if it was
present.

### 3. Parallel ColorTemperature select for the hood light

**Files:** `entity_descriptions/cooking.py`, `translations/en.json`

Added a `select_hood_color_temperature` entity backed by
`Cooking.Hood.Setting.ColorTemperature` (enum custom/warm/warmToNeutral/neutral/
neutralToCold/cold). This is the documented-as-available control on the profile and
works even when the percent endpoint rejects writes. Users get both the slider on the
Light entity and this discrete select.

### 4. Per-program start buttons for hoods

**Files:** `entity_descriptions/cooking.py`, `button.py`,
`entity_descriptions/descriptions_definitions.py`, `entity_descriptions/common.py`,
`translations/en.json`

All Hood programs (`Automatic`, `Venting`, `Interval`, `DelayedShutOff`) are declared
as `execution="startOnly"` in the DeviceDescription. The generic "Selected Program"
select issues a `start()` that injects all the program's read-write options at their
current shadow value, which the appliance frequently rejects with a `400`.

Approach:

- New optional fields on `HCButtonEntityDescription`: `program` (program entity name)
  and `program_options` (explicit option dict). When `program` is set, `HCButton.press()`
  calls `program.start(options=program_options or {}, override_options=True)` —
  bypassing the shadow-fill in `_build_options`.
- Added four hood program buttons keyed off the program names. Translations added.
- The generic "Selected Program" select is now `entity_registry_enabled_default=False`
  for `appliance.info["type"] == "Hood"` so it stops cluttering the UI by default,
  while remaining available for power users.

### 5. Hood fan = program-start semantics (Off + 5 speeds + Auto preset)

**Files:** `fan.py`, `entity_descriptions/cooking.py`,
`entity_descriptions/descriptions_definitions.py`

Upstream `HCFan` writes `Cooking.Common.Option.Hood.VentingLevel` and
`Cooking.Common.Option.Hood.IntensiveLevel` directly. On Bosch hoods these option
writes alone are no-ops; the fan only runs when the `Cooking.Common.Program.Hood.Venting`
program is *started* with the level as an option. That's why upstream's hood fan
didn't toggle or change speed.

New `HCHoodFan` class (kept side-by-side with `HCFan`; selection is by whether the
fan descriptor has a `venting_program`):

- Speed count derived from the union of `VentingLevel` and `IntensiveLevel` enum
  values (excluding 0). For DWK91LT65: VentingLevel has Stage01..05; IntensiveLevel
  has only `IntensiveStageOff` so all 5 speeds come from VentingLevel.
  Other hoods that split 3 normal + 2 intensive across the two options also get a
  combined 5-speed mapping.
- `async_set_percentage` / `async_turn_on` start the Venting program with the
  chosen option set explicitly (`override_options=True`).
- `async_turn_off` starts Venting with VentingLevel=0.
- `auto` preset (when `Cooking.Common.Program.Hood.Automatic` exists) starts the
  Automatic program.
- State is read from `appliance.active_program` + the option entities' current
  values; the entity subscribes to `BSH.Common.Root.ActiveProgram` updates so HA
  reflects external state changes.

`HCFan` is untouched — non-hood fan entities (if any) continue to use the old
option-write path.

### 6. Section-E extras for the hood

**Files:** `entity_descriptions/cooking.py`, `translations/en.json`

Added entities for settings/sensors that exist in the DWK91LT65 profile but weren't
exposed. All hood-only (gated by the entity names existing in the profile), most
under `EntityCategory.CONFIG`:

- Sensor: `Cooking.Hood.Status.RegenerativeCarbonFilterSaturation`
- Switch: `Cooking.Hood.Setting.IntervalTotalExecutionTimeLimitation`
- Number: `Cooking.Hood.Setting.IntervalTotalExecutionTime`
- Selects: `VentilationProfileOperating`, `VentilationStartupSetting`,
  `VentilationShutdownSetting`, `WorkingLightStartupSetting`,
  `WorkingLightShutdownSetting`, `MoodlightStartupSetting`,
  `MoodlightShutdownSetting`, `FilterSaturationNotificationInterval`,
  `BSH.Common.Setting.Favorite.001/002.Functionality` (disabled by default)

### 7. Lights no longer go unavailable on entity-level availability flips

**Files:** `light.py`

Both the hood main light and the ambient light went `unavailable` whenever any
of their backing entities reported `available=false`. On Bosch hoods this
happens routinely:

- The main light's `Cooking.Hood.Setting.ColorTemperaturePercent` is marked
  `available=false` in the DDF (despite the physical light supporting color temp).
- The primary `Cooking.Common.Setting.Lighting` itself gets flipped
  `available=false` by the appliance (e.g. when PowerState=Off), even though
  writing it back to `On` is what we want to do in the first place.
- Turning the ambient light off flips `AmbientLightBrightness` /
  `AmbientLightCustomColor` to `available=false`, dragging the parent light
  offline.

`HCLight.available` now only gates on session connectivity — neither the primary
nor the secondary entities' `available` flags can take the light offline. Write
failures are still handled gracefully by `async_turn_on`'s per-payload retry from
change #2.

### 8. Hood fan on/off uses PowerState

**Files:** `fan.py`

The HA fan toggle was a no-op because starting `Hood.Venting` with `VentingLevel=0`
doesn't actually power down a Bosch hood (the appliance stays in standby waiting
for the program). The user's working Power switch already writes
`BSH.Common.Setting.PowerState` — the fan now does the same:

- `async_turn_on`: writes `PowerState=On` first (no-op if already on), then sets
  speed / preset.
- `async_turn_off`: writes `PowerState=Off` (falls back to Venting level 0 only on
  appliances where PowerState isn't a 2-state on/off mapping).
- `is_on` consults PowerState — when off, the fan reports off regardless of any
  lingering program state.

PowerState mapping resolution mirrors `common.generate_power_switch`
(`POWER_SWITCH_VALUE_MAPINGS` precedence: `On/MainsOff`, `Standby/MainsOff`,
`On/Off`, `On/Standby`, `Standby/Off`). For DWK91LT65 this resolves to `On/Off`.

### 9. Hood light turn-on always writes the on-payload

**Files:** `light.py`

`HCLight.async_turn_on` was guarding the `Cooking.Common.Setting.Lighting`
write with `if self._entity.value is not True`. On Bosch hoods the cached
value of `Lighting` doesn't reliably track the physical light state — the
appliance reports `True` even when the light is off. With no kwargs (plain
toggle), the brightness/color-temp blocks are skipped too, so the guard
turned the whole POST into an empty `data=[]`, which the appliance rejects
with `400 BadRequest`. Now we always include the on-write payload; writing
`True` to an already-on light is a no-op on the appliance.

### 10. Hood light state properties tolerate value=None

**Files:** `light.py`

`color_temp_kelvin`, `brightness`, and `rgb_color` all dereferenced backing
entity values without checking for `None`. `ColorTemperaturePercent` on
Bosch hoods is flagged `available=false` with `value=None`, which made
`color_temp_kelvin` raise `TypeError` from inside
`LightEntity.state_attributes`. HA caught the exception, rolled back the
optimistic on-state, and the UI reverted the light to "off" — making the
turn-on look broken even when the write succeeded. All three getters now
short-circuit to `None` when the underlying value is `None`.

### 11. Hood light color-temp slider drives the ColorTemperature enum

**Files:** `light.py`, `entity_descriptions/cooking.py`, `translations/en.json`

The slider used to write `Cooking.Hood.Setting.ColorTemperaturePercent`.
Bosch firmware rejects that endpoint regardless of mode (we also tried
bundling a `ColorTemperature=0`/custom pre-write — still 400). Switched
the slider to drive the discrete `Cooking.Hood.Setting.ColorTemperature`
enum directly. The slider's min/max are restricted to the enum's
actual range (2700 K..6000 K) and each enum step has a hardcoded
kelvin anchor — read picks the anchor for the current raw value,
write picks the raw whose anchor is closest to the requested kelvin.
Earlier attempts to derive the mapping via `scale_ranged_value_to_int_range`
kept landing one step short at the endpoints (warm→neutralToCold
instead of warm→cold) because of int-truncation + source-range
off-by-one. With explicit anchors there's no scaling math at all.

| raw | enum value     | kelvin anchor |
| --- | -------------- | ------------- |
| 1   | warm           | 2700 K        |
| 2   | warmToNeutral  | 3525 K        |
| 3   | neutral        | 4350 K        |
| 4   | neutralToCold  | 5175 K        |
| 5   | cold           | 6000 K        |

The 0 = "custom" slot maps to `None` on read (slider hides itself).

The parallel `select_hood_color_temperature` from change #3 is kept as
a backup control — slider and select drive the same enum, just with
different UX.

Supersedes the slider half of change #2: `ColorTemperaturePercent` is no
longer referenced by the integration. The light entity's resilience
fixes (per-payload retry, None-tolerant state getters, always-on-write)
are still in place from #2 / #9 / #10.

### 12. Reconfigure flow to change Appliance Host/IP (+ Python-3 except fix)

**Files:** `config_flow.py`, `translations/en.json`, `translations/de.json`

Upstream offered no way to edit an Appliance's Host/IP after initial setup. The
host lives in `config_entry.data[CONF_HOST]` and was only settable via the
first-run manual host step (shown *only on connection failure*) or via zeroconf
auto-update — and zeroconf is gated on `CONF_MANUAL_HOST == False`, so a manually
entered IP is never auto-corrected. A device whose DHCP lease changes (e.g. the
dishwasher) becomes permanently unreachable with no UI remedy.

- Added `async_step_reconfigure`, surfacing HA's standard "Reconfigure" button on
  the integration's entry page. It seeds `self.data` from the existing entry
  (profile, encryption keys, device id are reused — no zip re-upload), shows the
  host form pre-filled with the current host, then reuses `async_step_test_connection`
  to validate the new address before committing.
- On success it writes only `{CONF_HOST, CONF_MANUAL_HOST: True}` via
  `async_update_reload_and_abort` (pins the host so zeroconf won't overwrite it).
  On connection failure it re-shows the `reconfigure` step with `cannot_connect`
  rather than falling into the add-flow `host` step.
- `self.data` is seeded from the entry only on first entry (`reconfigure_entry is
  None`) so a typed-but-failed host survives the retry round-trip.
- Translations: `reconfigure` step + `reconfigure_successful` abort (en + de).

While here, fixed a **pre-existing Python-2-ism**: two `except KeyError, ValueError:`
clauses (in `async_step_upload` and `async_step_set_data`) are a `SyntaxError` under
Python 3 and made the entire `config_flow` module unimportable. Parenthesized to
`except (KeyError, ValueError):`. Other language files (fr/it/nl/no/ru/sv) don't
yet have the `reconfigure` strings — they fall back to English.

Also (pre-existing, surfaced during reconfigure testing): a failed connection in
`async_step_test_connection` raised an **uncaught** `homeconnect_websocket`
`ConnectionFailedError`, bubbling up as an unhandled aiohttp 500 instead of
re-showing the form with `cannot_connect`. The `except` list only handled aiohttp/
binascii/timeout errors; `homeconnect_websocket` 1.5.x wraps connect failures in its
own `HCConnectionError` (parent of `ConnectionFailedError`). Added `HCConnectionError`
to the `cannot_connect` branch — this fixes the normal setup flow too, not just
reconfigure.

### 13. Hood fan state gated on OperationState (firmware DDF 6-4 regression)

**Files:** `fan.py`

After a BSH firmware update (DDF version 4-4 -> 6-4, swVersion 5.19.0.11) the main
fan control stopped working in HA while lights and power kept working. Diagnosed by
connecting directly to the appliance and replaying the writes.

**Root cause:** the new firmware *latches* `BSH.Common.Root.ActiveProgram` and
`Cooking.Common.Option.Hood.VentingLevel` across power-off. With the hood switched
off, the appliance still reports:

```
PowerState='Off'  OperationState='Inactive'
ActiveProgram=55307 (Cooking.Common.Program.Hood.Venting)  VentingLevel='FanStage05'
```

On DDF 4-4 these cleared when the program ended. `is_on`/`percentage` read them as
truth, so as soon as the hood was powered on, the fan entity reported **on at 100%**
even though nothing was running. HA does not dispatch `async_turn_on` (or a
percentage change to a value it thinks is already set) on an entity it already
believes is in that state, so the toggle and the speed slider became no-ops.

**Not the cause** (ruled out by direct testing against the appliance):

- The protocol still works. `POST /ro/activeProgram` with
  `{program: 55307, options: [{55308: <level>}, {55305: 0}]}` is accepted and the fan
  physically changes speed. Both `override_options=True` and `False` work.
- `validate="true"`, newly added to `activeProgram`/`selectedProgram` in the DDF, is
  parsed by `homeconnect_websocket` but never acted on, and does not reject the
  partial option set `_start_venting` sends.
- Enum types were renumbered (`0203`->`1018`, `0204`->`1019`, `1000`->`101A`, plus
  `1016`/`1017`) but these are legitimate `subsetOf` declarations in the DDF's
  `enumerationTypeList` and resolve correctly; `PowerState` still yields `On`/`Off`
  and `_resolve_power_mapping` still returns `('On', 'Off')`.
- No UID was reused or renumbered. Profile changes are limited to
  `SensorSensitivity` -> `AutomaticSensitivity`, the removal of
  `RegenerativeCarbonFilterLifeTimeReset`, and `ProgramProgress` dropping out of
  Venting's option list.

**Fix:** `BSH.Common.Status.OperationState` is the only entity that distinguishes
"venting is running" from "venting was the last program". `HCHoodFan` now tracks it
(`_is_program_running`, running = `Run`/`DelayedStart`/`Pause`/`ActionRequired`) and:

- `is_on` returns `False` unless power is *known* on (`_is_powered_on is not True`
  now short-circuits, so an unknown power state no longer reports the fan as on) and
  OperationState doesn't say idle.
- `percentage` returns 0 instead of echoing the latched `VentingLevel`.
- `preset_mode` returns `None` instead of a stale `auto`.

When `OperationState` isn't exposed, `_is_program_running` returns `None` and the old
ActiveProgram/level behaviour is kept as a fallback.

**Device limitation confirmed:** while venting runs, the hood *accepts but ignores*
every attempt to stop it short of cutting power — starting Venting with
`VentingLevel=0`, writing `VentingLevel=0` to `/ro/values`, and POSTing program `0`
to `/ro/activeProgram` all return `RESPONSE` with the fan still physically running.
`async_turn_off` writing `PowerState=Off` (change #8) therefore remains the only
option. This is acceptable on this appliance: `PowerState` only affects venting,
the hood lights are unaffected and stay on. Also observed: the hood briefly applies the program's declared
`default="2"` before settling to the requested level.

## Open items / not yet done

- No automated tests for the new hood fan / program buttons (HA dev deps don't all
  install cleanly on Windows). Add coverage when convenient.
- The `HCButtonEntityDescription.program_options` field is typed
  `dict[str, Any]` but `Program.start()` actually expects `dict[int, ...]` (option
  uid → value). The current code only passes `{}`, so the mismatch is harmless;
  tighten the type if/when we pass real options.
- Other Bosch/Siemens hood models may have `IntensiveLevel` populated with real
  Stage04/Stage05 values — the new `HCHoodFan` mapping handles that already, but it
  hasn't been verified against a profile that uses the split.
- Fan speed-down while venting runs is not possible on DDF 6-4 (see #12); the
  appliance ignores level-lowering writes. Only raising the level and powering off
  were verified to take effect. Lowering speed therefore requires a power cycle.
