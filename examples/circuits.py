"""Small caller-defined circuits, with no dependency on a particular PCB."""
from pcb_emu import Board


def circuit(parts, name='demo'):
    """Build a virtual board from (reference, value, {pad: node}) tuples."""
    nodes=sorted({node for _,_,pads in parts for node in pads.values()})
    return Board(name=name,extracted={
        'board':name,'nets':[{'node':f'{name}:{n}'} for n in nodes],
        'components':[{'ref':ref,'value':value,'footprint':'Virtual:demo',
                       'pads':{pad:{'node':f'{name}:{node}','label':node} for pad,node in pads.items()}}
                      for ref,value,pads in parts]})


def divider():
    return circuit([('R1','10k',{'1':'input','2':'output'}),('R2','10k',{'1':'output','2':'ground'})])


def rc():
    return circuit([('R1','10k',{'1':'input','2':'output'}),('C1','1uF',{'1':'output','2':'ground'})])


def amplifier():
    pins={'1':'output','2':'feedback','3':'input','4':'positive','11':'negative',
          '5':'ground','6':'unused1','7':'unused1','8':'unused2','9':'unused2',
          '10':'ground','12':'ground','13':'unused3','14':'unused3'}
    return circuit([('U1','TL074',pins),('R1','10k',{'1':'feedback','2':'ground'}),
                    ('R2','10k',{'1':'output','2':'feedback'})])
