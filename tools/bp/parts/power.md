# Power, fluid and cable parts: `power.json`

Status 2026-10-02. All 15 simulator power types, both valve types, the 9 pipes, the 9 nanopipes and the four
cable kinds, derived from the game's own prefab data and checked against the 301-blueprint corpus. Every part
with corpus instances has every port confirmed, no overlaps and almost no stray cables (3 in 1,757 Power
Routers). The cable section answers the four cable questions from the game code (Burst disassembly and metadata
constants) and the corpus.

## Contents of `power.json`

- One entry per part, keyed by simulator type id (`power_router`, ...) or by prefab name when the simulator has
  no such type (`SC_PipeFull`, ...). The fields are the ones requested: `name`, `prefab`, `hash`,
  `mirrored_hash`, `struct`, `size`, `ports`, `settings`, `corpus`, `confidence`, `notes`.
  - **`ports`** are in the canonical frame (orientation 16, origin = footprint min corner). `cell` is the cell
    just outside the face and `face` is the footprint cell it touches.
  - Extra port fields: `game_port` is the game's port index (Port0..N, the `SC_<X>_PortN` order in
    Localization.csv) and `game_type` is the `SpaceshipPortType`.
  - **Simulator port names follow the game order.** engine.js lists every type's ports in that order (checked:
    Power Blocker block/a/b = DataInput/Power/Power, meters generation/power = DataOutput/Power, batteries
    power/level = Power/DataOutput, the valve open/power = DataInput/Power).
  - **Pipe ends are ports of kind `fluid`.** Each is a whole 2×2 face. `cell` and `face` give the patch's min
    corner, `cells`/`faces` list all four cells, `normal` is the outward direction, and `end_type` is `pipe` or
    `decoupling`. Two ends join when their patches coincide face to face.
  - `twin_prefab_ports_are_x_reflection` is true for every part that has a twin. The game ships each twin as its
    own prefab `"<name> M"`. This category's twins were dumped and compared: the ports are exactly the normal
    ports reflected along x (dx → w−1−dx, facing x negated), as NOTES.md states.
- **`cable_rules`** holds the cable answers (below) with their corpus numbers.

## Summary

