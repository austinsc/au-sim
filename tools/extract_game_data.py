"""Extracts what the circuit simulator takes from the game install:

  tools/icons.json      64px PNG data URIs of each part's inventory icon (SC_<Part> textures)
  tools/part_text.json  each part's in-game name, description and per-port text (Localization.csv)
  game-reference/icons/ the full-size icon PNGs

The type_id -> game part mapping (and the game's port order) comes from engine.js,
so this script asks Node for it. Requires UnityPy (pip install --user UnityPy).
Reads the game install, never writes to it. tools/sync-simulator.js injects both
JSON files into circuit-simulator.html.

Run after a game update:  python tools/extract_game_data.py && node tools/sync-simulator.js
"""
import base64
import csv
import io
import json
import os
import re
import subprocess

import UnityPy
from PIL import Image

GAME = r'C:\Program Files (x86)\Steam\steamapps\common\Approximately Up\ApproximatelyUp_Data'
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON_DIR = os.path.join(ROOT, 'game-reference', 'icons')
SIZE = 64


def engine_parts():
    script = ("const {TYPES}=require('./engine.js');"
              "const o={};for(const[t,d] of Object.entries(TYPES))o[t]={game:d.game,order:d.order||null,shared:d.sharedPort||null};"
              "process.stdout.write(JSON.stringify(o));")
    return json.loads(subprocess.check_output(['node', '-e', script], cwd=ROOT))


def clean(text):
    text = re.sub(r'</?(u|b|i)>', '', text)
    text = re.sub(r'<color=[^>]*>|</color>', '', text)
    return text.replace('{0}', 'N').replace('\\n', ' ').strip()


def part_text(parts):
    with open(os.path.join(GAME, 'StreamingAssets', 'Localization.csv'), encoding='utf-8') as f:
        rows = csv.reader(f)
        next(rows)
        en = {r[0]: r[1] for r in rows if len(r) > 1}
    out = {}
    for type_id, info in parts.items():
        g = info['game']
        entry = {'name': clean(en.get(f'SC_{g}_Name', g)), 'desc': clean(en.get(f'SC_{g}_Desc', ''))}
        if info['order']:
            entry['ports'] = {name: clean(en[f'SC_{g}_Port{i}'])
                              for i, name in enumerate(info['order']) if f'SC_{g}_Port{i}' in en}
            for ours, theirs in (info.get('shared') or {}).items():  # one game port split in two
                if theirs in entry['ports']:
                    entry['ports'][ours] = entry['ports'][theirs]
        out[type_id] = entry
    return out


def icons(parts):
    wanted = {'SC_' + info['game'] for info in parts.values()}
    found = {}
    for fn in ['sharedassets0.assets', 'resources.assets', 'globalgamemanagers.assets']:
        env = UnityPy.load(os.path.join(GAME, fn))
        for obj in env.objects:
            if obj.type.name != 'Texture2D':
                continue
            try:
                name = obj.peek_name()
            except Exception:
                continue
            if name in wanted and name not in found:
                found[name] = obj.read().image

    os.makedirs(ICON_DIR, exist_ok=True)
    result, missing = {}, []
    for type_id, info in sorted(parts.items()):
        img = found.get('SC_' + info['game'])
        if img is None:
            missing.append(type_id)
            continue
        img = img.convert('RGBA')
        img.save(os.path.join(ICON_DIR, f"SC_{info['game']}.png"))
        bbox = img.getbbox()  # trim transparent margins so the icon fills its slot
        small = img.crop(bbox) if bbox else img
        small.thumbnail((SIZE, SIZE), Image.LANCZOS)
        canvas = Image.new('RGBA', (SIZE, SIZE), (0, 0, 0, 0))
        canvas.paste(small, ((SIZE - small.width) // 2, (SIZE - small.height) // 2))
        buf = io.BytesIO()
        # 64-colour palette keeps the page small; the icons are flat-shaded so this is lossless to the eye
        canvas.quantize(colors=64, method=Image.Quantize.FASTOCTREE).save(buf, 'PNG', optimize=True)
        result[type_id] = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
    return result, missing


def write_json(path, data):
    with open(path, 'w', encoding='utf8', newline='\n') as f:
        json.dump(data, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write('\n')


def main():
    parts = engine_parts()
    text = part_text(parts)
    write_json(os.path.join(ROOT, 'tools', 'part_text.json'), text)
    print(f'{len(text)} parts of in-game text -> tools/part_text.json')
    icon_map, missing = icons(parts)
    write_json(os.path.join(ROOT, 'tools', 'icons.json'), icon_map)
    print(f'{len(icon_map)} icons, {sum(map(len, icon_map.values())) // 1024} KB -> tools/icons.json')
    if missing:
        print('no game icon for:', ', '.join(missing))


if __name__ == '__main__':
    main()
