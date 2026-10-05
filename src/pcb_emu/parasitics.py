"""Geometry-derived distributed copper resistance; approximate C/L inventory.
Zone star models are spreading-resistance estimates, not a field solver.
"""
import math
from collections import defaultdict
import numpy as np
from shapely import wkt
from shapely.geometry import Point
from shapely.strtree import STRtree

def copper_graph(board,temperature=20,copper_thickness_um=None,via_plating_um=25,er=4.2):
    g=board['copper_geometry'];name=board['board'];t=(copper_thickness_um or g['copper_thickness_um'])*1e-6
    rho=1.68e-8*(1+.00393*(temperature-20));sheet=rho/t;h=g['thickness_mm']*1e-3
    entities=g['entities'];edges=[];nodes=set();terminals=defaultdict(list);inventory=[]
    order=g.get('layer_order') or sorted(g['layer_shapes'], key=lambda x: (0 if x=='F.Cu' else 2 if x=='B.Cu' else 1, int(x[2:-3]) if x.startswith('In') else 0))
    depths=g.get('layer_depth_mm') or {layer:g['thickness_mm']*i/max(len(order)-1,1) for i,layer in enumerate(order)}
    via_terminals={}
    entity_layers=defaultdict(list)
    for layer,items in g['layer_shapes'].items():
        for item in items:
            if layer not in entity_layers[item['entity']]:entity_layers[item['entity']].append(layer)
    layer_sheet={layer:rho/((copper_thickness_um or g.get('layer_copper_thickness_um',{}).get(layer) or g['copper_thickness_um'])*1e-6) for layer in order}
    track_layers={i:ls[0] for i,ls in entity_layers.items() if entities[i]['kind']=='track' and ls}
    def add_node(n,xy):nodes.add(n);return (n,np.asarray(xy,float))
    for i,e in enumerate(entities):
        if e['kind']=='pad':terminals[i].append(add_node(f'{name}@{e["pad"]}',e['xy_mm']))
        elif e['kind']=='track':
            terminals[i].extend([add_node(f'{name}@t{i}a',e['start_mm']),add_node(f'{name}@t{i}b',e['end_mm'])])
        elif e['kind']=='via':
            span=[layer for layer in order if layer in e.get('layers',entity_layers[i])]
            via_terminals[i]={layer:add_node(f'{name}@v{i}:{layer}',e['xy_mm']) for layer in span}
            terminals[i].extend(via_terminals[i].values())
            d=e['drill_mm']*1e-3;R=0.;length=0.
            for a,b in zip(span,span[1:]):
                segment=abs(depths[b]-depths[a])*1e-3
                resistance=rho*segment/(math.pi*max(d,1e-6)*via_plating_um*1e-6)
                edges.append((via_terminals[i][a][0],via_terminals[i][b][0],max(resistance,1e-7)))
                R+=resistance;length+=segment
            inventory.append({'kind':'via','entity':i,'layers':span,'length_mm':length*1e3,'R_ohm':R,'L_H':2e-7*length*(math.log(max(4*length/max(d,1e-6),1.01))+1),'C_F':2*math.pi*8.854e-12*er*length/math.log(max((d+0.5e-3)/max(d,1e-6),1.01))})
    shapes_by_entity=defaultdict(list)
    for layer,items in g['layer_shapes'].items():
        shapes=[wkt.loads(s['wkt']) for s in items];tree=STRtree(shapes)
        for item,s in zip(items,shapes):shapes_by_entity[item['entity']].append(s)
        def attach(entity,xy):
            e=entities[entity];ts=terminals[entity]
            if e['kind']=='via':return via_terminals[entity][layer][0]
            if e['kind']=='pad':return ts[0][0]
            if e['kind']=='zone_island':
                if not ts:ts.append(add_node(f'{name}@zone{entity}',xy))
                n=f'{name}@zone{entity}p{len(ts)}';ts.append(add_node(n,xy));return n
            a=np.asarray(e['start_mm']);b=np.asarray(e['end_mm']);v=b-a
            frac=np.clip(np.dot(np.asarray(xy)-a,v)/max(np.dot(v,v),1e-20),0,1);xy=a+frac*v
            for n,p in ts:
                if np.linalg.norm(xy-p)<1e-6:return n
            n=f'{name}@t{entity}p{len(ts)}';ts.append(add_node(n,xy));return n
        for j,(item,s) in enumerate(zip(items,shapes)):
            for k in tree.query(s,predicate='intersects'):
                k=int(k)
                if k<=j or item['entity']==items[k]['entity']:continue
                overlap=s.intersection(shapes[k]);xy=(overlap.representative_point().x,overlap.representative_point().y)
                a=attach(item['entity'],xy);b=attach(items[k]['entity'],xy)
                if a!=b:edges.append((a,b,0.))
    for i,e in enumerate(entities):
        ts=terminals[i]
        if e['kind']=='track':
            sheet=layer_sheet.get(track_layers.get(i),rho/t)
            start=np.asarray(e['start_mm']);ts.sort(key=lambda n:np.linalg.norm(n[1]-start));width=e['width_mm']*1e-3
            for (a,pa),(b,pb) in zip(ts,ts[1:]):
                length=np.linalg.norm(pb-pa)*1e-3;edges.append((a,b,max(sheet*length/width,1e-7)))
            length=np.linalg.norm(np.asarray(e['end_mm'])-start)*1e-3
            # Parallel-plate upper-order estimate to opposite plane, partial inductance.
            inventory.append({'kind':'track','entity':i,'R_ohm':sheet*length/width,'C_F':8.854e-12*er*length*width/max(h,1e-6),'L_H':2e-7*length*max(math.log(max(2*length/(width+t),1.01))+.5,0)})
        elif e['kind']=='zone_island' and len(ts)>1:
            sheet=layer_sheet.get(entity_layers[i][0],rho/t)
            area=sum(s.area for s in shapes_by_entity[i]);width=max(math.sqrt(area),.05)*1e-3
            for n,p in ts[1:]:edges.append((ts[0][0],n,max(sheet*np.linalg.norm(p-ts[0][1])*1e-3/width,1e-7)))
            inventory.append({'kind':'zone','entity':i,'C_F':8.854e-12*er*area*1e-6/max(h,1e-6),'approximation':'star spreading resistance'})
    # Legacy local net aliases only used for diagnostics. Component stamps use pad nodes.
    aliases={n['node']:f'{name}@{n["pads"][0]}' if n['pads'] else f'{name}@floating{j}' for j,n in enumerate(board['nets'])}
    nodes.update(aliases.values())
    return {'aliases':aliases,'nodes':sorted(nodes),'edges':edges,'inventory':inventory,'copper_thickness_um':t*1e6,'temperature_C':temperature}