| key | prefab | hash / twin | size w×h×d | ports (canonical cell) | corpus n (twin) | ports used | conf |
|---|---|---|---|---|---|---|---|
| small_disposable_battery | SC_SmallDisposableBattery | 1fa8fb58e3c13ead / 3ee716a3abde8b5a | 4×4×4 | power (2,1,−1) | 859 (333) | 1/1 | high |
| medium_disposable_battery | SC_MediumDisposableBattery | 9bab51c99b079f89 / c0e29316570ecef4 | 4×8×8 | power (3,3,−1); level (2,3,−1) data out | 401 (100) | 2/2 | high |
| large_disposable_battery | SC_LargeDisposableBattery | edb5cf9aa33baf20 / eae63d8b28f871ff | 8×16×8 | power (7,0,−1); level (6,0,−1) data out | 440 (21) | 2/2 | high |
| small_rechargeable_battery | SC_SmallRechargeableBattery | 336f2ac52d4787be / 0f03d9e1ab941736 | 4×4×4 | power (3,0,−1) | 53 (7) | 1/1 | high |
| medium_rechargeable_battery | SC_MediumRechargeableBattery | cd89d4664fdb88d1 / 835c73f722e6f815 | 4×8×8 | power (3,0,−1); level (2,0,−1) data out | 285 (126) | 2/2 | high |
| large_rechargeable_battery | SC_LargeRechargeableBattery | e3b42b942f0609a0 / c4410a00c671f5f4 | 8×16×8 | power (7,0,−1); level (6,0,−1) data out | 0 | – | medium |
| solar_panel | SC_SolarPanel | b50151c544d28980 / c66a560c250a02cc | 8×1×16 | a (0,0,−1); b (0,0,16) | 442 (100) | 2/2 | high |
| autohemisphere_solar_panel | SC_AutohemisphereSolarPanel | c71fefef7fdd7a6d / 98b5868e9920859d | 8×8×8 | power (4,0,8) | 95 (32) | 1/1 | high |
| dynamo_box | SC_DynamoBox | f7e679584541cb43 / 658727e656088e61 | 4×4×4 | power (−1,0,0) (left face) | 5 (4) | 1/1 | high |
| power_router | SC_PowerRouter | 113f69c2ce431379 / – | 2×1×2 | a (1,0,2); b (0,0,2); c (0,0,−1); d (1,0,−1) | 1757 | 4/4 | high |
| large_power_router | SC_LargePowerRouter | 59f14dc51f340839 / – | 4×1×2 | a..d (3..0,0,2); e..h (0..3,0,−1) | 584 | 8/8 | high |
| fuse_box | SC_FuseBox | 28930cd939c68265 / a5c58bbc386a1af4 | 4×4×1 | a (2,4,0); b (1,4,0) (top face) | 47 (4) | 2/2 | high |
| power_blocker | SC_PowerBlocker | 753599ac7ffa22ec / 4025ee436b7aa71c | 2×1×2 | block (1,0,−1) data in; a (0,0,−1); b (0,0,2) | 149 (43) | 3/3 | high |
| power_generation_meter | SC_PowerGenerationMeter | cf9a9b322af3088c / 7cbe6cf9ba5f1558 | 2×1×2 | generation (1,0,2) data out; power (0,0,2) | 67 (40) | 2/2 | high |
| power_usage_meter | SC_PowerUsageMeter | ca5b4160d4b2717c / 3df572d815326c80 | 2×1×2 | usage (1,0,2) data out; power (0,0,2) | 52 (5) | 2/2 | high |
| pipe_electric_valve | SC_PipeElectricValve | 656a9abb2f5ca827 / cbe07a62af952772 | 2×2×2 | open (0,2,1) data in; power (1,2,1); end_+z; end_−z | 2 | 4/4 | medium |
| nanopipe_electric_valve | SC_NanopipeElectricValve | 6ff0d1b476b62cf4 / 09bd5cd1de87b7db | 2×2×2 | same as the valve above | 0 | – | medium |
| SC_PipeFull / Half / Quarter | SC_Pipe… | 72c3c84be0745184 / 77d3b9de6947ecdb / 412a44636f7305d1 (no twins) | 2×2×8 / 2×2×4 / 2×2×2 | end_−z, end_+z | 312 / 194 / 449 | 2/2 | high |
| SC_PipeCorner | SC_PipeCorner | 4ea7430169fc121c / 51586b0d9b2c7fa9 | 2×2×2 | end_+z, end_+x | 906 (49) | 2/2 | high |
| SC_PipeThreeway | SC_PipeThreeway | d29ccf71936083f3 / f780dce5ee3d34ce | 2×2×2 | end_−z, end_+z, end_+x | 538 (12) | 3/3 | high |
| SC_PipeCross | SC_PipeCross | 235f4af9d0bb1206 / – | 2×2×2 | end_±z, end_±x | 2 | 4/4 | medium |
| SC_PipeManualValve | SC_PipeManualValve | a0e7fa229a881e99 / 2bd1afd649134885 | 2×2×2 | end_+z, end_−z | 99 | 2/2 | high (geometry) |
| SC_PipeMeter | SC_PipeMeter | 9d1e58bec000e969 / – | 2×2×2 | end_−z, end_+z | 155 | 2/2 | high |
| SC_PipeDecoupling | SC_PipeDecoupling | ec1c63538250be7c / 4b8b5ccd966e5475 | 2×2×2 | end_−z (pipe), end_+z (decoupling) | 0 | – | medium |
| SC_Nanopipe… (9 kinds) | SC_NanopipeFull … | see power.json | same as the matching pipe | same | 0 | – | medium |

Port kinds: power ports are `both` (one circuit); data ports are `in`/`out`. "Back" is z = −1 and "front" is z = d.

### Notes per part
- **Batteries.**
  - All ports sit on the back face.
  - The small disposable has its port at mid-height, (2,1,−1). The medium disposable has both ports at y = 3.
    The other batteries have them on the bottom row.
  - The level output (data) is rarely wired. Its port cell often holds the power cable that leaves the power
    port sideways, counted as `cable_not_open` in `power_validation.json`. In both medium batteries' corpus data
    the power ports touch other power ports directly 49 + 49 times.
