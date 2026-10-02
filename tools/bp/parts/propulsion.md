# Propulsion and powered consumers: geometry, ports, settings

Output: `propulsion.json`, 50 entries. Each is keyed by simulator type_id, or by prefab name for the five parts
the simulator lacks (`SC_GimbalThruster`, `SC_SmallDamper`, `SC_MediumDamper`, `SC_LargeDamper`,
`SC_DamagedLargeFuelThruster`).

Coordinates use the canonical frame of NOTES.md: orientation 16, footprint `[0,w)×[0,h)×[0,d)`, and the origin
at the footprint's min corner. A port's `cell` is the cell just outside the part. Its `face` is the footprint
cell it touches. Unlike the logic parts, these ports can sit on any of the six faces, so always use the explicit
`face`; model.py's `ports()` assumes z faces. Mirrored twin ("<prefab> M", `mirrored_hash`): apply x → w−1−x to
both `cell` and `face`, at the same orientation code. The exhaust and heat boxes reflect the same way.

## Results

| key | size | ports: cell (kind) | struct | corpus inst (normal/twin) | ports ok | overlaps | conf |
|---|---|---|---|---|---|---|---|
| small_electric_thruster | 8×16×8 | throttle (1,−1,0) d-in; power (0,−1,0) | SCThruster | 898 (451/447) | 2/2 | 0 | high |
| medium_electric_thruster | 16×24×16 | throttle (1,−1,0); power (0,−1,0) | SCThruster | 127 (65/62) | 2/2 | 0 | high |
| large_electric_thruster | 24×32×24 | throttle (1,−1,0); power (0,−1,0) | SCThruster | 0 | – | – | medium |
| electric_lift_thruster | 8×8×8 | throttle (1,−1,0); power (0,−1,0) | SCThruster | 955 (489/466) | 2/2 | 0 | high |
| bidirectional_maneuvering_thruster | 4×12×4 | force (4,6,0); power (4,5,0) | SCThruster | 0 | – | – | medium |
| small_maneuvering_thruster | 4×8×4 | throttle (4,2,0); power (4,1,0) | SCThruster | 257 (137/120) | 2/2 | 0 | high |
| medium_maneuvering_thruster | 4×12×4 | throttle (4,2,0); power (4,1,0) | SCThruster | 78 (50/28) | 2/2 | 0 | high |
| large_maneuvering_thruster | 8×16×4 | throttle (8,2,0); power (8,1,0) | SCThruster | 0 | – | – | medium |
| small_fuel_thruster | 8×16×8 | throttle (2,−1,0); **no power port** | SCThruster | 247 (124/123) | 1/1 | 0 | high |
| medium_fuel_thruster | 16×24×16 | throttle (2,−1,0); **no power port** | SCThruster | 57 (57/0) | 1/1 | 0 | high |
| large_fuel_thruster | 24×32×24 | throttle (2,−1,0); **no power port** | SCThruster | 0 | – | – | medium |
| small_solid_fuel_thruster | 8×32×8 | power (8,15,4) | SCThruster | 51 (42/9) | 1/1 | 0 | high |
| atmospheric_thruster | 8×8×16 | throttle (0,8,5); power (0,8,4) | SCThruster | 20 (11/9) | 2/2 | 0 | high |
| atmospheric_fan | 8×8×16 | speed (0,8,5); power (0,8,4) | SCThruster | 124 (67/57) | 2/2 | 0 | high |
| atmospheric_lift_fan | 8×8×8 | speed (1,−1,0); power (0,−1,0) | SCThruster | 324 (172/152) | 2/2 | 0 | high |
| ducted_fan | 48×8×48 (round) | speed (26,8,47); power (25,8,47); rotation (24,8,47) | SCThruster | 6 (3/3) | 3/3 | 6* | medium |
| ballast | 24×8×8 | buoyancy (5,0,−1); power (4,0,−1) | SpaceshipComponent | 12 (6/6) | 2/2 | 0 | high |
| rcs_controller | 4×2×4 | yaw (3,0,4); pitch (2,0,4); roll (1,0,4); power (0,0,4) | SCGimbalController | 206 (158/48) | 4/4 | 0 | high |
| floodlight | 4×4×4 | intensity (0,0,−1); horizontal (1,0,−1); vertical (2,0,−1); power (3,0,−1) | SpaceshipComponent | 41 (31/10) | 4/4 | 0 | high |
| rimcore_turbo | 16×16×20 | on (10,16,12); power (9,16,12) | SpaceshipComponent | 0 | – | – | medium |
| lava_sucker | 16×16×16 | on (12,12,16); length (12,11,16); power (12,10,16) | SpaceshipComponent | 0 | – | – | medium |
| extendable_damper | 8×8×8 | extension (6,6,8); power (5,6,8) | SpaceshipComponent | 6 (3/3) | 2/2 | 0 | high |
| pipe_electric_valve | 2×2×2 | open (0,2,1); power (1,2,1) | SpaceshipComponent | 2 (2/0) | 2/2 | 0 | high |
| nanopipe_electric_valve | 2×2×2 | open (0,2,1); power (1,2,1) | SpaceshipComponent | 0 | – | – | medium |
| small_gate / small_nanogate | 16×16×4 | state (15,0,−1); power (14,0,−1) | SpaceshipComponent | 27 (17/10) / 0 | 2/2 / – | 0 | high / medium |
| medium_gate / medium_nanogate | 24×24×4 | state (23,0,−1); power (22,0,−1) | SpaceshipComponent | 5 / 0 | 2/2 / – | 0 | high / medium |
| large_gate / large_nanogate | 48×32×4 | state (47,0,−1); power (46,0,−1) | SpaceshipComponent | 17 / 0 | 2/2 / – | 0 | high / medium |
| personnel_gate / personnel_nanogate | 8×16×4 | state (7,1,−1); power (7,0,−1) | SpaceshipComponent | 17 / 0 | 2/2 / – | 0 | high / medium |
| ramp_gate / ramp_nanogate | 32×28×4 | state (31,5,−1); power (31,4,−1) | SpaceshipComponent | 2 (1/1) / 0 | 2/2 / – | 0 | high / medium |
| radar | 4×2×4 | power (0,0,4) | SCRadar | 79 (29/50) | 1/1 | 0 | high |
| green_trench_pump | 16×16×16 | power (8,7,16) | SCGreenTrenchPump | 3 | 1/1 | 0 | high |
| ice_cream_freezer | 8×8×8 | power (8,0,0) | SpaceshipComponent | 0 | – | – | medium |
| outcast_polar_anchor | 16×24×16 | power (2,2,−1) | SCOutcastPolarAnchor | 2 (1/1) | 1/1 | 0 | high |
| solar_shield_generator | 8×8×8 | plasma (3,0,8); radius (4,0,8); max_heat (5,0,8) d-out | SpaceshipComponent | 0 | – | – | medium |
| wind_shield_generator | 8×8×8 | plasma (3,0,8); radius (4,0,8); max_wind (5,0,8) d-out | SpaceshipComponent | 5 (3/2) | 3/3 | 0 | high |
| small_plasma_generator | 8×8×8 | speed (1,0,8); power (0,0,8); plasma (2,0,8) | SpaceshipComponent | 5 | 3/3 | 0 | high |
| bomb_c4 | 8×2×4 | trigger (3,2,1) | SpaceshipComponent | 2 | 1/1 | 0 | high |
| tnt_box | – | – | – | – | – | – | none (not in game) |
| clima_bomb | 24×24×56 | trigger (−1,12,38) | SpaceshipComponent | 0 | – | – | medium |
| decoupler_small | 4×4×4 | trigger (4,0,3) | SpaceshipComponent | 444 (223/221) | 1/1 | 0 | high |
| SC_GimbalThruster (RCS Thruster) | 4×4×2 | none (wireless) | SCGimbalThruster | 1204 (820/384) | 0/0 | 0 | high |
| SC_SmallDamper / Medium / Large | 4×4×4 / 8×4×8 / 16×8×16 | none | SpaceshipComponent | 325 / 169 / 257 | 0/0 | 0 | high |
| SC_DamagedLargeFuelThruster | 24×32×24 | none | SCThruster | 0 | – | – | medium |

