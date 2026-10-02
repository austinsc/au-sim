# Frames, glass and windows: shapes, welding and properties (2026-10-02)

`python tools/bp/extract_structure.py` writes:
- **`parts/structure_meshes.json`** (54 parts): properties, collider shape, weldable faces and their meshes, render
  meshes and attachment areas, plus the joint strength tables.
- **`meshes/<prefab>.obj`**: one OBJ per part, for a 3D viewer. Its groups are `collider_*`, `face<i>_gappy_*` /
  `face<i>_solid_*` (each weldable face unwelded and welded) and `render_*`.

**Coordinates:** grid cells from the part's minimum corner at orientation code 16 (identity), so a quarter spans 0..4
on each axis. Prefab space is metres from the part's centre: cell = m / 0.125 + size / 2.

## Welding (the user, 2026-10-02; the game's own descriptions agree)
- A weld covers one whole face. It makes the part stronger and heavier, and welding every face doubles the part's
  mass. Every frame's in-game description says "Fully welded frame weighs twice as much!".
- **Interior face:** not connected to another part, and facing the ship's interior volume.
  **Exterior face:** not connected, on the outside of the ship.
- A face partly covered by another part still needs welding if it is interior or exterior.
- One side can hold two coplanar faces, each welded on its own. Examples: Frame Full's 8×8 sides are two triangles,
  and Frame Full Curved 1 has a 2-face slope and a 2-face back. Each face's bit is its index in the frame's
  `_faceSetupData` (bit i of `_solidFaces`, paint slot `_col<i>`).
