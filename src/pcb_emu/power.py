"""Bench supply channels, CV with resistive droop and hard current limit.
Channel return currents are computed from the same node solution as the load.
"""
import numpy as np
from .core import Board

class PowerSupply(Board):
    def __init__(self,channels,name='psu',current_limit=1.,output_resistance=.01,ripple=0.,frequency=50.):
        self.channels={str(k):{'voltage':float(v),'limit':float(current_limit),'resistance':float(output_resistance),'ripple':float(ripple),'frequency':frequency,'current':0.,'power':0.,'mode':'OFF'} for k,v in channels.items()}
        pads={};nets=[]
        for k in self.channels:
            for sign in '+-':
                pad=k+sign;n=f'{name}:{pad}';pads[pad]={'node':n,'label':'','layers':[],'xy_mm':[0,0]};nets.append({'node':n,'labels':[],'pads':[f'J:{pad}']})
        super().__init__(name=name,extracted={'board':name,'nets':nets,'components':[{'ref':'J','value':'PowerSupply','footprint':'virtual','pads':pads}]})
        self.enabled=False
    def pin(self,terminal,pad=None):return super().pin('J',terminal) if pad is None else super().pin(terminal,pad)
    def on(self):self.enabled=True
    def off(self):self.enabled=False
    def configure(self,channel,**kwargs):self.channels[channel].update(kwargs)
    def stamp(self,conduct,x,index,time):
        for k,c in self.channels.items():
            a=index[self.pin(k+'+').key];b=index[self.pin(k+'-').key];v=x[a]-x[b]
            if not self.enabled:c.update(current=0.,power=0.,mode='OFF');continue
            target=c['voltage']+c['ripple']*np.sin(2*np.pi*c['frequency']*time)
            r=max(c['resistance'],1e-5);unlimited=(target-v)/r
            current=float(np.clip(unlimited,-c['limit'],c['limit']))
            g=1/r if abs(unlimited)<=c['limit'] else 0.
            # Load current outgoing from plus terminal.
            conduct(a,b,g,-current-g*v)
            c.update(current=current,power=v*current,mode='CV' if g else 'CC')
