# au-sim

Flight-computer tools for the game *Approximately Up*. The project has three parts:
- a browser circuit simulator with a game-accurate engine;
- a generator that turns simulator circuits into in-game blueprints;
- the circuits themselves, including a planet-hop autopilot and a scanner target lock.

**Simulator:** https://austinsc.github.io/au-sim/. It is one self-contained page, so you can also open
`circuit-simulator.html` locally. To load a circuit, click **Import** and pick a file from `circuits/`.

| Path | What it is |
|---|---|
| `circuit-simulator.html` | The simulator. It embeds `engine.js`, `bpgen.js` and `bpdata.js`; re-embed them with `node tools/sync-simulator.js`. |
| `engine.js` | The circuit engine. Every block takes one game tick (60 per second), with the game's own block semantics. |
| `bpgen.js`, `bpdata.js` | The blueprint generator, which places parts, routes cables and adds labels and paint. |
| `tools/make_blueprint.js` | Command-line generator: `node tools/make_blueprint.js circuits/<file>.json [--install]` |
| `circuits/` | Circuits. `tools/build_*.js` generate them, and `tools/*_harness.js` fly them against simple physics models. |
| `tools/bp/` | The decoded `.bp` blueprint format, readers, writers and an independent blueprint checker (`verify_bp.py`). |
| `game-reference/` | Reference material taken from the game files: part icons, part text and the in-game manual. |
| `PROJECT_SUMMARY.md` | Project notes: game facts, circuit designs and their test results. |

Run the tests with `node --test` (Node 20 or later).

This is a fan project, not affiliated with the developers of *Approximately Up*. The part icons and part text
come from the game.
