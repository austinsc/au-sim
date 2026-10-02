# Approximately Up blueprint (.bp) format — reverse-engineering notes

Status 2026-10-02: **container format and hash scheme fully decoded.** All local .bp files parse with no leftover
bytes, and every id is a hash of a readable name (see "Hash scheme"). Logic-part footprints, ports and the orientation
table are decoded below. Frame, glass and label geometry is still to do.

## Where blueprints live
- `%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp\Blueprints\<guid>.bp`
  plus `<guid>.bpmeta`, a small JSON file `{"_name": "...", "_folder": "...", "_version": "1.0.212"}`.
  The `.bpex` files there are all zero bytes.
- `...\BlueprintsBin\` holds 1,320 more .bp/.bpmeta pairs (history / deleted).
- The game install ships tutorial ships under `ApproximatelyUp_Data\StreamingAssets\*.bp`.

## Container (little-endian), see `bpformat.py`
```
u32 nTypes
nTypes × { u64 structHash; u32 size; u32 nFields; nFields × { u64 fieldHash; u32 offset; u32 size } }
records until EOF: { u64 partHash; u32 schemaIndex; u32 0; byte[schema[schemaIndex].size] }
```
- The schema is a global table of part-settings structs: 45 entries in older saves, up to 48 in newer ones.
- Part, struct and field ids are 64-bit hashes of names (see "Hash scheme"). All structs and fields are
  listed by name in **`schemas.json`**; parts by prefab name in **`prefabs.json`**.
- Common fields:
  - `_guid` `5a9afb0dddc03646`: 16 B, always at offset 0. A unique instance id.
  - `_gt` `674a096805f65dc6`: 4 B, CELL (below). The offset varies by struct.
  - `_actionableLabel` `602a2eadf84c5000`: 32 B, UTF-16, 16 chars. A part's own title or label text.
  - `_col` `a02a12ac78f009a6`: 1 B, paint colour. On every struct except frames, which have `_col0`..`_col7`.
  - `_labelRotated` `0ebcc5a8415a16fe`: the 180° text flip.
  - Settings have plain names, e.g. `_value` (Constant), `_mode` (Condition, Round, Memory, Accumulator),
    `_value0`..`_value3` (Remapper), `_rotKnobValue` (Delay, Differentiator), `_ticks` (Initializer),
    `_shape`/`_type` (cable), `_solidFaces` (frame).

## Hash scheme (decoded from the game binaries, 2026-10-02), see `hashes.py`
Every id is **`BurstUtility.AsciiHash64(name)`**:

| id | name hashed | example |
|---|---|---|
| part hash | prefab name; a mirrored twin is a separate prefab, `"<name> M"` | `"SC_Constant"` → `9fe80f5af364c2ec`, `"SC_Constant M"` → `cee813dc3421e693` |
| struct hash | the settings struct's .NET `Type.FullName` | `"EPC_SCConstant+Blueprint+BlueprintData"` → `4bebf2e4eb16d986` |
| field hash | the C# field name | `"_guid"` → `5a9afb0dddc03646` |

**AsciiHash64** (GameAssembly.dll `0x180C458E0` in this build) is xxHash64-like but **not** xxHash64. That is why
the earlier xxHash64 tests missed.
- It uses the xxHash64 primes and avalanche with seed 0.
- It reads **one byte per char**, the low byte of each UTF-16 code unit.
- Its initial length term is the **UTF-16 byte length** (2 × chars).
- It hashes 8 chars per round with the 8-byte-lane step, then single chars with the 1-byte step. There is no 32-byte
  stripe path and no 4-byte step.

Coverage and confirmation:
- **Coverage.** Every field hash (65 of 65) and 48 of 49 struct hashes resolve. Part hashes resolve for 359 of 362
  types, 99.998% of all records, using `"SC_" + <Localization key>` and asset names. The three unresolved types
  occur 1–3 times each.
- **Where the hashes are computed.** `BlueprintUtility.CreateBlueprintHeader` calls AsciiHash64 twice, for the struct
  and field names. `SCPrefab..ctor` calls it on the prefab name.
- **How it was found:**
  1. The metadata names the schema records `BlueprintSerializedStructLayout._structName` and
     `BlueprintSerializedStructField._fieldName`.
  2. `il2cpp.py` maps each IL2CPP method to its code address. `lib_burst_generated.dll` ships with a PDB, so dumpbin
     shows the Burst serializer (`BlueprintUtility.Bursted.*`) by name.

Some prefab names fix earlier guesses:
- `SC_FrameQuarterA` is the frame quarter.
- `SC_FrameHalfA` is the 4 × 8 × 4 encasing frame.
- `SC_GlassHalfA` is the 4 × 8 × 4 glass.
- `SC_FrameA` is the 8 × 4 × 8 frame.
- `SC_LabelSmall` is the Label; `SC_LabelMedium` is the **Large Label** (its in-game name, from Localization.csv).
- `SC_FrameQuarterPorts` / `SC_FrameQuarterPortsCorner` are the port frames, with twins.
- `SC_PowerCable` and `SC_PlasmaCable` are the other two cables.
- Logic parts use internal names, e.g. `SC_Router4` (Data Router 4), `SC_SignalRouter3` (Data Redirector 3),
  `SC_JoystickSplitter` (Sign Splitter) and `SC_LogicGateAnd`. `partdb.json` records each one's `prefab`.

New part types need no template: hash the prefab name, and build the schema entry from the struct's field names,
offsets and sizes (`schemas.json`, or the PDB via `pdbtypes.py`).

## CELL (u32)
- bits 0–8 = x, 9–17 = y, 18–26 = z (9 bits each). Values in saves sit around 180–260, so the origin is presumably near 256.
- bits 27–31 = orientation index 0–23. All 24 cube rotations occur. **The mapping from index to rotation is unknown.**
- Evidence: with the x/y/z = 9/9/9 split, 2,281 of 2,281 cable cells in "Boxy" are unique and 99.8% have a grid neighbour.

## Part types seen (362 distinct across 301 blueprints; names from the hash scheme)
- `SC_DataCable` `e60658e2e04f33ce`: the **data cable cell**, in every non-empty save. Compact logic circuits are
  mostly these.
- `SC_PowerCable` `743531fcd428bc2c` and `SC_PlasmaCable` `e8f9b8dac4e23b9c`: the other cables, on the same
  `EPC_SCCable` struct.
- `SC_GlassHalfA` `83430f870bdfacbf`: **glass block, 4 × 8 × 4** (local w × h × d; the user confirmed the size). It
  uses the settings-free struct.
  - In "Better Than PID" and "Universal flight computer", **every logic part sits fully inside the glass** (9/9 and
    26/26). Only the I/O cable ends and the text labels are outside.
  - That is the "encased in glass" glitch: overlapping records, which the game loads.
- `SC_FrameHalfA` `65ba6e9a45f600d0`: **4 × 8 × 4 frame** (`EPC_SCFrame`).
  - "Universal flight computer" **double-encases** its logic: three of these frames and three glass blocks share
    exactly the same origins and volume.
  - The frame reads `_solidFaces` = `08`. Six of `_col0`..`_col7` are `02` and two are `c8`. In the same blueprint
    the glass's `_col` is `0f`.
- `SC_LabelMedium` `7cfa59e0d07dcb3e`: the **Large Label** (`EPC_SCLabel`). Both glass examples carry their I/O names
  on it ("VELOCITY OVERALL", "GROUND DISTANCE", "HOVER HEIGHT"), just outside the glass by the cable ends.
  Size to be confirmed.
- `SC_FrameQuarterA` `482074ef572f3723`: the **frame quarter**, a 4 × 4 × 4 cube. "Auto Turn and Burn v3" sits on a
  6 × 8 floor of them at 4-cell spacing, and it occurs in only 5 orientations.
- `SC_FrameQuarterPorts` `18d3ed13f664ec3f` (twin `731e5443f167d667`) has 3,288 corpus instances.
  `SC_FrameQuarterPortsCorner` `ebc0272a6795bc6c` (twin `50d4412d3c4bbed3`) has 1,712. Port cells are still to
  derive from the corpus.
- Compact Workshop logic circuits contain **no frames**. Blocks sit directly against each other and
  the cables, for example "Compact PID with AntiWindup": 85 parts in a 5×6×9 box, 64 of them cable cells.

## Writing (verified offline 2026-10-02)
- `bpformat.write()` reproduces **all 747 local .bp files byte-for-byte**, and `pack_cell(unpack_cell(c))`
  is exact on all 1,034,699 parts.
- No part's GUID appears anywhere else in its file, across about 1M parts, so fresh ids are independent.
  Most GUIDs are .NET-order v4 (`uuid.uuid4().bytes_le`); about 10%, mostly cable cells, aren't v4,
  so the game doesn't insist on v4.
- `.bpmeta` is one-line UTF-8 JSON with no BOM.

## Cable cells (data cable, schema struct `ac55b0d723fc7373`)
- Of the three 1-byte settings, the first two are always 0 in straight runs. The third is the field
  shared by every struct (`…09a6`), which takes values 0/2/3/10/11/19… and is probably paint colour.
- Connections must come from adjacency; nothing in the record names a neighbour.
- Straight runs use one of two orientations per axis: x → 0 or 5, y → 9 or 12, z → 16 or 21.

## Load tests (2026-10-02, `make_load_tests.py --install`, folder "au-sim" in-game)
- **A** "au-sim A clone": "Height Control" with fresh ids. Only GUID bytes differ.
- **B** "au-sim B labels": as A, with TARGET → AU-SIM and TARGET HEIGHT → AU-SIM TEST OK.
- **C** "au-sim C axes": built from scratch. Three separate straight data-cable runs, 7 cells along x,
  5 along y and 3 along z. They should show which in-game direction each axis is.
- **Results: all three load in-game.** The two edited "labels" in B were the built-in titles of two items, the Wireless
  Transmitter's channel name and the title of a display part, not Label parts. So the 32-byte LABEL field is an item's
  own title text.

## Decoded from the user's "rosetta" blueprint plus 290 distinct corpus blueprints (2026-10-02)
`decode_rosetta.py` → `parts.json`, `fit_orientations.py` → `orientations.json`, `build_partdb.py` → **`partdb.json`**.

- **Part identities.** 43 logic parts are mapped by row order. The order is confirmed independently by each part's settings
  struct: a float on the Constant and Simple Threshold, a mode byte on the Condition, Round, Accumulator and Memory,
  4 floats on the Remapper, and ticks on the Delay, Differentiator and Initializer. Rosetta lacked the hyperbolic row
  and the Large Label.
  - Notable hashes: Label `30dd685b29b0b3a1`; Wireless Transmitter `fb42bddabfe173ed` (its LABEL field is
    the channel name, the field ending `1781` is the channel); data cable `e60658e2e04f33ce`; frame used under rosetta
    `30fe6645d0a002a4` (8×4×8 cells).
- **Footprints.** Logic blocks are **1 cell tall**. Most are 2 × 1 × 2 (x × y × z); Data Router 4, Data Redirector 3,
  Condition, Remapper and Addition Array are 4 × 1 × 2; Data Hub is 6 × 1 × 2. The origin is the min corner. Evidence:
  - spacing in rosetta
  - no cable ever sits inside the footprint in 951 corpus instances
  - other blocks sit directly on top
- **Ports.** Each port is the cell just outside the back (z = −1) or front (z = 2) face. Back = inputs, front = outputs,
  except Datameter, Fader, Remapper and Data Hub, which have everything on the front, and the Addition Array,
  whose front has 3 inputs and the output. The game numbers ports back face first, then front face, each in
  ascending x. The Condition and Data Redirector 3 wiring frequencies confirm the direction.
- **Orientation code k** = 4 × facing + spin. Facing is where the part's local +z, its front, points:
  0–3 → +x, 4–7 → −x, 8–11 → +y, 12–15 → −y, 16–19 → +z, 20–23 → −z.
  - The full rotation table is in `orientations.json`. 16 is the identity; parts in the rosetta sit on the floor at 16.
  - After rotation, the origin is the rotated footprint's min corner.
- **Cables.**
  - Each cell has a shape byte (setting byte 1): **0 = straight**, open at local ±z; **1 = corner**, open at local +y and +z.
    In the corpus, 91% of straight cells and 76% of corner cells have neighbours at exactly those faces.
  - Adjacent cells connect only when both open toward each other. A cable joins a port when the cable in the port cell
    opens toward the part.
  - With this rule, every corpus network joins at most 2 ports, and **all 2,730 two-port networks join an input to
    an output**.
- The third byte, shared by all structs (`a02a12ac78f009a6`, on 47 of 48 types; frames lack it but have nine 1-byte
  fields of their own), varies on every part type. It does **not** change geometry: corner-cable open faces and part
  port cells are the same for every value. Its name, `_col`, confirms it is paint.

## Text direction (the user: "many labels allow you to rotate the text direction 180 degrees")
- Field `0ebcc5a8415a16fe` is present **only** on the 11 structs that carry a LABEL. Its first byte is 0 or 1, the
  "text rotated 180°" switch.
- **Declared sizes can overlap.** 16fe is declared 4 B, but the next field can start 3 bytes later. In the Wireless
  Transmitter record its "4 bytes" read `00 00 00 54`, where `54` is the T of "TARGET". Treat 16fe and similar
  flags (e.g. Datameter `…bcaa`) as 1-byte values, and never write a declared width blindly.

## Mirroring: decoded from the user's "mirror test" (2026-10-02)
- The blueprint held four Remappers, one normal and three mirrored, each with a stub on its input. Two have the
  normal hash `f45687f85cf62f59`; two have a **different part hash, `5969bb0edf8607bc` (Remapper, mirrored twin)**.
  Settings are byte-identical, and there is no mirror flag anywhere.
- **Rule: a mirrored part is its twin type**, whose ports are the normal ports reflected along the part's local x
  (dx → w−1−dx), placed with an ordinary orientation code. All four stubs land exactly on the input this predicts.
  Mirroring twice gives a plain rotation of the normal type; one copy was the normal Remapper at orientation 21.
- For these 1-cell-tall blocks the twin at code k has the same port cells as the normal part spun 180° about its
  facing axis, i.e. upside down. So the generator can use only normal parts, at the cost of some sitting upside down,
  or use twins where known to keep everything upright.
- **All twins mapped from "rosetta M"** (rosetta stacked four times: normal, then mirrored on x, y and z, in the user's
  axis names). `decode_rosetta_m.py` writes `mirrored_hash` into `partdb.json` for all 43 parts. The frame's twin is
  `64acc8852709fb29`; Labels have no twin.
  - mirror x → twin types, same orientation (16)
  - mirror y → normal types turned 180° (orientation 21)
  - mirror z → normal types upside down (orientation 17)
  - Every cable stub in all four layers, 480 of 480, lands on the predicted port.
- **Heights:** Data Hub and Wireless Transmitter are **2 cells tall** (flipped, their origin drops a cell). Everything
  else is 1. Footprints must include height when re-anchoring after rotation.
- The corpus statistics above are unaffected: twins were unknown hashes and so were left out.

## Logic-part settings (read from the game code, 2026-10-02)
Sources: the per-part tick jobs (`SCTick_<Part>+OwnJob/ActiveJob.Execute` in `lib_burst_generated.dll`), the
`FromBinary` / `BlueprintData..ctor` converters, the knob step counts on the prefabs
(`EPC_Actionable_Knob._roundingIntervals`, via `prefab_dump.py`), and the mode names in Localization.csv.
A knob's position v in [0, 1] selects step `clamp(floor(v * steps), 0, steps - 1)`. The game writes v back as
`(step + 0.5) / steps`, or `mode / (steps - 1)` for mode bytes.

| Part | Field | Encoding |
|---|---|---|
| Constant | `_value` f32 | the output value |
| Simple Threshold | `_value` f32 | out = in ≥ value |
| Condition | `_mode` u8 | 0 Equal, 1 Not Equal, 2 Less, 3 Less Equal, 4 Greater, 5 Greater Equal (A op B). Equal is approximate: \|A−B\| < max(1e-6·max(\|A\|,\|B\|), 2^-20). Unwired True = 1, False = 0. |
| Round | `_mode` u8 | 0 Floor, 1 Round (half away from zero), 2 Ceil. Default 1. |
| Memory | `_mode` u8 | 0 Continuous (stores while Set ≥ 0.5), 1 Pulse (stores on a rising edge across 0.5) |
| Accumulator | `_mode` u8 | adds the input every tick, then 0 Continuous (zeroes while Reset ≥ 0.5) or 1 Pulse (zeroes on a rising edge) |
| Delay | `_rotKnobValue` f32 | 60-step knob. N = step + 1 ticks (1–60), the block's own tick included: a 60-slot ring buffer read `step` slots back. Write `(N − 0.5) / 60`. |
| Differentiator | `_rotKnobValue` f32 | 12-step knob, intervals [1,2,3,4,5,6,10,12,15,20,30,60] ticks. Every interval: out = in − in_at_last_update, held in between. Write `(i + 0.5) / 12`. |
| Initializer | `_ticks` u16 | the knob step itself (60 steps, 0–59). Outputs 0 while the local tick < ticks. |
| Remapper | `_value0..3` f32 | in_min, in_max, out_min, out_max; t = clamp((in − v0)/(v1 − v0), 0, 1), out = v2 + (v3 − v2)·t. If \|v1 − v0\| < 1e-9: out = in < v0 ? min(v2,v3) : max(v2,v3). |
| Fader | `_lever` f32 | out = in × lever (continuous 0..1, default 1). An unwired input reads 1. |
| Datameter | `_inputSwitch` u8 | display only: float vs integer (the user) |
| Data Hub | `_channel` u8 | selected input 0–4 |
| Wireless Transmitter | `_channel` i32 | 0–99 (its lever has 100 steps) |

Every data output is clamped to ±1e20, and inputs above 1e20 or NaN read as 0.
`engine.js` follows all of this. It keeps its own encodings for Condition (aupbuilder's `op`) and Round (0 round,
1 floor, 2 ceil), and the generator maps them to the bytes above.

## Wiring rules (from the user, 2026-10-02); data and power behave the same
1. A cable cell is straight or one 90° bend (shapes 0/1 above).
2. A cable cell connects to at most two other cells (cables are simple paths; branching needs a router).
3. Cables can't cross each other.
4. Only one cable of any kind per cell.
5. Every cable must be **supported**, by a compatible port it connects to (a power port can't support a data cable) or
   by an adjacent frame. Unwelded frames only support cables at certain points; welded frames presumably on all faces.
6. **Reach:** at most 11 cells from a supported side, i.e. 10 past the last supported cell.
   - A port-to-port cable is supported at both ends. Keep every cell within 10 cells of a supported end; up to 21
     cells is then safe.
   - A cable supported at only one end (the edge stubs for substituted parts) can be at most 11 cells long.
7. **Directly adjacent compatible ports connect without a cable.** They connect when A's port cell is B's
   face cell at one of B's ports, and B's port cell is A's face cell.
   - Confirmed in the corpus with `model.py`: 1,873 face-to-face contacts join an output to an input, against 2
     output-to-output and no input-to-input. Wireless Transmitter contacts show up as "both" (1,490 with an input,
     372 with an output, each counted twice for tx/rx).
   - So direct contact is about as common as cabling (2,730 cabled pairs).
Generator corollaries:
- Use face-to-face contact for direct links. It's the densest wiring possible.
- **Never let unrelated ports touch.** An output facing an input it isn't meant to drive is a real connection (and an
  input accepts only one driver). A port face against a non-port face is fine, but it blocks that port.
- A route must not pass through another part's port cell, where it could connect or block.
- Cables may lie side by side; they connect only through open faces.

## Still needed before a blueprint can be generated
1. ~~part hashes~~, ~~footprints and ports~~, ~~orientation table~~, ~~cable connectivity~~, ~~mirroring~~,
   ~~hash scheme~~ (done, above)
2. ~~load tests~~: all three load.
3. ~~Settings encodings~~ (done: "Logic-part settings").
4. Footprints of `SC_LabelSmall` and `SC_LabelMedium`, used for the edge annotations.
5. Port cells of `SC_FrameQuarterPorts` and `SC_FrameQuarterPortsCorner`: derive them from their 5,000 corpus
   instances.
6. Anchoring: does every cable cell need to touch a block (the "cable cells are not anchored" error)?
