import math
import pytest
from shapely.geometry import box
from pcb_emu.parasitics import copper_graph
from pcb_emu.stackup import copper_stackup
from pcb_emu.components import Connector, make_component


def multilayer(span=None):
    layers=['F.Cu','In1.Cu','In2.Cu','B.Cu']
    span=span or layers
    entities=[{'kind':'via','xy_mm':[0,0],'drill_mm':.3,'layers':span}]
    shapes={}
    for layer in span:
        i=len(entities)
        entities.append({'kind':'pad','pad':f'J:{i}','xy_mm':[0,0]})
        shapes[layer]=[{'entity':0,'wkt':box(-.3,-.3,.3,.3).wkt},{'entity':i,'wkt':box(-.1,-.1,.1,.1).wkt}]
    return {'board':'b','nets':[{'node':'n','pads':['J:1']}], 'copper_geometry':{'entities':entities,'layer_shapes':shapes,'thickness_mm':1.6,'copper_thickness_um':35,'layer_order':layers,'layer_depth_mm':dict(zip(layers,[0,.2,1.3,1.6]))}}


def test_four_layer_via_distinct_taps_and_depths():
    graph=copper_graph(multilayer())
    edges=[(a,b,r) for a,b,r in graph['edges'] if a.startswith('b@v') and b.startswith('b@v')]
    assert len(edges)==3
    assert [b.split(':')[-1] for a,b,r in edges]==['In1.Cu','In2.Cu','B.Cu']
    expected=1.68e-8*.0016/(math.pi*.0003*25e-6)
    assert sum(r for a,b,r in edges)==pytest.approx(expected)
    assert edges[1][2]/edges[0][2]==pytest.approx(5.5)
    assert graph['inventory'][0]['length_mm']==pytest.approx(1.6)
    for i,layer in enumerate(['F.Cu','In1.Cu','In2.Cu','B.Cu'],1):
        assert any({a,b}=={f'b@v0:{layer}',f'b@J:{i}'} for a,b,r in graph['edges'])


def test_blind_via_only_spans_present_layers():
    graph=copper_graph(multilayer(['In1.Cu','In2.Cu']))
    assert graph['inventory'][0]['length_mm']==pytest.approx(1.1)
    assert not any('v0:F.Cu' in n or 'v0:B.Cu' in n for n in graph['nodes'])


def test_stackup_saved_and_fallback():
    layers=['F.Cu','In1.Cu','B.Cu']
    text='''(kicad_pcb (setup (stackup
        (layer "F.Cu" (thickness 0.035))
        (layer "dielectric 1" (thickness 0.2))
        (layer "In1.Cu" (thickness 0.018))
        (layer "dielectric 2" (thickness 1.0))
        (layer "B.Cu" (thickness 0.035)))))'''
    stack=copper_stackup(text,layers,1.6)
    assert stack['layer_depth_mm']['In1.Cu']==pytest.approx(.2265)
    assert stack['layer_depth_mm']['B.Cu']==pytest.approx(1.253)
    assert stack['layer_copper_thickness_um']['In1.Cu']==18
    fallback=copper_stackup('(kicad_pcb)',layers,1.6)
    assert fallback['layer_depth_mm']==dict(zip(layers,[0,.8,1.6]))


@pytest.mark.parametrize('value,dnp',[('DNP',False),('10k',True),('DNI',False)])
def test_dnp_keeps_pad_terminals_but_is_open(value,dnp):
    metadata={'ref':'R1','value':value,'dnp':dnp,'footprint':'0805','pads':{'1':{'node':'a'},'2':{'node':'b'}}}
    component=make_component(type('B',(),{'name':'test'})(),metadata)
    assert isinstance(component,Connector)
    assert component.pins=={'1':'a','2':'b'}