Unless marked, ports are data inputs. Power and plasma ports are undirected, so `dir` is "both".
\* ducted_fan: see "Irregular footprints".

Corpus totals: the corpus has 301 blueprints and 307,224 parts (corpus.py's set). The game saved two more during
the session; the final run used 303 and got identical results for these parts. 5,974 instances of these parts were
placed with the predicted geometry. Results:
- **6,755 cable hits** on predicted port cells: 3,563 data, 3,182 power and 10 plasma, all of the matching cable
  kind.
- **469 direct port-to-port contacts** with compatible ports.
- **0 overlaps**, except the ducted fan.
- **38 cable misses** in total:
  - 36 are cables in the ducted fan's empty bounding-box corners.
  - 1 is a legacy fuel thruster in the game's own MainMenuBlueprint.bp.
  - 1 is a radar in an autosave.

Twin instances hit their reflected ports 2,976 times: 1,528 data, 1,446 power and 2 plasma. Excluding the ducted fan
corners, they miss once (the radar autosave).

## Method

1. **Prefabs.**
   - `propulsion_dump.py` dumps the 108 relevant GameObjects from `globalgamemanagers.assets` into
     `propulsion_prefabs.json`, using the same method as `../prefab_dump.py`. The set includes every
     `"<prefab> M"` twin.
   - prefabs.json, and so prefab_dump.json, lacks 16 of these prefabs, although the game has them: the large
     thrusters, Bidirectional, RimcoreTurbo, LavaSucker, NanopipeElectricValve, the 5 nanogates,
     IceCreamFreezer, SolarShieldGenerator, ClimaBomb and DamagedLargeFuelThruster.
   - Two are absent from the game: SC_TNTBox and SC_ElectricGate.
2. **Field layout from the IL2CPP metadata** (`propulsion_meta.py`). typeDefinitions give
   fieldStart (+20), parentIndex (+12, matched against byvalTypeIndex +8) and nestedTypesStart (+36). Field
   definitions are header section 11, in 10-byte records.
   - The part component serializes `EPC_SpaceshipComponent`'s fields first, in this order:
     `_mirroredVersion` (PPtr), `_bounds`, `_mass`, `_oceanFloatingSetup`, `_maxTemperature`, `_colliders[]`,
     `_colliderAirResistant`, `_scGroup`, `_scSecondaryGroup`, `_availableAmount`, `_inventoryDependency`,
     `_boundsCollider`, `_defaultPaintableColor`, `_paintableRenderers[]`, `_collisionSoundMaterial`,
     `_soundObstacleMin`/`Max`, `_electricPorts[]`, ...
   - **size** = `_bounds` (bytes 12–23, metres) / 0.125.
   - **ports** = `_electricPorts`: u32 count, then 20-byte records `{float x,y,z; i32 face; i32 kind}`.
     - Position: the centre of the face cell, in the prefab frame (origin = part centre).
     - Face codes: 0 +x, 1 −x, 2 +y, 3 −y, 4 +z, 5 −z.
     - Kind codes: 0 data in, 1 data out, 2 power, 3 data both (wireless), 4 plasma.
   - A table is accepted only when it agrees with the `Port …` children's EPC_Renderer transforms: the same
     positions, and each euler rotation turning +z to the same face. The `Port Input Reverse Mode Button` child is
     a toggle, not a port.
   - The sequential parse of the base fields, `_defaultPaintableColor` at 76 + 12·n(colliders), lands exactly on
     the port table for 261 of 264 dumped prefabs. The three exceptions are the glass parts and the port frames,
     which use other layouts.
3. **Self-test.** The same decoder, run on the 43 logic parts, reproduces partdb.json exactly: every size, every
   port cell and direction, and the port order. The prefab frame axes are the canonical axes, and cell = (p + size/2)/0.125 − 0.5.
4. **Port names.** The table order is the game's port order. All 43 logic parts agree with Localization
   `SC_<Key>_Port0..N`; the Remapper's table lists I before X, although its hierarchy lists X first. That order
   matches the simulator's `order`. Independent check: corpus cables join Joystick3D port i to RCS Controller
   port i, (0,0) 189×, (1,1) 10× and (2,2) 58×, and never cross. So yaw/pitch/roll are x = 3/2/1.
5. **Corpus** (`propulsion_corpus.py`, the same file set and de-duplication as `corpus.py`). This loader also
   keeps the `_shape` byte of power and plasma cables, which corpus.py keeps only for data cables.
   - Instances are placed with the model.py rule: the stored cell is the min corner of the rotated footprint, and
     orientations come from orientations.json.
   - **Overlaps**: cables, plus every part with a known size, inside the predicted footprint.
   - **Cable check**: every cable cell next to the footprint that opens toward it (the networks.py open-face rule)
     must sit on a predicted port cell and be of the port's kind.
   - **Contacts**: port cell = the other part's face cell, and vice versa. All dumped parts' ports are decoded.
6. **Twins.** 46 of the 49 present prefabs have a `" M"` prefab. Each twin's own port table equals the x
   reflection of the normal table: 46/46.
   - prefabs.json lacks `mirrored_hash` for MediumFuelThruster, MediumGate, LargeGate, PersonnelGate,
     PipeElectricValve, GreenTrenchPump, SmallPlasmaGenerator and BombC4, but those twin prefabs exist.
   - The three dampers have no twin.
7. **Struct.** The metadata has exactly 48 classes with a nested `Blueprint` type, and they match the 48 named
   structs in schemas.json. The 49th, `?a0a17e9c56d75ad2`, is not among them, so it is presumably from an older
   build.
   - A class without its own Blueprint uses its nearest ancestor's. Every class here except
     `EPC_SCGimbalThruster` and `EPC_SCDamagedLargeFuelThruster` (both children of EPC_SCThruster) and
     `EPC_SCPipeElectricValve` (child of EPC_SCPipe) derives directly from EPC_SpaceshipComponent.
   - The corpus agrees for every part that has records. Gates, valves, ballast, floodlight, plasma generator, shield
     generator, bombs, decoupler and dampers all save the settings-free `EPC_SpaceshipComponent` struct.

## Settings (struct fields other than `_guid`/`_gt`)

- `_col` (all): the default is the prefab's `_defaultPaintableColor`, from 0xc8 = 200 to 0xc9 = 201. These are the
  unpainted finishes; 0 is used for some parts. It matches the corpus mode wherever users didn't repaint.
- `EPC_SCThruster._reverseButton` (byte 20, 1 B; the declared 4 B overlaps `_col`): the in-game **"Reversed Input"**
  toggle. Default 0. The corpus has 1 on about a third of small electric thrusters. The manual says to enable it on one
  thruster per axis when a pair shares one signed signal.
- `EPC_SCGimbalController` (RCS Controller): `_leverA`..`_leverF`, floats 0..1 with default 1.0 (prefab levers;
  the corpus mode is 1.0). `_toggle` defaults to 1 (206/206 in the corpus).
- `EPC_SCGimbalThruster._channel` (RCS Thruster): the mode knob, with 6 steps (`EPC_Actionable_Knob`
  roundingIntervals = 6). Saved values are (2k+1)/12, so mode k = floor(v·6). The prefab default is 0.0.
  - Corpus analysis: take each RCS thruster's torque (force +y local × offset from the ship's volume centroid),
    expressed in the frame of the blueprint's single pilot seat. The modes then pair up by axis:
    - modes 0/1: yaw, torque −y/+y (109/144 and 109/109)
    - modes 2/3: pitch, torque +x/−x (105/109 and 70/74)
    - modes 4/5: roll, torque +z/−z (96/109 each)
  - 89% of 654 thrusters are consistent. The grouping matches the controller's yaw/pitch/roll inputs and suggests
    levers A–F = modes 0–5 (unverified). The signs are tentative because the centroid stands in for the centre of
    mass. Reproduce with `propulsion_rcs_modes.py`.
