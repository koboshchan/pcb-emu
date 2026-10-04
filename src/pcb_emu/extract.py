#!/usr/bin/env python3
"""Copper-only connectivity. Never joins items by their assigned KiCad net code."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

pcbnew = None  # Loaded lazily only when a PCB is actually extracted.
from shapely.geometry import Polygon
from shapely.strtree import STRtree

HERE = Path(__file__).resolve().parent

class UnionFind:
    def __init__(self):
        self.parent = []
    def add(self):
        i = len(self.parent)
        self.parent.append(i)
        return i
    def find(self, i):
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i
    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def chain_points(chain):
    return [(chain.CPoint(i).x / 1e6, chain.CPoint(i).y / 1e6) for i in range(chain.PointCount())]


def polygons(poly):
    for i in range(poly.OutlineCount()):
        outer = chain_points(poly.COutline(i))
        holes = [chain_points(poly.CHole(i, j)) for j in range(poly.HoleCount(i))]
        if len(outer) < 3:
            continue
        shape = Polygon(outer, holes)
        if not shape.is_valid:
            shape = shape.buffer(0)
        parts = shape.geoms if hasattr(shape, 'geoms') else [shape]
        for part in parts:
            if part.geom_type == 'Polygon' and not part.is_empty:
                yield part


def extract_board(name, filename, max_error_nm=1000):
    global pcbnew
    if pcbnew is None:
        try:
            import pcbnew as module
            pcbnew = module
        except ImportError as exc:
            raise ImportError('PCB extraction needs KiCad pcbnew; use the Python interpreter shipped with KiCad') from exc
    filename = Path(filename).resolve()
    if filename.suffix != '.kicad_pcb':
        raise ValueError('Only .kicad_pcb inputs are allowed')
    source_sha = hashlib.sha256(filename.read_bytes()).hexdigest()
    board = pcbnew.LoadBoard(str(filename))
    # In-memory fill only. No SaveBoard, .pro, schematic, netlist, or design scripts.
    if not pcbnew.ZONE_FILLER(board).Fill(board.Zones()):
        raise RuntimeError(f'Zone refill failed on {name}')
    layers = list(board.GetEnabledLayers().CuStack())
    uf = UnionFind()
    by_layer = defaultdict(list)
    meta = []
    pad_ids = {}
    components = []

    def add_shape(layer, shape, identifier, data):
        by_layer[layer].append((shape, identifier))

    def item_polys(item, layer):
        poly = pcbnew.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(poly, layer, 0, max_error_nm, pcbnew.ERROR_INSIDE)
        return list(polygons(poly))

    for fp in sorted(board.GetFootprints(), key=lambda f: f.GetReference()):
        comp = {'ref': fp.GetReference(), 'value': fp.GetValue(), 'footprint': str(fp.GetFPID().GetLibItemName()), 'pads': {}}
        for pad in fp.Pads():
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            i = uf.add()
            key = f'{fp.GetReference()}:{pad.GetNumber()}'
            if key in pad_ids:
                raise ValueError(f'Duplicate electrical pad identifier {name}:{key}')
            pad_ids[key] = i
            meta.append({'kind': 'pad', 'pad': key, 'label': pad.GetNetname(), 'xy_mm': [pad.GetPosition().x/1e6, pad.GetPosition().y/1e6], 'layers': [board.GetLayerName(l) for l in layers if pad.IsOnLayer(l)], 'attribute': int(pad.GetAttribute())})
            comp['pads'][pad.GetNumber()] = {'id': i, 'label': pad.GetNetname(), 'xy_mm': meta[-1]['xy_mm'], 'layers': meta[-1]['layers']}
            # Through-hole plated pad is one entity on all copper layers; SMD pads
            # only appear on their own layer. Opposed straddle pads are NOT joined.
            for layer in layers:
                if pad.IsOnLayer(layer):
                    for shape in item_polys(pad, layer):
                        add_shape(layer, shape, i, meta[i])
        components.append(comp)
    for track in board.GetTracks():
        i = uf.add()
        meta.append({'kind': 'via' if isinstance(track, pcbnew.PCB_VIA) else 'track', 'label': track.GetNetname()})
        for layer in layers:
            if track.IsOnLayer(layer):
                for shape in item_polys(track, layer):
                    add_shape(layer, shape, i, meta[i])
    # Each disconnected zone island receives its own union-find identity.
    for zone in board.Zones():
        for layer in layers:
            if zone.IsOnLayer(layer) and zone.HasFilledPolysForLayer(layer):
                for shape in polygons(zone.GetFilledPolysList(layer)):
                    i = uf.add()
                    meta.append({'kind': 'zone_island', 'label': zone.GetNetname()})
                    add_shape(layer, shape, i, meta[i])
    for layer, entries in by_layer.items():
        geoms = [x[0] for x in entries]
        tree = STRtree(geoms)
        for i, (geom, item_id) in enumerate(entries):
            for j in tree.query(geom, predicate='intersects'):
                j = int(j)
                if j > i:
                    uf.union(item_id, entries[j][1])
    islands = defaultdict(list)
    for i, data in enumerate(meta):
        islands[uf.find(i)].append(data)
    nets = []
    for root, members in sorted(islands.items()):
        node = f'{name}_n{root}'
        labels = sorted({m['label'] for m in members if m['label']})
        pads = sorted(m['pad'] for m in members if m['kind'] == 'pad')
        nets.append({'node': node, 'labels': labels, 'pads': pads, 'copper_items': len(members)})
    for comp in components:
        for data in comp['pads'].values():
            data['node'] = f'{name}_n{uf.find(data.pop("id"))}'
    labels = defaultdict(list)
    for net in nets:
        for label in net['labels']:
            labels[label].append(net['node'])
    pad_counts = {n['node']:len(n['pads']) for n in nets}
    report = {
        'shorts': [n for n in nets if len(n['labels']) > 1],
        'split_declared_nets': {label:nodes for label,nodes in labels.items() if len(nodes)>1},
        'single_pad_nets': [n for n in nets if len(n['pads']) == 1],
        'floating_copper': [n for n in nets if not n['pads']],
        'unlabelled_pad_nets': [n for n in nets if n['pads'] and not n['labels']],
        'pad_count': sum(pad_counts.values()), 'physical_net_count':len(nets),
    }
    if hashlib.sha256(filename.read_bytes()).hexdigest() != source_sha:
        raise RuntimeError('Input changed during extraction')
    copper={'entities':meta,'layer_shapes':{board.GetLayerName(l):[{'entity':i,'wkt':s.wkt} for s,i in entries] for l,entries in by_layer.items()}, 'thickness_mm':board.GetDesignSettings().GetBoardThickness()/1e6, 'copper_thickness_um':35., 'copper_thickness_source':'default 1 oz; stackup overrides supported by graph parameters'}
    return {'copper_geometry':copper, 'board':name, 'path':str(filename), 'sha256':source_sha, 'kicad_version':pcbnew.Version(), 'zone_refilled_in_memory':True, 'polygon_max_error_nm':max_error_nm, 'components':components, 'nets':nets, 'report':report}


def combine(boards, connections=()):
    uf = UnionFind()
    ids = {}
    components = []
    for board in boards:
        for net in board['nets']:
            ids[net['node']] = uf.add()
        for c in board['components']:
            components.append({**c, 'board':board['board'], 'ref':f'{board["board"]}_{c["ref"]}', 'pads':{p:dict(d) for p,d in c['pads'].items()}})
    lookup = {(c['board'],c['ref'].split('_',1)[1]):c for c in components}
    mating = []
    for daughter, header, mother, socket in connections:
        a,b = lookup[(daughter,header)], lookup[(mother,socket)]
        if set(a['pads']) != set(b['pads']):
            raise ValueError(f'{daughter} connector pin numbers do not match {socket}')
        for number in a['pads']:
            uf.union(ids[a['pads'][number]['node']], ids[b['pads'][number]['node']])
        mating.append({'daughter':daughter,'mother':mother, 'header':header, 'motherboard_socket':socket, 'pin_count':len(a['pads']), 'mapping':'identical pad number; no net-label joining', 'geometry':{'header':{p:{k:d[k] for k in ('xy_mm','layers')} for p,d in a['pads'].items()}, 'socket':{p:{k:d[k] for k in ('xy_mm','layers')} for p,d in b['pads'].items()}}})
    bodge_report = None
    merged = defaultdict(lambda:{'local_nodes':[], 'labels':set(), 'pads':[]})
    for board in boards:
        for net in board['nets']:
            entry = merged[uf.find(ids[net['node']])]
            entry['local_nodes'].append(net['node'])
            entry['labels'].update(f'{board["board"]}:{label}' for label in net['labels'])
            entry['pads'].extend(f'{board["board"]}:{p}' for p in net['pads'])
    for c in components:
        for d in c['pads'].values():
            d['local_node'] = d['node']
            d['node'] = f'n{uf.find(ids[d["node"]])}'
    nets = [{'node':f'n{i}', **d, 'labels':sorted(d['labels'])} for i,d in sorted(merged.items())]
    # Different board-local labels are normal (e.g. GND). Conflicts within a board
    # are caught separately; connector mapping disagreements remain explicit.
    mismatches = []
    for m in mating:
        a,b=lookup[(m['daughter'],m['header'])],lookup[(m['mother'],m['motherboard_socket'])]
        for p in a['pads']:
            if a['pads'][p]['label'] != b['pads'][p]['label']:
                mismatches.append({'daughter':m['daughter'], 'pin':p, 'daughter_label':a['pads'][p]['label'], 'mother_label':b['pads'][p]['label']})
    return {'components':components,'nets':nets,'mating':mating,'bodge':bodge_report,'connector_label_disagreements':mismatches}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board',action='append',required=True,help='NAME=/path/to/file.kicad_pcb')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    paths={}
    for option in args.board:
        name,path=option.split('=',1);paths[name]=Path(path)
    boards=[]
    for name,path in paths.items():
        print(f'Extracting {name} from physical copper',flush=True)
        result=extract_board(name,path)
        print(name,json.dumps({k:len(v) if isinstance(v,(list,dict)) else v for k,v in result['report'].items()}),flush=True)
        boards.append(result)
    combined=combine(boards)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps({'format_version':1,'boards':boards,'combined':combined},indent=2)+'\n')
    print(f'Wrote {args.out}',flush=True)

if __name__=='__main__':
    main()