- **Large Rechargeable Battery.** No corpus instance. Its prefab, twin prefab and Localization rows exist, and
  it has the same size and port layout as the Large Disposable Battery, which has 440 corpus instances.
- **Solar Panel.** A flat 8×1×16 plate. Its two ports are both at x = 0, one on each end face, 16 cells apart.
- **Dynamo Box.** The port is on the **left** face (−x), at the bottom back corner. The twin has it on the right
  face.
- **Fuse Box.** A 4×4×1 upright plate. Both ports are on the **top** face.
- **Routers.**
  - The ports are interchangeable, since they form one circuit.
  - The game order runs around the part: for the Power Router, front x=1, front x=0, back x=0, back x=1; for the
    Large Power Router, front x=3..0, then back x=0..3.
  - Neither router has a twin.
- **Pipe valves are one-way.**
  - The electric valve: in both corpus designs, Gecko and Outcast, the −z end leads only to tanks and the +z end
    only to thrusters. So the inlet is end_−z and the outlet end_+z (2/2; not found in code).
  - The manual valve's only corpus design has two valves in a loop, which is inconclusive.
  - The Pipe Decoupling's decoupling side, "the marked side", is the +z end: its JointsArea `_type` is 2.

## Method (scripts in this folder; `PYTHONUTF8=1`, optional `AU_SCRATCH` for the corpus cache)

1. **`power_prefabs.py` → `power_prefab_dump.json`.** It dumps this category's prefabs from
   globalgamemanagers.assets, plus the extras that `../prefab_dump.json` lacks: SC_LargeRechargeableBattery,
   SC_PowerNanocable, the nanopipes and every `"<name> M"` twin. It uses the same format as `../prefab_dump.py`,
   plus object path ids.
