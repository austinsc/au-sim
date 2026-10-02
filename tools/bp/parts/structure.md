# Structure parts: labels, frames, port frames, glass, windows, decoupler

Output: `structure.json` (built by `build_structure.py`), validated by `validate_structure.py`. This file is the method,
the evidence and the open questions. Shared files (partdb.json, model.py, NOTES.md, ...) were not changed.

## Files (all in tools/bp/parts/)

| file | what |
|---|---|
| `structure.json` | the deliverable: 56 parts + `label_rules`, `frame_ports_rules`, `frame_support_rules`, `glass_encasing` |
| `structure_rules.json` | hand-written prose rules and per-part notes merged into structure.json |
| `build_structure.py` | builds structure.json (one corpus pass, about 2-4 min); writes atomically |
| `validate_structure.py` | independent check that uses only structure.json; writes `validate_structure_report.json` |
| `structure_prefabs.py` | reads prefab_dump.json: size, JointsArea polygons, colliders, ports, frame face lists |
| `structure_geom.py`, `structure_occupancy.py` | placement (model.py convention) and per-blueprint occupancy |
| `structure_corpus.py` | corpus loader that keeps names, struct hashes and raw settings bytes |
| `structure_cables.py` | cables that open toward a part, in its canonical frame |
| `structure_support.py` | per-contact statistics for cables lying against frames (`structure_support_stats.json`) |
| `structure_anchor.py` | network-level test of the cable anchoring rule (`structure_anchor_stats.json`) |

## Method

1. **Sizes from the prefab.** Each part's root `EPC_SC*` component (the `EPC_SpaceshipComponent` base) stores the
   part size in metres at bytes 12..23, and the mass at 24. Size / 0.125 m gives the footprint. This matches all
   43 sizes in partdb.json, so every structure size comes from there:
   - Labels: 2x1x1 and 4x1x1.
   - Frames, glass and windows: quarter 4x4x4, half 4x8x4, full 8x8x4, and some windows 8x8x8.
   - Decoupler: 4x4x4.
2. **Layouts read from the dump.** Each needed layout was decoded and checked against parts with known geometry.
   - `DOTSColliderBox` holds centre[3], euler[3], size[3] and bevel. The task brief listed a leading u32, but there
     is none.
   - `SpaceshipComponentAreaPoly` ("JointsArea") holds a joint type, a material, n and n vertices. These are the
     faces a part can attach through.
   - The port list in the root component is n x (position[3], face code, port type). The port types are:
     0 data in, 1 data out, 2 power, 3 wireless both, 4 plasma, 5 universal.
   - The frame `FaceSetupData` list holds, per face, PPtr gappy mesh, PPtr solid mesh, 4 vertices and a vertex
     count.
3. **The corpus.** The study used 301 deduplicated blueprints (307,224 parts).
   - Origins follow model.py: the stored origin is the min corner of the rotated footprint. For frames this was
     re-checked: all 9,630 frame-quarter-type instances share one 4-grid residue per blueprint, across all their
     orientations.
   - Footprints were checked by overlap.
   - Ports were checked with cables that open toward the part, using the open-face rule from networks.py.
   - Twins were checked with the x reflection.
4. **Burst code.** Two functions in `burst.asm` were read:
   - `SCTick_FrameWithPorts+SharePortsValuesJob.Execute` (line 730713 ff.), for port pairing and chains.
   - `GarageUpdateCables.UpdateCellsAndPortsJob`, inlined in `ParallelForJobStruct<...>.Execute`
     (line 1050138 ff.), for the face loop, the weld bit and the 0.08 m edge test.

   The power study had already decoded the anchoring rule (power.md Q4). Its open question was the face list and the
   bit order, which this study answers.

## Results

### Labels (`label_rules`)
- **Footprint and attachment.** A label is a 0.02 m plate lying flush against its back face (local -z). The only
  JointsArea is on that face.
  - 1,059 of 1,063 Labels have their back cells occupied, 1,045 of them fully. The front (+z) is free in 1,046.
  - The 46 Large Labels with nothing behind them are all in the pasted modules.
- **Text direction.** Text faces +z, and its top is +y. `_labelRotated` = 1 turns the text 180° in the plate.
  - With the flag at 0, 743 of 795 vertical labels have local +y = world up.
  - All 13 flagged vertical labels have local +y = world down, so the flag is used to make upside-down placements
    upright.
  - Reading direction is local -x, so the first letter is at high x. The text renderer is euler (270, 180, 0) on the
    game's +y-facing text mesh, which is also used for the logic-block captions.
  - The corpus agrees: two-label names in "Universal flight computer" read naturally only from high x to low x, and
    the "Multiplexer" number labels only order 1..4 that way.
  - `orientation_table` gives front, up and reading direction for all 24 codes.
- **Text limits.** `EPC_Actionable_Label._maxLength` is 14 for the Label and 16 for the Large Label, which matches
  the corpus maxima. All 7,962 corpus text fields are upper case and zero-padded.
- **At cable ends**, in both glass examples (16 of 16 cases): one Large Label lies on the cable axis directly beyond
  the straight end cell. Its long axis runs along the cable, in the same layer. Neighbouring ends get one row each,
  and a long name continues with a second label further out.
- **On port frames** (372 corpus labels): four 2-cell Labels sit in the outer ring of the port face, next to the
  2x2 port block, one under or over each port: (0..1,0) A, (2..3,0) B, (2..3,3) C, (0..1,3) D.

### Port frames (`frame_ports_rules`)
- **Port cells.**
  - Straight variant: ports on the -z and +z faces, at x, y ∈ {1,2}.
  - Corner variant: ports on +x and +z.
  - Twins reflect x. The corner twin's side ports move to -x.
  - Corpus: 6,825 cable cells open toward the 5,169 port-frame instances (169 of them twins). Every cable lands on a
    predicted port cell and touches the predicted face cell, with 0 misses. All 8 ports are seen on both variants.