- `EPC_SCRadar`: `_knob0Value` 0.0, `_knob1Value` 0.0 (its knob range is 0–360°, a heading), `_knob2Value` 0.4
  (prefab knobs). `_toggle` and `_mode` (Wall/Floor) are 1-byte bools; the corpus modes are 0 and 1.
- `EPC_SCGreenTrenchPump._toggle`: the corpus mode is 0. `EPC_SCOutcastPolarAnchor._leverValue`: prefab 0.0, with
  0.298 in its 2 corpus records.

## Game parameters

`propulsion_params.py` reads each class's own fields; the result is `game_params` in the JSON. They start 36 bytes
after the port table. The thruster tail is read back from the record end because of a variable-length array.
Checks:
- Field-less classes end exactly at the computed start.
- Fixed-size parses end exactly at the record length.
- Each force vector points opposite the exhaust direction.
- Atmospheric parts have zero efficiency in space.
- Fuel thrusters have 0 P/s, which agrees with their missing power port.

Power use, in P/s (the simulator's `params.power_ps` placeholders are 10):

| part | P/s | part | P/s |
|---|---|---|---|
| small/medium/large electric thruster | 15 / 60 / 160 | small/medium/large maneuvering | 5 / 17 / 50 |
| electric lift (flat) thruster | 11 | bidirectional maneuvering | 15 |
| atmospheric thruster / fan / flat fan | 11 / 8 / 4 | ducted fan | 60 |
| fuel thrusters (fuel/s: 0.85 / 2.5 / 7.5) | 0 | solid fuel: ignition power 200, time 1000 | 0 |
| RCS controller | 4 | RCS thruster | 5 (battery 700) |
| ballast | 30 | floodlight | 4 |
| rimcore turbo | 300 | lava sucker | 80 |
| extendable damper | 20 | pipe / nanopipe valve | 2.5 |
| small / medium / large gate (and nanogates) | 5 / 8 / 10 | personnel / ramp gate | 5 / 12 |
| radar | 2 | green trench pump | 90 |
| ice cream freezer (idle) | 1 | outcast polar anchor | 40 |
| small plasma generator (max) | 100 | | |

`max_force` holds the thrust vector in canonical axes, e.g. the small electric thruster's (0, −330000, 0). Also
decoded:
- efficiencies (space, atmosphere, water)
- acceleration time
- `force_type`, which is 1 for the maneuvering and RCS thrusters (rotation-only, per their descriptions)
- shield radius range, 1–50

These are the raw serialized numbers. Check one tooltip in-game before relying on the units.

## Exhaust and moving parts (keep clear)

`exhaust.dir` is the jet direction, taken from EPC_ThrusterBlow and EPC_Heat; the force on the ship is the
opposite. `heat_zones` and `blow_zone` are inclusive cell boxes in the canonical frame, mostly outside the
footprint. Components inside a heat zone burn (manual, "Heat From Thrusters").
- **+y exhaust**: electric, fuel and lift thrusters, and the flat fan. Their ports are on the bottom face.
- **−y exhaust**: the maneuvering, solid-fuel and RCS thrusters.
- **−z exhaust**: the atmospheric thruster and fan.
- **Ducted fan**: −y at rotation 0.
- **Bidirectional maneuvering thruster**: both ±y.

Moving parts:
- The extendable damper's leg leaves the bottom face, by up to 1.5 m (12 cells).
- The ramp gate's ramp swings out.
- The ducted fan tilts.
- The floodlight head rotates.
- The lava sucker's intake pipe extends.

## Irregular footprints

- **Ducted fan.** The 48×8×48 box is the `_bounds` of a round 6 m duct.
  - In all 6 corpus instances (3 blueprints, one design), frames and cables sit in the box's empty corners: z 44–47,
    x 0–12 and 35–47. That gives the 6 overlaps and 36 cable "misses".
  - All 3 ports hit in all 6 instances.
  - The JointsArea mount strip is the +z face, x 16–31.
  - Use the box as a safe over-approximation. The exact occupied cells are unknown; the collider is a mesh.
- **Other thrusters.** Their colliders are convex meshes too, so their box corners may also be free, but nothing in
  the corpus sits there. The box is safe.

## Disagreements with the simulator or shared files

- **Fuel thrusters have no power port.** The simulator models one, and Localization still has
  `SC_*FuelThruster_Port1 "Requires {0} P/s"`.
  - The prefab table has only the input.
  - There is not a single power cable at any of 304 corpus fuel thrusters, apart from one in MainMenuBlueprint.bp.
    That one sits on today's data-port cell, so it is an older layout.
  - The JSON lists `"absent_ports": ["power"]`, and `_powerConsumptionPerSec` is 0.
- Plasma ports are undirected in the game (kind 4). The simulator's plin/plout distinction exists only in the
  simulator.
- `tnt_box`: no SC_TNTBox prefab in this build. Its Localization text is a demo leftover. The entry has hash null.
- prefabs.json is missing 16 present prefabs and 8 twin hashes (see Method 1 and 6).

## Open questions

1. Prefab-only parts are marked medium; they have no corpus instances. The same decoder is exact on every part that
   has instances, but each still deserves one in-game load test. The parts:
   - large electric, bidirectional, large maneuvering and large fuel thrusters
   - rimcore turbo, lava sucker, nanopipe valve
   - the 5 nanogates
   - ice cream freezer, solar shield generator, clima bomb, damaged large fuel thruster
2. The signs within each RCS mode pair, and whether controller levers A–F map to modes 0–5 (see Settings).
3. The exact semantics of `_reverseButton` (the "Reversed Input" sign handling) and the radar knob meanings.
4. The ducted fan's true occupied cells.
5. P/s units are confirmed only by consistency (see "Game parameters").

## Reproduce

```
set PYTHONUTF8=1
python tools/bp/parts/propulsion_dump.py        # game assets -> propulsion_prefabs.json (read-only on the game)
python tools/bp/parts/propulsion_meta.py        # class tree, Blueprint structs, field names (IL2CPP metadata)
python tools/bp/parts/propulsion_geom.py        # decoded size/ports/paint for every dumped prefab
python tools/bp/parts/propulsion_params.py      # P/s, forces, etc.
python tools/bp/parts/validate_propulsion.py    # self-test + corpus check -> propulsion.json
python tools/bp/parts/propulsion_rcs_modes.py   # RCS mode knob vs torque axis (Settings)
```
Helpers: `propulsion_place.py` (placement, cable open faces) and `propulsion_corpus.py` (corpus loader; set
`AU_BP_CACHE=<dir>` to cache it).
