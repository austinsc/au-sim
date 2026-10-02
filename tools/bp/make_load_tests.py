"""Builds three load-test blueprints to check the writer against the real game.

  A  "Height Control" cloned through bpformat with fresh part ids (otherwise byte-identical)
  B  the same clone with two labels rewritten (TARGET -> AU-SIM, TARGET HEIGHT -> AU-SIM TEST OK)
  C  built from scratch: three straight data-cable runs along x (7 cells), y (5) and z (3)
     that don't touch, to check the cable part hash, the x/y/z cell encoding and which way
     each axis points in-game

Writes <guid>.bp + <guid>.bpmeta to blueprints/load-test/ and, with --install, copies them
into the game's Blueprints folder (new files only; nothing existing is touched).
Usage: python tools/bp/make_load_tests.py [--install]
"""
import json
import os
import shutil
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
import bpformat  # noqa: E402

GAME_BP = os.path.expandvars(r'%USERPROFILE%\AppData\LocalLow\ApproximatelyGames\ApproximatelyUp\Blueprints')
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 'blueprints', 'load-test')
SOURCE = 'c80a4975-88f3-446f-9968-0443d3701b02'   # "Height Control" (folder Parts)
NEWEST = 'autosave'                               # newest schema/version on disk
CABLE = 0xe60658e2e04f33ce                        # suspected data cable cell
FOLDER = 'au-sim'


def load(name):
    with open(os.path.join(GAME_BP, name + '.bp'), 'rb') as f:
        schema, parts = bpformat.read(f.read())
    with open(os.path.join(GAME_BP, name + '.bpmeta'), encoding='utf-8') as f:
        meta = json.load(f)
    return schema, parts, meta


def save(schema, parts, name, version):
    guid = str(uuid.uuid4())
    data = bpformat.write(schema, parts)
    bpformat.read(data)  # must parse back cleanly
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, guid + '.bp'), 'wb') as f:
        f.write(data)
    with open(os.path.join(OUT, guid + '.bpmeta'), 'w', encoding='utf-8', newline='') as f:
        f.write(json.dumps({'_name': name, '_folder': FOLDER, '_version': version}, separators=(',', ':')))
    return guid, len(parts), len(data)


def main():
    made = []
    schema, parts, meta = load(SOURCE)

    # A: clone, fresh ids
    a = [bpformat.with_new_guid(x) for x in parts]
    made.append(('A', 'au-sim A clone', save(schema, a, 'au-sim A clone', meta['_version'])))

    # B: clone, fresh ids, two labels rewritten
    relabel = {'TARGET': 'AU-SIM', 'TARGET HEIGHT': 'AU-SIM TEST OK'}
    b = [bpformat.with_label(x, relabel[x['label']]) if x['label'] in relabel else x for x in a]
    b = [bpformat.with_new_guid(x) for x in b]
    assert sum(1 for x in b if x['label'] in relabel.values()) == 2
    made.append(('B', 'au-sim B labels', save(schema, b, 'au-sim B labels', meta['_version'])))

    # C: from scratch. Template = a straight cable cell from the newest save, re-indexed into
    # the newest schema. Straight runs in saves use orientation 5 along x, 12 along y, 16 along z.
    nschema, nparts, nmeta = load(NEWEST)
    template = next(x for x in nparts if x['part'] == CABLE)
    struct_hash = nschema[template['schema']]['hash']
    tdata = bytearray(template['data'])
    for fh, (off, sz) in template['fields'].items():   # zero every setting byte (paint etc.)
        if fh not in (bpformat.F_GUID, bpformat.F_CELL):
            tdata[off:off + sz] = bytes(sz)
    template = dict(template, data=bytes(tdata))
    assert nschema[template['schema']]['hash'] == struct_hash
    o = 240
    cells = [(o + i, o, o, 5) for i in range(1, 8)] + \
            [(o, o + i, o, 12) for i in range(1, 6)] + \
            [(o, o, o + i, 16) for i in range(1, 4)]
    c = [bpformat.with_new_guid(bpformat.with_cell(template, *cell)) for cell in cells]
    made.append(('C', 'au-sim C axes', save(nschema, c, 'au-sim C axes', nmeta['_version'])))

    install = '--install' in sys.argv
    for tag, name, (guid, n, size) in made:
        where = os.path.join(OUT, guid)
        if install:
            for ext in ('.bp', '.bpmeta'):
                dst = os.path.join(GAME_BP, guid + ext)
                assert not os.path.exists(dst)
                shutil.copyfile(where + ext, dst)
        print(f'{tag}  "{name}"  {n} parts, {size} bytes  {guid}' + ('  (installed)' if install else ''))


if __name__ == '__main__':
    main()
