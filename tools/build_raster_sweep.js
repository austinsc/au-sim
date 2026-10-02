'use strict';
// Generates circuits/raster_sweep.json.  Run: node tools/build_raster_sweep.js
//
// Loop-free design, built for the game's 1-tick-per-component timing:
//   total     = Σ (yaw_step × enable)              one accumulator, never reset
//   yaw       = total mod range                    sawtooth 0 .. range-step
//   row       = floor(total / range)               increments on every yaw wrap
//   rows      = floor(span / pitch_step) + 1
//   pitch_cmd = (row mod rows) × pitch_step − span/2
//   yaw_cmd   = (yaw + offset) mod 360
// The yaw path is padded with two Data Routers so yaw and pitch leave the
// circuit on the same tick (both are 6 blocks downstream of the accumulator).
const fs = require('fs');
const path = require('path');

// [id, type_id, params, col, row]
const N = [
  ['in_yaw_step',   'slider', { value: 2 },   0, 0],
  ['in_enable',     'toggle', { value: 1 },   0, 1],
  ['in_yaw_range',  'slider', { value: 360 }, 0, 2],
  ['in_pitch_step', 'slider', { value: 20 },  0, 4],
  ['in_pitch_span', 'slider', { value: 120 }, 0, 5],
  ['in_yaw_offset', 'slider', { value: 0 },   0, 7],

  ['step_gated',    'multiplier', {}, 1, 0],
  ['range_router',  'data_router_2', {}, 1, 2],
  ['pstep_router',  'data_router_2', {}, 1, 4],
  ['span_router',   'data_router_2', {}, 1, 5],

  ['acc_total',     'accumulator', { mode: 0 }, 2, 0],
  ['total_router',  'data_router_2', {}, 3, 0],

  // yaw path: mod → pad → pad → +offset → mod 360
  ['yaw_raw',       'mod', {}, 4, 0],
  ['yaw_pad_1',     'data_router_2', {}, 5, 0],
  ['yaw_pad_2',     'data_router_2', {}, 6, 0],
  ['yaw_heading',   'adder', {}, 7, 0],
  ['const_360',     'constant', { value: 360 }, 7, 1],
  ['yaw_cmd',       'mod', {}, 8, 0],

  // pitch path: ÷ range → floor → mod rows → × step → − half span
  ['row_div',       'divider', {}, 4, 2],
  ['row',           'round', { mode: 1 }, 5, 2],
  ['pitch_idx',     'mod', {}, 6, 2],
  ['pitch_scaled',  'multiplier', {}, 7, 2],
  ['pitch_cmd',     'subtractor', {}, 8, 2],

  // row count and half span (constant-ish setup paths)
  ['rows_div',      'divider', {}, 2, 4],
  ['rows_floor',    'round', { mode: 1 }, 3, 4],
  ['const_one',     'constant', { value: 1 }, 3, 5],
  ['rows',          'adder', {}, 4, 4],
  ['const_two',     'constant', { value: 2 }, 2, 6],
  ['half_span',     'divider', {}, 3, 6],
];

const E = `
in_yaw_step.out step_gated.a
in_enable.out step_gated.b
step_gated.out acc_total.in
acc_total.out total_router.in
in_yaw_range.out range_router.in
total_router.a yaw_raw.a
range_router.a yaw_raw.b
yaw_raw.out yaw_pad_1.in
yaw_pad_1.a yaw_pad_2.in
yaw_pad_2.a yaw_heading.a
in_yaw_offset.out yaw_heading.b
yaw_heading.out yaw_cmd.a
const_360.out yaw_cmd.b
total_router.b row_div.a
range_router.b row_div.b
row_div.out row.in
row.out pitch_idx.a
rows.out pitch_idx.b
pitch_idx.out pitch_scaled.a
pstep_router.b pitch_scaled.b
pitch_scaled.out pitch_cmd.a
half_span.out pitch_cmd.b
in_pitch_step.out pstep_router.in
in_pitch_span.out span_router.in
span_router.a rows_div.a
pstep_router.a rows_div.b
rows_div.out rows_floor.in
rows_floor.out rows.a
const_one.out rows.b
span_router.b half_span.a
const_two.out half_span.b
`.trim().split('\n').map((l) => {
  const [f, t] = l.trim().split(/\s+/);
  const [from_instance, from_port] = f.split('.');
  const [to_instance, to_port] = t.split('.');
  return { from_instance, from_port, to_instance, to_port, color: '#e9c46a' };
});

const diagram = {
  instances: N.map(([id, type_id, parameters, c, r]) => ({
    id, type_id, parameters, position: { x: 40 + c * 230, y: 40 + r * 170 }, color: '#e9c46a', mirrored: false,
  })),
  edges: E, groups: [], max_per_column: 4, max_rows: 4, max_columns: 8,
};
fs.writeFileSync(path.join(__dirname, '..', 'circuits', 'raster_sweep.json'), JSON.stringify(diagram, null, 2) + '\n');
console.log(`raster_sweep.json: ${N.length} blocks, ${E.length} wires`);
