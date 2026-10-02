'use strict';
// Injects engine.js, circuits/planet_hop_v2.json, tools/icons.json, tools/part_text.json and the blueprint
// generator (bpdata.js + bpgen.js) into circuit-simulator.html,
// so the single-file simulator always runs the same engine the tests cover.
// Run after editing engine.js or the demo circuit:  node tools/sync-simulator.js
// Pass --check to fail (exit 1) instead of writing when the page is out of date.
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const htmlPath = path.join(root, 'circuit-simulator.html');
const html = fs.readFileSync(htmlPath, 'utf8');

const engine = fs.readFileSync(path.join(root, 'engine.js'), 'utf8').trim();
const demo = JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, 'circuits', 'planet_hop_v2.json'), 'utf8')));

function replaceBetween(src, begin, end, body) {
  const re = new RegExp(`(/\\* ${begin}[^*]*\\*/)[\\s\\S]*?(/\\* ${end} \\*/)`);
  if (!re.test(src)) throw new Error(`markers ${begin} / ${end} not found in circuit-simulator.html`);
  return src.replace(re, (_, a, b) => `${a}${body}${b}`);
}

// In-game part icons, extracted from the game install by tools/extract_icons.py.
const icons = JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, 'tools', 'icons.json'), 'utf8')));
// In-game part names, descriptions and port text, extracted by tools/extract_game_data.py.
const partText = JSON.stringify(JSON.parse(fs.readFileSync(path.join(root, 'tools', 'part_text.json'), 'utf8')));

let out = replaceBetween(html, '@@ENGINE_BEGIN', '@@ENGINE_END', `\n${engine}\n`);
out = replaceBetween(out, '@@DEMO_BEGIN', '@@DEMO_END', ` ${demo} `);
out = replaceBetween(out, '@@ICONS_BEGIN', '@@ICONS_END', ` ${icons} `);
out = replaceBetween(out, '@@PARTTEXT_BEGIN', '@@PARTTEXT_END', ` ${partText} `);
// The blueprint generator and its data, run in a worker by the Blueprint panel.
const bpgen = fs.readFileSync(path.join(root, 'bpdata.js'), 'utf8').trim() + '\n' + fs.readFileSync(path.join(root, 'bpgen.js'), 'utf8').trim();
if (bpgen.includes('</script')) throw new Error('bpgen.js or bpdata.js contains a closing script tag');
out = replaceBetween(out, '@@BPGEN_BEGIN', '@@BPGEN_END', `\n${bpgen}\n`);

if (process.argv.includes('--check')) {
  if (out !== html) { console.error('circuit-simulator.html is out of date — run: node tools/sync-simulator.js'); process.exit(1); }
  console.log('circuit-simulator.html is up to date');
} else {
  fs.writeFileSync(htmlPath, out);
  console.log(out === html ? 'circuit-simulator.html already up to date' : 'circuit-simulator.html updated');
}