- **Pairing.** Port i is paired with port i+4: A0-A1, B0-B1, C0-C1, D0-D1. The job's loop reads `ownPorts[i]` and
  `ownPorts[i+4]`, and the prefab list order is A0 B0 C0 D0 A1 B1 C1 D1.
  - Corpus: when both ends of a pair carry cables, the two kinds match in 1,152 of 1,152 cases. Every other pairing
    mixes kinds 26–54% of the time.
  - In the corner variant, the +x port at (y, z) pairs with the +z port at (x = z, y).
- **Port type.** Every port is universal (type 5). Data and power both occur on all 8 positions; plasma is not seen.
  - A pair passes values only when both of its ports are connected.
  - Chains of directly touching frame ports are followed frame by frame. The corpus has 13,760 such contacts.
  - Part ports can plug straight into frame ports (178 cases).

### Frame faces, welding and cable support (`frame_support_rules`)
- **`_solidFaces`** is a bit per face, and `_col0..7` is a colour per face (200 = unpainted). The faces are the
  prefab's FaceSetupData list, which is the FramePrefabFacesData the game loops over (`bt _solidFaces, faceIndex`).
  - Box frames: quarters and port frames are Y-, Y+, X+, Z+, X-, Z-. FrameHalfA is Z+, Y+, Y-, X+, X-, Z-.
  - FrameA has 8 faces, because each 8x8 face is two triangles.
  - Across 53,555 frame records, no bit at or past the face count is ever set, and every unused colour slot is 200.
- **Anchoring rule** (Burst; matches power.md):
  - Only straight cable cells probe, in the 4 directions perpendicular to their axis.
  - A probe tests the near face of the frame (back faces are culled), taking the first hit in face order.
  - The cell is anchored if that face's bit is welded, or if the hit point is under 0.08 m from one of the polygon's
    edge lines.
  - On a bare face, only the outer ring of cell positions anchors, plus the triangle diagonals on FrameA's 8x8 faces.
  - On a welded face, every position anchors, except a port frame's port positions.
- **Network test** (`structure_anchor.py`): the number of cable networks with a cell more than 10 steps from any
  anchor, under each model.

  | model | networks |
  |---|---|
  | ports only | 1,691 |
  | + edge rule | 44 |
  | **exact rule (FaceSetupData bit order)** | **39** |
  | old JointsArea bit order | 42 |
  | exact rule without the diagonals | 41 |
  | upper bound (any side contact) | 38 |

  The exact rule matches the upper bound except for one network in one autosave.
- **Bit order check.** The FaceSetupData order puts contacted faces on welded bits more often than 95.6–99.9% of
  all 720 face orderings (`structure_support.py`).
- **Twin faces.** Mirroring the twin's face list fits slightly better than not mirroring it (39 vs 40 networks).
  This is weak support only.

### Glass and frame halves, encasing (`glass_encasing`)
- **Size.** GlassHalfA and FrameHalfA are 4x8x4, 8 long along local y.
- **"Better Than PID".** One glass block at orientation 8 encloses 9 logic parts. 4 cable ends and 3 labels are
  outside.
- **"Universal flight computer".** Three glass blocks (orientations 8/12/8) and three frames (5/1/5) share exactly
  the same boxes and enclose 26 logic parts. One frame welds bit 3, its world floor. Glass `_col` is 15 in both
  blueprints.
- These overlaps are the deliberate glitch. The validator counts them separately from real collisions.

### Priority-2 parts
- **Box parts** fill their whole bounding box. These are FrameQuarterA, FrameQuarterPipe, the two port frames,
  FrameHalfA, FrameA, GlassA, GlassHalfA, GlassQuarterA, WindowDual/End/Round and the decoupler: 41,271 instances.
  Apart from the encasing glitch, no box part ever overlaps another part.
- **Curved parts** fill only the cells of the hull of their face polygons: the JointsArea polygons for glass and
  windows, whose curved surface is a convex mesh collider that is not in the dump.
  - Other parts occupy bounding-box cells only at least 0.5 cell outside that hull, and never on the sloped face.
  - The one exception is a single SC_DuctedFan design (3 blueprints) that runs through FrameB/FrameC.
- **Independent validator, using only structure.json:**
  - 0 unexplained overlaps in all 56 parts.
  - Port frames 8/8 and 8/8 ports confirmed, with 0 misses. The decoupler's port is 1/1 (59 cables).

## Open questions
1. **Label reading direction.** It is inferred from the prefab and supported by the corpus, but has not been seen in
   game. A one-label load test would settle it: write "AB" at orientation 16 and check that A appears at the high-x
   end.
2. **Plasma through port frames.** The code has a plasma port mesh, but there is no corpus case.
3. **Twin face lists.** Mirroring a twin's face list fits slightly better; this is weak support. It matters only for
   a weld on a twin's X+/X- faces and for FrameA twin diagonals.
4. **Curved glass and windows.** Their solid cells come from JointsArea hulls. The windows that are 8x8x8 have only
   1 to 12 instances each, so their confidence is low.
5. **The frame probe for curved frames** needs the real convex collider. `structure_anchor.py` uses bounding-box
   cells there.
6. **Joint materials.** JointsArea type/material codes (glass = 5, thrusters = 4, ...) set joint strength through
   `SpaceshipJointTypeConnections`. The table was not decoded.
7. **The SC_DuctedFan footprint** overlaps curved frames in one design, which is a question for the propulsion
   study.

See also `structure_meshes.md` (2026-10-02): the parts' meshes, slope shapes, weld faces and surface fractions, masses and joint strengths, extracted by `../extract_structure.py`.
