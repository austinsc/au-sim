# Blueprint generator — spec (from the user, 2026-10-02)

Turns a simulator circuit into an in-game `.bp` + `.bpmeta` the user downloads and loads.
Format and part data: see `NOTES.md`, `partdb.json`, `model.py`.

## Phase 1: logic/data parts only
**Included parts.** Only parts the size of a Data Router 4 (4 × 1 × 2 cells) or smaller. Every other part in the
circuit, including the Data Hub (6 × 2 × 2) and all sensors, controls and actuators, is **substituted**: its
connection becomes a cable that runs to the blueprint's outer surface and ends beside a label saying what to
connect there.

**Hard rules (the game's):**
1. Cables: one per cell, of any kind. Each cell is straight or one 90° bend, connects to at most two cells, and never
   crosses another cable.
2. Every cable is supported by a compatible port it connects to or by an adjacent frame. It reaches at most 11 cells
   from a supported side. A port-to-port cable can run up to 21 cells; a stub held at one end, at most 11.
3. Compatible ports in direct face-to-face contact connect without a cable. Unrelated ports must never touch.
   A port covered by a plain face is blocked, so only unused ports may be covered.
4. Every part is supported by a frame or another part, by stacking (face contact) or by port-to-port contact.
   The whole design is one connected structure.

**Goals, in priority order:**
1. **Fewest frame quarters.** The frame quarter (`482074ef572f3723`) is a 4 × 4 × 4 cube on a 4-cell grid. Minimise
   the number of grid cubes the design occupies.
2. **Fewest cable cells.** Prefer direct port contact, then the shortest legal route.
3. **I/O sides.** Inputs on one face and outputs on the opposite face, or all I/O on one face, wherever possible.
4. Keep parts upright where possible; mirrored twins give reversed port order without flipping a part over.

**Options:**
- **Glass-encased:** tile the logic volume with 4 × 8 × 4 glass blocks (`83430f870bdfacbf`) that overlap the logic,
  with only the I/O cable ends and their labels outside. Example: "Better Than PID. No tuning required".
  **Double-encased:** the same with a 4 × 8 × 4 frame (`65ba6e9a45f600d0`) in the same volume as each glass block.
  The frame presumably supports the parts and cables. Example: "Universal flight computer. Plug and play by Santxc",
  with three of each.
- **Port-frame termination:** run the loose cable ends through a **Frame Quarter With Ports** (4 universal ports on
  each of two opposite faces, passing through the wall) or a **Frame Quarter With Ports Corner** (the same ports,
  turned 90° to an adjacent face). Standardises connections and supports them through walls.

## Phase 2
Any part the simulator has, not just logic/data, so it needs hashes, footprints and ports for sensors, actuators,
power parts and so on.

## Part ids
The hash scheme is solved (`hashes.py`; NOTES.md, "Hash scheme"), so any part's id comes from its prefab name:

| Part | Prefab | Hash |
|---|---|---|
| Frame Quarter With Ports | `SC_FrameQuarterPorts` | `18d3ed13f664ec3f` (twin `731e5443f167d667`) |
| Corner variant | `SC_FrameQuarterPortsCorner` | `ebc0272a6795bc6c` (twin `50d4412d3c4bbed3`) |
| Label, Large Label | `SC_LabelSmall`, `SC_LabelMedium` | `30dd685b29b0b3a1`, `7cfa59e0d07dcb3e` |
| Data cable | `SC_DataCable` | `e60658e2e04f33ce` |
| Power cable | `SC_PowerCable` | `743531fcd428bc2c` |
| Plasma cable | `SC_PlasmaCable` | `e8f9b8dac4e23b9c` |

All three cables share `EPC_SCCable`.

Schema entries come from `schemas.json`, so a generated file needs no template blueprint.

## Still to identify before the options can be built
- the port cells of the two port frames (from their corpus instances)
- what welding changes about cable support on a frame

## Implementation (v1, 2026-10-02)
- **Code:**
  - `bpgen.js` is the generator; `bpdata.js` is its data, built by `tools/bp/build_bpdata.py`.
  - The same code runs in Node and in the simulator page. There it sits in the Blueprint panel, inside a Web Worker;
    `tools/sync-simulator.js` injects it.
- **CLI:** `node tools/make_blueprint.js circuit.json [--name N] [--folder F] [--install] [--jobs N] [--seeds N]
  [--budget-ms N] [--io bundle|split|free] [--box XxYxZ] [--stripes] [--no-sink-stubs]`
  - It writes `<guid>.bp`, `.bpmeta` and `.layout.json` into `blueprints/generated/`.
  - `--install` copies the pair into the game's Blueprints folder as new files and never overwrites.
  - **Parallel search** (2026-10-02): worker threads (one per CPU, up to 16) try box × I/O mode × seed.
    - First they look for any layout, smallest box first, among boxes of at least 4× the parts' volume.
    - Then they work down from the best size found; every success lowers the bar.
    - The score is frame quarters × 1 for bundle, 1.15 for split and 1.4 for free, so the I/O comes out as one
      parallel group unless that costs over 40% more size.
    - Why: one attempt at a 40-part circuit succeeds only a few percent of the time, and the smallest boxes almost
      never.
    - Default budget 4 min. `--jobs 1` runs bpgen's own sequential search.
- **Placement:** simulated annealing on a cell grid inside cube-aligned boxes, tried fewest-cubes first.
  - All parts stay upright, facing ±x or ±z, normal or mirrored twin.
  - The cost counts:
    - wiring length, plus 2 per cabled link
    - stub distance to its face
    - blocked or unrelated touching ports (forbidden)
    - port cells with no free exit
    - parts that don't touch the rest
  - A "snap" move puts a part's port face to face with its partner's (direct contact), or one cell apart (a
    1-cell cable).
  - The initial placement chains each part onto a driver already placed.
- **Routing:** PathFinder (negotiated congestion, A* per cable).
  - Used port cells are reserved for their own cable.
  - Cables are capped at 21 cells between two ports and 11 for an edge stub.
  - **Repair** (2026-10-02): a routing failure is structural, so more router iterations don't help. When routing
    fails, the placer instead:
    - marks the congested cells (shared cells, both ends of each cable with no path, over-long cables) at
      5 per cell, plus half that next to them;
    - re-anneals at a low temperature (a quarter of the steps) to push parts off those cells;
    - routes again, up to 4 times.
- **Stubs:**
  - Every wire to a part that isn't placed becomes a stub.
  - A part none of whose outputs feeds anything gets an output stub on each output.
  - Each stub ends beside its own **Label** (Large Label if the name needs 15–16 characters), painted like its stub.
    - Labels sit in the face layer the stub leaves through, text facing out, back resting on parts, inside the box.
    - Text is the source or target name in upper case, with characters other than A–Z 0–9 % + , - . / : replaced
      by spaces.
    - Labels don't count when checking that the parts touch, because a label hangs on its back face.
  - **I/O modes** (`opts.io`, 2026-10-02; the user wants the I/O as a group of parallel cables where possible):
    - **bundle:** every stub ends in one row on the −z face, inputs left, outputs right.
    - **split:** inputs in a row on −z, outputs in a row on +z.
    - **free:** the v1 layout. Inputs end anywhere on −z and outputs anywhere on +z, each beside its label.
  - **Rows:**
    - Each end cell is a straight cable opening out of the face. The goal cell just inside it is where the routed
      cable arrives.
    - Ends sit one label width apart (2 cells), with each label directly above or below its end. The label's
      first letter is over the end.
    - A row too wide for the box wraps onto further rows, 3 cells apart.
    - A row label needs at least half its back on parts. It is one plate held by its back, and the corpus has 14
      labels backed only partly.
  - **Placer moves for rows:**
    - Slide the whole row.
    - Swap two ends of the same kind.
    - Flip a label to the other side of its end.
    - Snap a stub's part so that its port opens onto its slot's goal cell. That makes a 2-cell stub, and the part
      can also hold up the label.
    - Rows are placed first, and the stub parts are snapped onto them before the rest.
  - **Search:** without `opts.io`, each box tries bundle, then split; free is the last resort.
- **Paint** (2026-10-02, at the user's request; the v1 colour-by-function scheme was "too crazy"):
  - Every logic part and internal cable is black.
  - Input cables and their labels are green; output cables and their labels red.
  - `opts.stripes` gives internal cables per-cable accent stripes again (off by default).
- **Settings:** written from the simulator params (NOTES.md, "Logic-part settings"). The Condition op and the Round
  mode are translated to the game's bytes, and a Datameter's title is its instance id.
- **Checks:** two independent checks.
  - The generator re-derives every connection from the cells it emits.
  - `tools/bp/verify_bp.py <bp> <circuit>` re-reads the file with the Python decoder and compares the netlist,
    overlaps, reach and touching. Like the generator, it accepts a label at least half backed and notes it.
- **Results** (2026-10-02, parallel search):
  - `gen_test_settings` (29 parts, 9 stubs): bundle in 6 frame quarters (12×8×4), 16 s. v1 needed the same size.
  - `raster_sweep_v3` (38 parts, 10 stubs):
    - split in 12 frame quarters (12×8×8); free also reaches 12;
    - bundle needs about 20 (its outputs, at the end of the signal chain, have to come back to the input face);
    - v1 reached 14 after 212 s.
