# Sensor parts: geometry, ports, settings (`sensors.json`)

Status 2026-10-02. **27 entries**: the 24 simulator sensor types, plus 3 sensor-like prefabs the simulator lacks
(`SC_PipeMeter`, `SC_NanopipeMeter`, `SC_BaobaraInterferencemeter`). Confidence: 19 high, 7 medium, 1 low
(`rotometer`, which has no prefab in this build).

## Reproduce
```
set PYTHONUTF8=1
python tools/bp/parts/sensors_dump.py       # once: dumps twins + extra prefabs -> sensors_prefabs.json (reads game assets)
python tools/bp/parts/validate_sensors.py   # derives + validates -> sensors.json, report on stdout
python tools/bp/parts/sensormodel.py        # self-check of the generator helper (1,248 placements)
```

| file | role |
|---|---|
| `sensors_dump.py` → `sensors_prefabs.json` | the mirrored twins (`"<prefab> M"`), `SC_Thermoscan`, `SC_RedTank`, `SC_NanopipeMeter`, `SC_BaobaraInterferencemeter` and 10 reference logic prefabs, same format as `prefab_dump.json` plus object path ids |
| `sensorlib.py` | prefab parsing (size field, baked port list, port renderers, joint areas), placement, corpus loader (keeps GUIDs, struct hashes and the shape of all three cable types), per-placement checks, cable networks, IL2CPP struct resolution |
| `validate_sensors.py` | builds every entry and validates it on the corpus; writes `sensors.json` after every part (atomic replace) |
| `sensormodel.py` | **generator-facing**, reads only `sensors.json`: `BY_HASH`, `footprint(key, origin, k)`, `ports(key, origin, k, mirrored)` (same shape as `model.ports`), `settings_bytes(key, **overrides)` |

The corpus cache is `%TEMP%\au_bp_sensors_corpus1.pkl`. Delete it when blueprints are added.

## Entry format (beyond the requested fields)
- `description`: the game's English description (Localization `SC_<Key>_Desc`), which states mounting
  requirements such as "must be mounted outside the ship" or "no obstacles in front of the component".
- `ports.<name>`: `cell`, `face`, `dir`, `kind`, plus `index` (the game's port number = Localization
  `SC_<Key>_Port<index>`) and `node` (the prefab child, e.g. `Port Y`).
- `struct` is the `schemas.json` key, with `struct_hash`. `class` is the prefab's EPC class.
- `settings.<field>`: `default` and `meaning`, plus `offset`, `type` and `size` (the true type and width, from the
  Burst PDB) and `declared_size` (what the .bp schema declares). **Write `size` bytes, not `declared_size`**: a bool
  declared as 4 B is followed by `_col` one byte later. `sensormodel.settings_bytes()` does this.
- `joint_faces`: the prefab's `JointsArea*` polygons as face rectangles (`normal`, inclusive `from`/`to` face
  cells, `pipe` = a fuel-pipe joint). These are probably the faces that can join neighbours. **Not
  corpus-validated.** For a twin, reflect x.
- `corpus`: `instances` counts all records, normal plus twin, across the 301 de-duplicated blueprints, so it
  includes many versions of the same ship. `unique_placements` counts distinct (GUID, cell, orientation).
  `ports_confirmed` is k/m ports with at least one hit. Also `port_hits` (cable or direct contact, once per
  placement and port), `cable_hits`/`cable_misses` by cable kind, `direct_contacts`, `twin_port_hits`,
  `network_partners` (the direction of whatever the port is cabled to), `direction_conflicts`, and `orientations`.
- `rotometer` has `substitute: "axis_rotometer"`.

## Method

### 1. Footprint = the size field, centred
Every part's main component (`EPC_SC<Class>` MonoBehaviour body) holds three floats at bytes 12..23: the part size
in metres (÷ 0.125 = cells). The footprint box is centred on the prefab origin, so a prefab point `p` lies in
canonical cell `floor((p + size/2) / 0.125)`. The axes are Unity's (x right, y up, z forward), with no flip.
- This holds for **all 43 logic parts**: the size and every port cell equal `partdb.json`, and 5 twin prefabs match
  too (48 of 48).
- The joint-area polygons and colliders do **not** give the footprint. The tanks show it: the Blue Tank's joint
  areas span only 20 of its 32 cells in y. See the tanks section.

