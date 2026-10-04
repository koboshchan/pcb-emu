import numpy as np
from shapely.geometry import box
from pcb_emu.parasitics import copper_graph
from pcb_emu import Board, Emulator


def specimen():
    entities=[{'kind':'pad','pad':'J:1','xy_mm':[0,0]}, {'kind':'pad','pad':'J:2','xy_mm':[10,0]}, {'kind':'track','start_mm':[0,0],'end_mm':[10,0],'width_mm':.2}]
    shapes=[{'entity':0,'wkt':box(-.1,-.1,.1,.1).wkt},{'entity':1,'wkt':box(9.9,-.1,10.1,.1).wkt},{'entity':2,'wkt':box(0,-.1,10,.1).wkt}]
    return {'board':'b','nets':[{'node':'n','pads':['J:1','J:2']}],'components':[{'ref':'J','value':'Connector','footprint':'test','pads':{'1':{'node':'n'},'2':{'node':'n'}}}], 'copper_geometry':{'entities':entities,'layer_shapes':{'F.Cu':shapes},'copper_thickness_um':35,'thickness_mm':1.6}}


def test_track_resistance_temperature():
    cold=copper_graph(specimen());warm=copper_graph(specimen(),temperature=120)
    rc=sum(r for a,b,r in cold['edges']);rw=sum(r for a,b,r in warm['edges'])
    expected=1.68e-8*.01/(.0002*.000035)
    assert abs(rc-expected)<1e-5
    assert abs(rw/rc-(1+.00393*100))<1e-4
    assert cold['inventory'][0]['C_F']>0
    assert cold['inventory'][0]['L_H']>0


def test_copper_and_virtual_supply():
    b=Board(name='b',extracted=specimen());e=Emulator(ideal_copper=False);e.add_board(b)
    p=e.add_psu({'ch':5});e.connect(p.pin('ch+'),b.pin('J','1'));e.connect(p.pin('ch-'),b.pin('J','2'));e.drive(p.pin('ch-'),0);p.on()
    e.dc();assert np.isfinite(e.x).all()
    assert e.read(b.pin('J','1'))>e.read(b.pin('J','2'))
