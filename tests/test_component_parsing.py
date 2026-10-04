import pytest
from pcb_emu.components import Capacitor,MountingHole,make_component

class Named:
    name='regression'


def metadata(ref,value,pads,footprint='Virtual:test'):
    return {'ref':ref,'value':value,'footprint':footprint,'pads':{pad:{'node':node,'label':node} for pad,node in pads.items()}}


@pytest.mark.parametrize('value,expected',[('10 nF',1e-8),('1 uF',1e-6),('100nF',1e-7),('1 µF',1e-6)])
def test_spaced_capacitor_units(value,expected):
    c=make_component(Named(),metadata('C1',value,{'1':'a','2':'b'}))
    assert isinstance(c,Capacitor)
    assert c.capacitance==pytest.approx(expected,rel=1e-12,abs=0)


@pytest.mark.parametrize('value,footprint',[('MountingHole_2.7mm','MountingHole_2.7mm'),('OSHW-Logo','Logo'),('CompanyLogo','Logo')])
def test_unannotated_mechanical_precedes_reference_prefix(value,footprint):
    c=make_component(Named(),metadata('REF**',value,{},footprint))
    assert isinstance(c,MountingHole)


def test_mechanical_footprint_with_pad():
    c=make_component(Named(),metadata('REF**','Hole',{'1':'ground'},'MountingHole:3mm_Pad'))
    assert isinstance(c,MountingHole)


def test_unknown_electrical_part_still_fails():
    with pytest.raises(ValueError,match='Unsupported component'):
        make_component(Named(),metadata('U1','UnknownIC',{'1':'a','2':'b'}))
