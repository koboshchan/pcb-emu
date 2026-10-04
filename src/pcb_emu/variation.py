"""Seeded component variation, with explicit statistical assumptions.

Defaults are an engineering scenario, not a manufacturing yield model.
Use fresh Emulator/Board instances for each sampled physical unit.
"""
from dataclasses import dataclass,asdict
import numpy as np
from .components import Resistor,Capacitor,TL074,Diode,L7805


@dataclass(frozen=True)
class Variation:
    resistor_tolerance:float=.01
    capacitor_tolerance:float=.10
    resistor_tempco:float=100e-6
    temperature:float=25.
    opamp_offset_bound:float=.006
    opamp_offset_drift:float=18e-6
    opamp_bias_bound:float=200e-12
    opamp_gain_relative:float=.20
    opamp_gbw_relative:float=.20
    opamp_slew_relative:float=.20
    diode_vf_bound:float=.03
    diode_tempco:float=-.002
    regulator_relative:float=.04
    supply_relative:float=.01
    ripple_peak:float=.01
    noise_bandwidth:float=1000.
    supply_noise_rms:float=.001
    adc_gain_bound:float=.0015
    adc_offset_bound:float=3.
    adc_inl_bound:float=1.
    adc_noise_rms:float=.5

    def __post_init__(self):
        if not np.isfinite(list(asdict(self).values())).all():raise ValueError('Variation parameters must be finite')
        if self.temperature<=-273.15:raise ValueError('Temperature must exceed absolute zero')
        for name,value in asdict(self).items():
            if name not in ('temperature','diode_tempco') and value<0:raise ValueError(f'{name} must be nonnegative')
        for name in ('resistor_tolerance','capacitor_tolerance','opamp_gain_relative','opamp_gbw_relative','opamp_slew_relative','regulator_relative','supply_relative'):
            if getattr(self,name)>=1:raise ValueError(f'{name} must be less than one')

    def apply(self,emu,seed):
        """Apply one fixed physical sample. Dynamic noise is separately keyed by time.

        Do not apply twice to the same emulator: that compounds tolerances.
        Component traversal is sorted by board name and reference, not object IDs.
        """
        if hasattr(emu,'variation'):raise ValueError('Use a fresh emulator for each variation sample')
        rng=np.random.default_rng(seed);temp=self.temperature-25.;draws={}
        components=sorted((c for b in emu.boards.values() for c in b.components),key=lambda c:(c.board.name,c.ref))
        for c in components:
            values={}
            if isinstance(c,Resistor):
                factor=(1+rng.uniform(-self.resistor_tolerance,self.resistor_tolerance))*(1+self.resistor_tempco*temp)
                if factor<=0:raise ValueError('Temperature produced nonpositive resistance')
                c.resistance*=factor;values['resistance']=c.resistance
            elif isinstance(c,Capacitor):
                c.capacitance*=1+rng.uniform(-self.capacitor_tolerance,self.capacitor_tolerance);values['capacitance']=c.capacitance
            elif isinstance(c,TL074):
                c.offset=rng.uniform(-self.opamp_offset_bound,self.opamp_offset_bound,4)+rng.uniform(-self.opamp_offset_drift,self.opamp_offset_drift,4)*temp
                c.bias=rng.uniform(-self.opamp_bias_bound,self.opamp_bias_bound,(4,2))*2**(temp/10)
                c.gain*=1+rng.uniform(-self.opamp_gain_relative,self.opamp_gain_relative)
                c.gbw=3e6*(1+rng.uniform(-self.opamp_gbw_relative,self.opamp_gbw_relative))
                c.slew_rate=13e6*(1+rng.uniform(-self.opamp_slew_relative,self.opamp_slew_relative))
                values.update(offset=c.offset.tolist(),bias=c.bias.tolist(),gain=c.gain,gbw=c.gbw,slew_rate=c.slew_rate)
            elif isinstance(c,Diode):
                c.vf_shift=rng.uniform(-self.diode_vf_bound,self.diode_vf_bound)+self.diode_tempco*temp
                c.nvt*= (self.temperature+273.15)/298.15
                values.update(vf_shift=c.vf_shift,nvt=c.nvt)
            elif isinstance(c,L7805):
                c.regulated_voltage=5*(1+rng.uniform(-self.regulator_relative,self.regulator_relative));values['regulated_voltage']=c.regulated_voltage
            if values:draws[f'{c.board.name}.{c.ref}']=values
        for supply in sorted(emu.supplies,key=lambda s:s.name):
            for name,channel in sorted(supply.channels.items()):
                channel['voltage']*=1+rng.uniform(-self.supply_relative,self.supply_relative)
                channel['ripple']=self.ripple_peak
                draws[f'{supply.name}.{name}']={'voltage':channel['voltage'],'ripple':channel['ripple']}
        for adc in sorted(emu.peripherals,key=lambda a:a.board.name):
            if hasattr(adc,'RANGES'):
                adc.gain_error=rng.uniform(-self.adc_gain_bound,self.adc_gain_bound)
                adc.offset_error=rng.uniform(-self.adc_offset_bound,self.adc_offset_bound)
                adc.inl_error=rng.uniform(-self.adc_inl_bound,self.adc_inl_bound)
                adc.noise_rms=self.adc_noise_rms;adc.noise_seed=int(seed)
                draws[adc.board.name]={'gain_error':adc.gain_error,'offset_error':adc.offset_error,'inl_error':adc.inl_error,'noise_rms':adc.noise_rms}
        emu.temperature=self.temperature;emu.variation=self;emu.variation_seed=int(seed)
        emu.variation_sample=draws;emu._compiled=False
        return draws

    def sample_noise(self,emu,time):
        """Independent bandwidth-limited endpoint samples, frozen during Newton.

        Not a continuous colored waveform. Repeated solves at identical time
        reuse the identical sample. Never call a random generator in Newton.
        """
        bits=int(np.float64(time).view(np.uint64))
        rng=np.random.default_rng(np.random.SeedSequence([emu.variation_seed,bits&0xffffffff,bits>>32]))
        for c in sorted(emu.components,key=lambda c:(c.board.name,c.ref)):
            if isinstance(c,Resistor):
                c.noise_current=rng.normal(0,np.sqrt(4*1.380649e-23*(self.temperature+273.15)*self.noise_bandwidth/max(c.resistance,1e-6)))
            elif isinstance(c,TL074):c.input_noise=rng.normal(0,37e-9*np.sqrt(self.noise_bandwidth),4)
        for supply in sorted(emu.supplies,key=lambda s:s.name):
            for _,channel in sorted(supply.channels.items()):channel['noise']=rng.normal(0,self.supply_noise_rms)