### 2. Ports = the port list baked into the main component
After the base-class fields the body holds `u32 n` and then `n × {f32 pos[3]; i32 facing; i32 type}`:
- `pos` is the face-cell centre in prefab metres.
- `facing` is 0..5 = +x, −x, +y, −y, +z, −z.
- `type` is 0 = data in, 1 = data out, 2 = power.

The list sits at offset 136 on most sensors and 160 on the Condition; `baked_ports()` searches for it.

It is cross-checked against the `Port …` child renderers. Each sits at the same position; its local +z, rotated by
its Euler angles (Unity order Z, X, Y), gives the same facing; and its mesh id gives the same kind (0x192b data
out, 0x16df data in, 0x161f power). **Both sources agree on every part.** The port cell is the face cell plus the
facing.

### 3. Port names = baked order
Baked entry *i* is game port *i*. That is Localization `SC_<Key>_Port<i>`, which is the simulator's
`TYPES[type].order[i]` (engine.js builds `order` from the Localization order).
- **Checked on all 43 logic parts.** Baked entry *i*, named by the simulator's order, lands on `partdb.json`'s cell
  for that name, including the multi-input Condition (a, b, true, false), Data Redirector 3, Accumulator, Memory
  and Atan2.
- The script also checks that each port's game type (in / out / power) matches the simulator's
  inputs / outputs / power lists.
- **Watch out:** the order is not node-name order. On the Fuel Analyzer, `performance` is node `Port Y` and
  `stability` is node `Port X`. On the Space GPS, `distance`, `longitude` and `latitude` sit at x = 3, 2, 1.

### 4. Mirrored twins
`sensors_dump.py` dumps every twin prefab. Each twin's baked ports equal the normal ones reflected along local x
(dx → w−1−dx, with the x part of the facing negated). The script asserts this for all 24 twins that exist.

In the corpus, twin placements hit only the reflected ports (`twin_port_hits`), with no misses.

`SC_PipeMeter` and `SC_NanopipeMeter` have no twin prefab (`mirrored_hash: null`). Twins exist for Aerometer,
Axis Rotometer, Inclinometer, Thermoscan and Red Tank even though `prefabs.json` omits them; their hashes come
from `hashes.part_hash(prefab, True)`.

### 5. Settings struct
The struct is the nearest class in the IL2CPP inheritance chain that declares a nested `Blueprint` type (read from
the v39 typedef records: name, then u16 byval / declaring / parent type indices).
- This agrees with the corpus struct hash for **196 of 196** corpus-backed prefabs.
- That includes 5 subclasses that inherit a non-base struct: FramePipe and FrameWithPorts use Frame's,
  ZoomCamera and RotationalTelescope use Camera's.
- So `EPC_SCCryotank` (Red Tank) saves with `EPC_SCTank+Blueprint+BlueprintData`. Its `InitializeEntity` also
  calls `EPC_SCTank.InitializeEntity` first.
- Every corpus record of every sensor uses the predicted struct (`struct_confirmed`).

