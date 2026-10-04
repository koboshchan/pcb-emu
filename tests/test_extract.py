import tempfile
import unittest
from pathlib import Path

try:
    import pcbnew
except ImportError:
    pcbnew = None
from pcb_emu.extract import extract_board

@unittest.skipIf(pcbnew is None, 'KiCad pcbnew is not installed')
class CopperTests(unittest.TestCase):
    def board(self, positions, tracks=(), via=False):
        b=pcbnew.BOARD()
        for i,(x,y,layer,label) in enumerate(positions):
            net=next((n for n in b.GetNetsByNetcode().values() if n.GetNetname()==label),None)
            if net is None:
                net=pcbnew.NETINFO_ITEM(b,label);b.Add(net)
            f=pcbnew.FOOTPRINT(b);f.SetReference(f'J{i}');b.Add(f)
            p=pcbnew.PAD(f);p.SetNumber('1');p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
            p.SetShape(pcbnew.PAD_SHAPE_RECT);p.SetSize(pcbnew.VECTOR2I(1000000,1000000))
            p.SetPosition(pcbnew.VECTOR2I(int(x*1e6),int(y*1e6)))
            layers=pcbnew.LSET();layers.AddLayer(layer);p.SetLayerSet(layers);p.SetNet(net);f.Add(p)
        for x1,y1,x2,y2,layer,label in tracks:
            t=pcbnew.PCB_TRACK(b);t.SetStart(pcbnew.VECTOR2I(int(x1*1e6),int(y1*1e6)))
            t.SetEnd(pcbnew.VECTOR2I(int(x2*1e6),int(y2*1e6)));t.SetWidth(200000);t.SetLayer(layer)
            t.SetNet(next(n for n in b.GetNetsByNetcode().values() if n.GetNetname()==label));b.Add(t)
        if via:
            v=pcbnew.PCB_VIA(b);v.SetPosition(pcbnew.VECTOR2I(2000000,2000000));v.SetWidth(600000);v.SetDrill(300000)
            v.SetLayerPair(pcbnew.F_Cu,pcbnew.B_Cu);b.Add(v)
        return b
    def extract(self,b):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.kicad_pcb';pcbnew.SaveBoard(str(p),b)
            return extract_board('TEST',p)
    def test_identical_labels_do_not_join(self):
        r=self.extract(self.board([(2,2,pcbnew.F_Cu,'same'),(5,2,pcbnew.F_Cu,'same')]))
        self.assertEqual(len(r['report']['split_declared_nets']['same']),2)
    def test_real_copper_overrides_labels(self):
        r=self.extract(self.board([(2,2,pcbnew.F_Cu,'a'),(5,2,pcbnew.F_Cu,'b')],[(2,2,5,2,pcbnew.F_Cu,'a')]))
        self.assertEqual(len(r['report']['shorts']),1)
    def test_opposed_smd_not_connected(self):
        r=self.extract(self.board([(2,2,pcbnew.F_Cu,'a'),(2,2,pcbnew.B_Cu,'b')]))
        self.assertEqual(r['report']['physical_net_count'],2)
    def test_via_connects_layers(self):
        r=self.extract(self.board([(2,2,pcbnew.F_Cu,'a'),(2,2,pcbnew.B_Cu,'b')],via=True))
        self.assertEqual(r['report']['physical_net_count'],1)

if __name__=='__main__':unittest.main()