- **Weld mass, inferred:** the runtime `FaceData` carries a `_surfaceFraction`, and `SCTypeFrame` a
  `_fullSolidMass`. The likely rule is welded mass = unwelded mass × (1 + the sum of the welded faces' fractions),
  which gives 2× with every face welded.
  - `faces[].surface_fraction` in the JSON is each face's area share; the shares sum to 1.
  - The game code has not been checked for this formula.

## Shapes
"Curved" parts are angular. Every corner of their colliders lies on the grid, and every non-grid face is built from
two diagonals, 1:1 (45°) and 1:2 (26.6°; the user calls it 30°). There are five slope orientations:

| slope | angles to the grid planes | parts |
|---|---|---|
| 1:1 ramp | 0 / 45 / 45 | Quarter Curved 2, 3, 5; Half Curved 3, 4, 5; Full Curved 5 |
| 1:2 ramp | 0 / 26.6 / 63.4 | Full Curved 1, 3, 5, 7; Half Curved 1, 3, 4, 6, 8; the curved windows |
| corner, 1:1:1 | 35.3 / 35.3 / 35.3 | Quarter Curved 1 and 4 |
| corner, 1:1:2 | 24.1 / 24.1 / 54.7 | Full Curved 2 and 6 |
| corner, 1:2:2 | 19.5 / 41.8 / 41.8 | Half Curved 2 and 7 |

Quarters, as cell corners at orientation 16:
- **Curved 1** (FrameQuarterB): a corner tetrahedron, 1/6 of the cube. Corners (4,4,0), (0,4,0), (4,0,0), (4,4,4).
- **Curved 2** (C): a 45° wedge, half the cube. The slope runs from the y=0, z=0 edge to the y=4, z=4 edge.
- **Curved 3** (D): five corners, two 45° slopes.
- **Curved 4** (E): the cube minus Curved 1, i.e. one corner cut off.
- **Curved 5** (F): seven corners, two 45° slopes.
- Halves and fulls are the same family stretched to 4×8×4 and 8×8×4. `shape.polygons` in the JSON lists every
  face with its normal and corners.

**Glass matches frames by letter.** GlassQuarterB has exactly FrameQuarterB's collider ("Curved 1" in both names),
and the same holds for every glass quarter, half and full. Glass has no weldable faces.

## Properties (unwelded)

| part | size | mass kg | joint material | strength |
|---|---|---|---|---|
| Frame Quarter / Half / Full (A) | 4×4×4 / 4×8×4 / 8×8×4 | 11 / 17 / 25 | Iron | 800 |
| Frame Quarter Curved 1–5 (B–F) | 4×4×4 | 4, 8, 6, 10, 10 | Iron | 800 |
| Frame Half Curved 1–8 (B–I) | 4×8×4 | 12, 9, 9, 9, 12, 12, 15, 15 | Iron | 800 |
| Frame Full Curved 1, 2, 3, 5, 6, 7 (B, C, D, F, G, H) | 8×8×4 | 17, 9, 14, 14, 23, 23 | Iron | 800 |
| Frame Quarter With Pipe / With Ports / Ports Corner | 4×4×4 | 17 / 16 / 16 | Iron | 800 |
| Glass Quarter / Half / Full (A) | as frames | 21 / 33 / 50 | Glass | 750 |
| Glass Quarter Curved 1–4 (B–E) | 4×4×4 | 8, 15, 12, 19 | Glass | 750 |
| Glass Half Curved 1–7 (B–H) | 4×8×4 | 23, 12, 18, 18, 23, 18, 30 | Glass | 750 |
| Glass Full Curved 1, 2, 3, 6 (B, C, D, G) | 8×8×4 | 34, 18, 27, 45 | Glass | 750 |
| Windows (Middle, End, Porthole, Corner; curved 8×8×8) | | 35, 39, 45, 24 | Iron | 800 |
| Decoupler Small | 4×4×4 | 80 | (none) | |

- Every part has buoyancy 0.7 and linear slowness 2.5.
- Max temperature (`_maxTemperature`): code 1 = 300 °C, every iron part; code 2 = 600 °C, glass and the decoupler
  (the user, 2026-10-02). The JSON has both `max_temperature_code` and `max_temperature_c`.
- Also recorded: `sc_group` (1 frames, 2 glass), `categories`, `ui_preview_bounds` and the port frames' 8 electric
  ports (position, direction 4 = +z / 5 = −z, type 5 = universal).

## Joint strength (game code)
- Parts join through their attachment areas (`SpaceshipComponentAreaPoly`, the `JointsArea*` children). Each area
  has a joint type and a material.
  - Frames use Normal / Iron. Glass uses Normal / Glass, so glass joins frames as Normal–Normal.
- **`SpaceshipJointExtension.MATERIALS`**, from the class's static constructor, gives (strength, force distribution)
  per material:

  | material | code | strength | force distribution |
  |---|---|---|---|
  | Iron | 0 | 800 | 0.62 |
  | Batteries | 1 | 6000 | 0.54 |
  | Nano | 4 | 2500 | 0.48 |
  | Glass | 5 | 750 | 0.94 |

- **Joint types:** Normal 0, Pipe 1, PipeDecoupling 2, Decoupler 3, Glass 4.
- **`SpaceshipJointTypeConnections[a*5+b]`** is read by `GetConnectionStrength`. It is probably the 0/1 table below,
  the only 25-float block among the compiler-generated array data that fits. It is not yet confirmed.

  ```
          Nor Pip PDc Dec Gla
  Normal   1   0   0   1   0
  Pipe     0   1   0   0   0
  PipeDec  0   0   0   0   0
  Decoupl  1   0   0   1   0
  Glass    0   0   0   0   1
  ```

- A joint accumulates over its contact (`IncrementingJoint`: `_areasSum`, `_strengthSum`, `_forceDistributionSum`),
  so strength grows with contact area.
- How welding raises strength is not decoded yet. It is probably through the welded faces' attachment area; the
  cable-anchoring code already treats a welded face as solid everywhere and a bare face only along its edges.

## Open
1. **Weld mass:** confirm the formula (`_surfaceFraction`, `_fullSolidMass`) in the Burst code.
2. **Welding and strength:** find out how welding feeds the joint strength.
3. **Connection table:** confirm it against `GetConnectionStrength`'s callers.