### 6. Settings values
- Field types and offsets come from the Burst PDB.
- Defaults are each prefab actionable's initial value: dword 19 of `EPC_Actionable_Toggle` is the initial state
  (the Data Hub's channel-1 toggle is 1 and the other four 0; a Switch is 0), and dword 0 of
  `EPC_Actionable_Knob` is the knob default.
- Two mode bits were decoded from the Burst code (`burst.asm`):
  - **Velocity Meter `_modeButton`.** `SCTick_VelocityMeter.OwnJob.Execute` reads the mode toggle. Below 0.5 it
    outputs `sqrt(vx²+vy²+vz²)`, which is **0 = Overall Mode**. Otherwise it outputs v · (the part's rotated
    +z), which is **1 = Directional Mode** (signed). The output is also smoothed:
    `out += (new − out) × 0.1535` per tick, clamped to ±1e20.
  - **Fuel Analyzer `_mode`.** `SCTick_FuelAnalyzer.OwnJob` reads the mode toggle. Below 0.5 the input is the
    knob entity, which is **0 = "Input: Knob"**. Otherwise it is the data port clamped to 0..1, which is
    **1 = "Input: Data Port"**. A generator that wires `value` must set `_mode = 1`.
- Gyro-Line: `_degrees` is the display range byte (40 / 60 / 90 / 180; default 40). `_rotKnobValue` is the
  orientation knob (corpus 0, 0.25, 0.75). `_toggle` is the on switch (default 1).
- Tank `_actionableValue` is the valve opening (0 closed … 1 open; `EPC_Actionable_Valve` off/on rotations). Its
  in-game initial value is not stored in the prefab, so **1.0 is a chosen default**. The corpus has blue 0.90–1.00
  and green ≈0.10, the 90/10 mix the manual recommends.

### 7. Corpus validation (`check_instance`, per unique placement)
- (a) **Overlaps.** Counts cable cells, logic-part cells (partdb via `model.py`) and other parts' origin cells
  inside the predicted footprint. Glass is reported separately (the encasing glitch).
- (b) **Ports.** Takes every cable cell next to the footprint that opens toward it (the open-face rule from
  `networks.py`, applied to data, power and plasma cables). A hit lands on a predicted port with the same face
  cell and kind; a miss is anywhere else. Direct face-to-face contacts with logic ports also count as hits.
- (c) **Twins.** The same checks with reflected ports.
- (d) **Direction.** Traces cable networks: an output should share a network only with inputs (or Wireless
  Transmitters), and an input only with outputs.

## Results

| key | in-game name | size | ports: name (kind) cell / face | struct | records (unique, twin recs) | port evidence | misses | conf |
|---|---|---|---|---|---|---|---|---|
| accelerometer | Accelerometer | 2x1x2 | acceleration (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 133 (19, 2) | 18 | 0 | high |
| aerometer | Aerometer | 2x2x1 | aerodynamics (out) [1,-1,0] / [1,0,0] | SpaceshipComponent | 22 (12, 0) | 0 | 0 | medium |
| altimeter | Altimeter | 2x1x2 | height (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 26 (16, 3) | 16 | 0 | high |
| atmometer | Atmometer | 2x1x2 | density (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 40 (16, 19) | 16 | 0 | high |
| axis_rotometer | Axis Rotometer | 2x1x2 | angular_velocity (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 10 (10, 0) | 8 | 0 | high |
| distance_meter | Distance Meter | 2x1x2 | distance (out) **[1,0,2]** / [1,0,1] | SpaceshipComponent | 11 (9, 1) | 8 | 0 | high |
| gravitymeter | Gravitymeter | 2x1x2 | gravity (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 73 (15, 16) | 14 | 0 | high |
| inclinometer | Inclinometer | 2x2x1 | angle (out) [1,-1,0] / [1,0,0] | SpaceshipComponent | 19 (9, 0) | 0 | 0 | medium |
| massmeter | Massmeter | 2x1x2 | mass (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 21 (12, 10) | 12 | 0 | high |
| rotometer | Rotometer | – | – (no prefab) | – | 0 | – | – | low |
| thermometer | Thermometer | 2x1x2 | temperature (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 13 (4, 12) | 4 | 0 | high |
| thermoscan | Thermoscan | 2x1x2 | temperature (out) **[1,0,2]** / [1,0,1] | SpaceshipComponent | 0 | – | – | medium |
| trajectory_curvature_meter | Trajectory Curvature Meter | 2x1x2 | angle (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 73 (17, 6) | 17 | 0 | high |
| velocity_meter | Velocity Meter | 2x1x2 | velocity (out) [0,0,-1] / [0,0,0] | SCVelocityMeter | 360 (62, 16) | 61 | 0 | high |
| windmeter | Windmeter | 2x2x2 | wind_speed (out) [0,0,-1] / [0,0,0] | SpaceshipComponent | 9 (7, 3) | 7 | 0 | high |
| blue_tank | Blue Tank | 16x32x16 | fuel (out) [8,8,16] / [8,8,15] | SCTank | 121 (13, 48) | 6 | 0 | high |
| green_tank | Green Tank | 8x24x8 | fuel (out) [4,8,8] / [4,8,7] | SCTank | 125 (10, 50) | 6 | 0 | high |
| red_tank | Red Tank | 16x16x16 | fuel (out) [8,8,16]; cooling (out) [11,7,16]; power [11,6,16] (faces z=15) | SCTank | 0 | – | – | medium |
| long_range_distance_meter | Long Range Distance Meter | 2x2x4 | distance (out) [0,0,-1]; power [1,0,-1] | SpaceshipComponent | 178 (30, 88) | 26 / 27 | 0 | high |
| magnetometer | Magnetometer | 4x8x4 | activity (out) **[-1,0,1]** / [0,0,1]; power [-1,0,0] / [0,0,0] | SpaceshipComponent | 11 (4, 1) | 4 / 4 | 0 | high |
| gyro_line | Gyro-Line | 4x2x4 | pitch (out) [1,0,4]; roll (out) [2,0,4]; power [0,0,4] (faces z=3) | SCGyroLine | 165 (26, 35) | 19 / 18 / 21 | 0 | high |
| space_gps | Space GPS | 4x4x4 | distance [3,0,4]; longitude [2,0,4]; latitude [1,0,4] (all out); power [0,0,4] | SpaceshipComponent | 11 (4, 1) | 4 / 3 / 3 / 4 | 0 | high |
| space_scanner | Space Scanner | 4x4x8 | cone (in) [1,0,-1]; distance (out) [2,0,-1]; power [3,0,-1] (faces z=0) | SpaceshipComponent | 163 (20, 10) | 11 / 12 / 11 | 1 | high |
| fuel_analyzer | Fuel Analyzer | 4x2x4 | value (in) [1,0,4]; performance (out) [1,1,4]; stability (out) [0,1,4]; power [0,0,4] | SCFuelAnalyzer | 19 (5, 10) | 1 / 0 / 0 / 5 | 0 | medium |
| SC_PipeMeter | Pipe Meter | 2x2x2 | none | SpaceshipComponent | 155 (7, 0) | – | 0 | high |
| SC_NanopipeMeter | Nanopipe Meter | 2x2x2 | none | SpaceshipComponent | 0 | – | – | medium |
| SC_BaobaraInterferencemeter | Baobara Interferencemeter | 4x2x2 | none | SpaceshipComponent | 0 | – | – | medium |

Across all parts: **0 cable cells inside any predicted footprint, and 1 miss (explained below).** Direction check:
every cabled sensor output shares its network only with logic inputs or Wireless Transmitters, apart from the one
scratch-blueprint wiring error listed below. Every direct face-to-face contact joins a sensor output to a logic
input or a Wireless Transmitter.

Tall parts were also seen in orientations that send local +y down a negative world axis, where the min-corner
anchoring depends on the full height. Gyro-Line (9 placements), LRDM (14), Space Scanner (5) and Fuel Analyzer (3)
all hit there with no misses. So the `model.py` min-corner rule with the full box holds for multi-cell-tall parts.

### Tanks: why 16 x 32 x 16 and 8 x 24 x 8
- The joint areas are bands at y = 6..7 and 24..25 on the back (Blue Tank), plus a pipe joint at y = 6..7 on the
  front. They span only 20 of 32 cells, so an alternative box of 16 × 20 × 16 (and 8 × 12 × 8 for the Green Tank)
  was tested.
- With the size-field box: 6 + 6 port hits and 0 misses. With the joint box: 0 hits and 6 + 6 misses, all at the
  size-field port cell. The tank-meter port lands at y = 8 above the box's min corner on both tanks, which pins the
  box's bottom at −size/2 for two different heights (4 m and 3 m).
- Upper extent: frames (FrameA ×15, FrameHalfF ×13, …), tanks and 35 cables sit directly on the 32-cell top
  (24-cell for green). Neighbours line the sides at every height up to y = 31, and nothing is ever inside.

### Anomalies (all explained)
- **Velocity Meter**, `0da00183…`: an `SC_FrameB` shares its origin. FrameB is a wedge (triangular joint faces),
  so its 8 × 8 × 4 box has free cells.
- **LRDM**, `824b0750…`: an `SC_FrameQuarterD` corner frame's box covers 4 of the meter's 16 cells. This is the
  same wedge/corner case.
- **Space Scanner**, `0978a48f…` ("Autosave", BlueprintsBin): one data cable opens into x = 0 (a miss) and a power
  cable sits on the `cone` port. The wiring is offset by two cells in −x, likely a mid-edit snapshot. The other 19
  placements agree.
- **Gyro-Line**, `4a0b42f9…` ("Blah", TUTORIAL folder): a twin's pitch and roll are cabled to two Data Router 2
  outputs, a wiring error. It is counted as `direction_conflicts = 2`.

## Per-part notes
- **Small 2 × 1 × 2 sensors** (accelerometer, altimeter, atmometer, axis rotometer, gravitymeter, massmeter,
  thermometer, trajectory curvature, velocity): single output on the **back** face at x = 0 (twin x = 1).
  - The Distance Meter and Thermoscan instead output on the **front** face at x = 1.
  - The Velocity Meter's `_modeButton` and smoothing are covered under "Settings values" above.
- **Aerometer / Inclinometer** (2 × 2 × 1 plates): the output is on the **bottom** face (facing −y) at x = 1. The
  baked list (facing code 3) and the renderer (Euler 90, 0, 0) agree. The footprint is corpus-checked (12 and 9
  placements, nothing inside), but none of those placements is wired, so the port is prefab-only (medium). Both
  parts show their value on a built-in display, which may be why they are placed unwired.
- **Windmeter** (2 × 2 × 2): output on the back face, lower row.
- **LRDM** (2 × 2 × 4): distance and power on the back face, lower row.
- **Magnetometer** (4 × 8 × 4 mast): both ports on the **left (−x)** side, bottom row. In the twin they move to the
  +x side (x = 4).
- **Gyro-Line** (4 × 2 × 4): power, pitch and roll at x = 0, 1, 2 on the front face, lower row.
- **Space GPS** (4 × 4 × 4): power and latitude / longitude / distance at x = 0..3 on the front face, bottom row.
  Its joint area is the bottom face only.
- **Space Scanner** (4 × 4 × 8): cone (in), distance, power at x = 1..3 on the back face, bottom row. Its joint
  area is the bottom face's back half only.
- **Fuel Analyzer** (4 × 2 × 4): all four ports on the front face, left half. The upper row holds stability and
  performance, the lower row power and value. A fuel-pipe joint sits on the front face, right half.
  - Power (5 placements) and `value` (1 twin) are corpus-confirmed. The two outputs are confirmed only by the
    prefab plus the order check in Method 3, hence medium.
  - Set `_mode = 1` when `value` is wired.
- **Red Tank** (16³): fuel (x = 8, y = 8), cooling (x = 11, y = 7) and power (x = 11, y = 6), all on the front face.
  No corpus instances. Geometry follows the same size-field rule as the two corpus-confirmed tanks, and the struct
  follows the inheritance rule.
- **Thermoscan**: no corpus instances, but its layout is identical to the corpus-confirmed Distance Meter.
- **Pipe Meter / Nanopipe Meter** (2 × 2 × 2): fuel-pipe segments with indicator bars. No data or power ports
  (no port children, no baked list, no Localization port rows), with pipe joints on −z and +z. The Pipe Meter's
  footprint is corpus-checked (7 placements).
- **Baobara Interferencemeter** (4 × 2 × 2): quest display (Void Watcher objective), no ports.
- **Rotometer**: no `SC_Rotometer` / `SC_Rotometer M` GameObject exists in `globalgamemanagers.assets` (scanned).
  Its hash `955ad7bed99d6821` never occurs in the corpus, but Localization still has `SC_Rotometer_*` rows.
  `SC_AxisRotometer` uses the class `EPC_SCRotometer`, so it is the in-game replacement. Substitute
  `axis_rotometer` (same 2 × 1 × 2 body, back-face output).

## Open questions
1. **Tank valve default.** The in-game initial `_actionableValue` of a freshly placed tank is unknown (1.0 is
   assumed). A one-tank load test would settle it.
2. **Gyro-Line `_rotKnobValue`.** It is an orientation knob with quarter steps; what each step means is not
   decoded.
3. **Unconfirmed ports.** No corpus wiring confirms the Aerometer and Inclinometer outputs or the Fuel Analyzer's
   two outputs; Thermoscan, Red Tank, Nanopipe Meter and Baobara Interferencemeter have no corpus instances at all.
   A test blueprint with one stub on each port would confirm them all at once.
4. **`joint_faces`.** These are from the prefab only. Whether the game refuses to join, or to support, a part
   through faces without a joint area (e.g. the LRDM and Space GPS have only a bottom joint face) is untested.
5. **Fuel pipes are not modelled.** The `pipe` joint faces are listed, but pipe connectivity is another network
   with its own parts.
6. **Sensing direction.** Several sensors must face open space (see `description`). Only the Velocity Meter's axis
   is decoded (+z in Directional mode). For the LRDM, Space Scanner, Trajectory Curvature Meter, Distance Meter and
   Thermoscan, the face that must be clear is presumably the one opposite the ports, but this is not decoded. The
   Altimeter and Windmeter components carry a `_dirIndex` (PDB `SCTypeAltimeter`, `SCTypeWindmeter`) that the
   game presumably sets at runtime.