2. **`power_geom.py`.** Geometry from the root EPC component, `EPC_SpaceshipComponent` and its subclasses.
   - **Size.** `_bounds` is the float3 at byte 12, in metres, after the 12-byte `_mirroredVersion` PPtr.
     It is an exact integer cell count on all 213 prefabs. The prefab origin is the footprint centre.
   - **Ports come from `_electricPorts`**, an array inside the same component: a u32 count, then per port a
     float3 local position (the face cell's centre), an i32 face (0 +x, 1 −x, 2 +y, 3 −y, 4 +z, 5 −z) and an
     i32 `SpaceshipPortType` (0 DataInput, 1 DataOutput, 2 Power, 3 DataInOut, 4 Plasma, 5 Unset). The array
     order is the game's port order.
   - **Checks on the port data:**
     - The array is located by scanning for a count followed by records that all lie on the box surface.
     - On all 157 prefabs that have ports, it equals the "Port …" renderer children: renderer position plus
       euler-rotated +z, with the mesh id giving the kind.
     - It reproduces `partdb.json` for all 43 logic parts, normal and twin: 86/86 port-cell sets.
     - Exception: the thrusters' "Port Input Reverse Mode Button" renderer (mesh 5642) is **not** a port. It is
       in neither `_electricPorts` nor Localization.
   - **Pipe ends** are the `SpaceshipComponentAreaPoly` ("JointsArea Pipe …") polygons with `_type` 1 (pipe
     end) or 2 (decoupling end). `_type` 0 marks plain joint faces and 3 the decoupler joint.
   - **Struct.** A part uses its own class's `Blueprint` struct, or else the nearest base class's. Checked on
     208/213 corpus prefabs; the 5 exceptions are subclasses inheriting a base struct, e.g. ZoomCamera →
     EPC_SCCamera. So batteries, pipes and the electric valve use `EPC_SpaceshipComponent`, the Fuse Box uses
     `EPC_SCFuseBox`, and the manual valves use `EPC_SCPipeManualValve`.
   - **Default `_col`** is the component's `_defaultPaintableColor`, the int32 before the
     `_paintableRenderers` array. It is 0 on power parts and nanopipes and 200 on pipes.
3. **`power_corpus.py` + `power_world.py`.** These load the corpus with raw records (same files and dedup as
   `../corpus.py`) and place every part with prefab geometry, plus all cable kinds, in world cells. Placement
   follows `../model.py`: orientations.json rotation, then re-anchoring at the min corner.
4. **`validate_power.py` → `power_validation.json`.** For each instance, normal and twin, it records:
   - overlaps with any placed part or cable;
   - per port: a compatible cable in the port cell opening toward the part (`cable`), a facing compatible port
     (`contact`), or covered / free / wrong kind;
   - misses: cables beside the footprint that open into it at a non-port cell;
   - pipe ends joined face to face.
5. **`build_power.py` → `power.json`**, written atomically after each entry. It uses
   **`power_cable_rules.py`**, which reads `power_cables_stats.json` (from **`power_cables.py`**) and
   `power_anchor_stats.json` (from **`power_anchor.py`**). **`power_pipeflow.py`** is the valve-direction check.

Run order: `power_prefabs.py`, `validate_power.py`, `power_cables.py`, `power_anchor.py`, `build_power.py`.
Each corpus pass takes 0.5–1 min.

### Validation results (from `power_validation.json`)
- **Overlaps.** None for any of these parts, apart from 1 Auto-Hemisphere twin inside a curved frame and 1
  Power Router inside glass, the known "encased" style. No cable cell ever lies inside a predicted footprint.
- **Ports.** Every predicted port on every part with corpus instances is used. Use is high wherever it is
  meaningful:
  - batteries' power ports: 857/859, 400/401, 440/440, 53/53, 285/285;
  - Power Router ports: 1,296–1,415 of 1,757 each;
  - Large Power Router ports: 313–525 of 584 each;
  - Fuse Box: 47/47 and 43/47;
  - Power Blocker: 146/149 data, 146/149 and 146/149 power.
- **Direct contact.** Power ports also connect face to face: 102–151 contacts per Power Router port, and 35/47
  on the Power Usage Meter's power port.
- **Misses.** Cables opening into a footprint away from a predicted port: 0 on every part except the Power
  Router, with 3 in 1,757 (1 data, 2 power).
- **Twins.** 333 small disposable, 100 medium disposable, 126 medium rechargeable, 100 solar panel twins and
  others, all on the x-reflected ports.
- **Pipes.** Every end of every pipe instance is joined face to face (2×2 patch on 2×2 patch), apart from 3 open
  ends among about 5,000.

## Settings
- `EPC_SpaceshipComponent` (24 B: `_guid`, `_gt`, `_col` @20). This is the struct for every battery, panel,
  router, the blocker, the meters, the Dynamo Box, every pipe and the electric valves; they carry no settings.
  A battery's charge is not saved.
- **`EPC_SCFuseBox._threshold`** (f32 @20) is a lever position from 0 to 1.
  - `SCTick_FuseBox` computes the trip threshold as `int(v × roundingIntervals)` clamped to 0..999 P/s. The
    lever's `roundingIntervals` is 1000 and its default 150.
  - All 47 corpus records hold 0.1505, which is 150 P/s.
  - To set T P/s, write (T + 0.5)/1000.
- **`EPC_SCPipeManualValve._actionableValue`** (f32 @20) is the valve opening from 0 to 1. 96 of 99 records hold
  1.0.
- **`_col`** is paint. Its default is the prefab's `_defaultPaintableColor`: 0, or 200 on pipes.

## Cables (`cable_rules` in power.json)

### Q1: same geometry and rules for every kind?
**Yes.**
- All cables use `EPC_SCCable`: `_guid` @0, `_gt` @16, `_shape` @20, `_type` @21, `_col` @22.
- The same open-face rule applies to every kind: `_shape` 0 is straight, open at local ±z; `_shape` 1 is a
  corner, open at local +y and +z. Each cell is rotated by its orientation code.
- **`_type`** (SpaceshipCableType) is the only setting that differs:

| kind | prefab | hash | `_type` | rated P/s (prefab `_maxPower`) | corpus cells |
|---|---|---|---|---|---|
| data | SC_DataCable | e60658e2e04f33ce | 0 | – | 111,044 |
| power | SC_PowerCable | 743531fcd428bc2c | 1 | 150 | 107,818 |
| power nano | SC_PowerNanocable | 796f2b5d0244e1af | 2 | 400 | 0 |
| plasma | SC_PlasmaCable | e8f9b8dac4e23b9c | 3 | – | 83 |

Evidence:
- **Prefabs.** Each cable prefab's own `EPC_SCCable` stores `_type` (u32 @176) and `_maxPower` (f32 @180).
  `SCTypeCableCell_Singleton` orders its mesh tables Data, Power, PowerNano, Plasma.
- **Corpus `_type` values.** Every record carries its kind's value: data 0 (70,972 straight + 40,072 corner),
  power 1 (80,340 + 27,478), plasma 3 (62 + 21).
- **Open-face rule.** An open face counts as a hit when it meets a same-kind cable opening back, or a compatible
  port whose port cell is this cell:

| kind | straight hits | corner hits |
|---|---|---|
| data | 140,183/141,944 | 80,043/80,144 |
| power | 160,610/160,680 | 54,925/54,956 |
| plasma | 124/124 | 42/42 |

- **Corner face pairs.** All 15 possible corner face pairs were scored, and local +y/+z wins for every kind. The
  next-best pair scores 29,531 for data and 22,331 for power.

**Same `_type` required.** Two cells connect only if both open toward each other **and** they have the same
`_type`: `UpdateCellsAndPortsJob` compares the neighbour's `_type` first. So a power cable never joins a nano
cable or a data cable directly. In the corpus, open faces meet a cable of another kind only 7 times, all dead
ends.

### Q2: which ports each kind joins
`GarageUpdateCables.UpdateCellsAndPortsJob` switches on the port's `SpaceshipElectricPort._setupType`; the jump
table was decoded from lib_burst_generated.dll:

| port type | accepts `_type` |
|---|---|
| DataInput (0), DataOutput (1), DataInOut (3, Wireless Transmitter) | 0 (data) |
| Power (2) | 1 or 2 (power, nano) |
| Plasma (4) | 3 (plasma) |
| Unset (5), the pass-through ports of the frames with ports | 0..3 (any) |

A cable joins a port when it sits in the port cell and its open face points straight at the part
(dot < −0.99).

Corpus joins:
- data: 13,002 data in, 11,840 data out, 3,088 wireless, 3,666 frame ports;
- power: 14,906 power ports, 3,159 frame ports;
- plasma: 10 plasma ports.

Cable ends lying in an incompatible port: 4 data-in-power and 23 power-in-data, all dead ends.

Networks per kind:

| kind | 2 ports | 1 port | 0 ports |
|---|---|---|---|
| data | 14,878 | 1,840 | 11 |
| power | 8,986 | 93 | 4 |
| plasma | 5 | – | – |

A cable has at most 2 links per cell. Power routers are the hubs.

### Q3: the Nano power cable
It is a separate prefab, `SC_PowerNanocable` ("Power Nanocable", unlocked by the `Package_Ascensia_NanopowerCables`
package). Its hash is `AsciiHash64("SC_PowerNanocable")` = `796f2b5d0244e1af`.
- It uses the same `EPC_SCCable` record with `_type = 2`, and the same shapes and orientations.
- Its prefab `_maxPower` is 400 P/s, against 150 for the normal power cable. Bulb_31: a cable burns out when its
  circuit's total consumption or generation exceeds the limit.
- It joins Power and Unset ports only, and links only to other `_type`-2 cells.
- No corpus blueprint uses it, so it is untested in a load test.

### Q4: reach ("at most 11 cells from a supported side")
**The constant.** `MAX_UNANCHORED_CELLS = 10`, read from global-metadata.dat: field default values, IL2CPP
compressed int 0x14 → 10. Other constants there: `CABLE_CELL_SIZE = 0.125`, `MAX_MOUNT_DISTANCE = 4.2`.

**The rule** (Burst jobs in `GarageUpdateCables`):
1. **`UpdateCellsAndPortsJob`** decides which cells are *anchored*. An anchored cell gets `_anchorEntity` set,
   `_anchorRangeEntity` = itself and `_anchorRangeDistance` = 0. A cell is anchored when either:
   - it is joined to a compatible port: `_anchorEntity` = the port's Parent, i.e. the part; or
   - it is **straight** (`_shape == 0`, never a corner), not already port-anchored, and one of its 4 side probes
     anchors it. The probes run perpendicular to the cable axis; each probe point is 0.0725 m from the cell
     centre. The rest of the probe test:
     - The probe point must lie inside a frame collider (layer 0x10, `SCTypeFrame`).
     - Then the line from the cell centre crosses one of the frame's face polygons (`FramePrefabFacesData`, up
       to 8 faces, back-face culled). The cell is anchored if that face is welded (its bit is set in the
       record's `_solidFaces`; on a frame with ports, not where a port collider is), or if the crossing point
       lies **within 0.08 m of the face polygon's edges**.
     - So on an unwelded 4×4 frame-quarter face, the 12 border-ring cells anchor and the inner 2×2 do not.
2. **`UpdateAnchoringJob`** walks `_connectedFwd`/`_connectedBwd` from every anchored cell for d = 1..10. It
   stops at d == 11 or at another anchored cell, and keeps the minimum d.
3. **`AreAllCableCellsAnchoredJob`** fails if any cell has `_anchorRangeEntity == Null`. The game then shows
   "Cannot enter Fly Mode because some cable cells are not anchored." Such blueprints still save and load.

So every cell needs an anchored cell within 10 steps along its own chain:
- a stub held at one end is at most 11 cells (the anchored cell + 10);
- a port-to-port run with no frame support is at most **22** cells (21 leaves one cell of margin);
- touching a part anywhere other than a compatible port does not anchor anything.

**Corpus evidence:**
- **Upper-bound model.** Anchors = compatible ports + any straight cell whose side touches a frame (a superset of
  the game's anchors). 160 networks reach exactly 10 steps, only 3 reach 11, and 29 in all exceed 10.
- **The 29 exceptions:**
  - the loose I/O stubs of one Workshop circuit ("Triple PID - All Hover", 12–18 cells held at one end);
  - autosaves;
  - three other saves.
- **Exact frame rule (`power_anchor.py`).** This model takes each frame prefab's plain JointsArea polygons as its
  faces, uses the near face, the 0.08 m edge test and the record's `_solidFaces`.

| model | networks > 10 | networks at exactly 10 / 11 |
|---|---|---|
| ports only | 1,691 | – |
| + frame edge rule | 46 | 220 / 5 |
| + welded faces | 45 | – |
| upper bound | 38 | – |

  The 8 networks between the edge model and the upper bound sit on curved or wedge frames (SC_FrameB etc.), whose
  sloped face is not a JointsArea polygon, or on welded faces.
- **Lengths with no frame contact.** Port-to-port: 106 networks of 21 cells and 3 of 22, then nothing until four
  one-off saves of 26–32 cells. One-port stubs stop at 11, apart from the same exceptions.

## Open questions
1. **Valve flow direction.**
   - Electric valve: inlet −z, outlet +z on corpus evidence (2/2 designs).
   - Manual valve: unresolved. The likely place to look is `FuelConnections._blockedEnding`, set in managed
     pipe-connection code.
2. **Nano power cable.** Untested in-game (no corpus use; it needs the package unlocked). If a load test is
   wanted: one SC_PowerNanocable record with `_type` 2 between two power ports.
3. **Frame faces for anchoring.** The rule is clear, but `FramePrefabFacesData`'s exact face list and the
   `_solidFaces` bit order are inferred: the JointsArea polygons in XP, XM, YP, YM, ZP, ZM order fit, and the
   near-face and far-face bit readings differ by one network. Curved frames need their real face list; this
   belongs to the frames/structure work.
4. **The four probe directions** were read as the 4 sides perpendicular to a straight cell's axis. That fits the
   code structure (±A, ±B) and the corpus, but the quaternion arithmetic was not traced line by line.
5. **Prefab-only parts.** Large Rechargeable Battery, Pipe Decoupling, the nanopipes and the nanopipe electric
   valve have no corpus instances; they are marked medium.
6. **For the other agents.** `_electricPorts` (see Method) gives every prefab's authoritative port list and game
   order, and mesh 5642 ("Port Input Reverse Mode Button" on the thrusters) is not a port.
