# Fork changes

Current fork version: **`1.0.5b10+hood.7`** (upstream baseline `1.0.5b10`, PEP-440
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
enum directly, mapping the kelvin range onto raw values 1..5
(warm..cold, inverted axis). The 0 = "custom" slot is read-only fallback
(slider reports None when the appliance reports it).

The parallel `select_hood_color_temperature` from change #3 is removed —
the slider covers the same endpoint with the same semantics. The
translations entry for it is gone too.

Supersedes the slider half of change #2: `ColorTemperaturePercent` is no
longer referenced by the integration. The light entity's resilience
fixes (per-payload retry, None-tolerant state getters, always-on-write)
are still in place from #2 / #9 / #10.

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
