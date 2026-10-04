"""Cooperative CPython runner for a subset of Pico MicroPython.

SECURITY: execute only trusted firmware. This is NOT a sandbox. Firmware has
full CPython privileges. Imports of machine/time/utime/rp2 are local to this
runner; sys.modules is never patched. PIO instructions are not emulated.

p = Pico(code='main.py').attach(emu)
emu.connect(p.pin('GP0'), other.pin('J1', '1'))
p.step_due(emu.time); emu.run(); p.step_due(emu.time)
Or use emu.add_pico(code='main.py') for automatic tick scheduling.
Existing footprints must really contain exactly pads 1..40. Otherwise use the
standalone virtual connector board, which never modifies a PCB. advance and
step_due service firmware until a future simulated sleep or operation budget.
All firmware pin operations rendezvous with the simulation thread. CPU-only
infinite loops cannot be preempted; daemon threads do not block process exit.
SPI/I2C/UART use explicitly installed bus callbacks or raise NotImplementedError,
not fictitious devices. PWM is ideal digital voltage, not averaged duty voltage.
Power rails are ideal explicit defaults, not an emulation of Pico's regulator.
Pin mapping source: Raspberry Pi RP-008309-DS-1-Pico-R3-A4-Pinout.pdf.
"""
import builtins
import math
from pathlib import Path
import threading
from types import SimpleNamespace

PAD_NAMES = ('GP0','GP1','GND','GP2','GP3','GP4','GP5','GND','GP6','GP7',
 'GP8','GP9','GND','GP10','GP11','GP12','GP13','GND','GP14','GP15',
 'GP16','GP17','GND','GP18','GP19','GP20','GP21','GND','GP22','RUN',
 'GP26','GP27','AGND','GP28','ADC_VREF','3V3','3V3_EN','GND','VSYS','VBUS')
GPIO_PADS = {int(n[2:]):str(i) for i,n in enumerate(PAD_NAMES,1) if n.startswith('GP')}

class _Stopped(BaseException): pass

class Pico:
    def __init__(self, code=None, *, board=None, ref=None, name='pico', source=None):
        from .core import Board
        if board is None:
            ref = ref or 'J_PICO'
            pads={str(i):{'node':f'{name}:pad{i}', 'label':n} for i,n in enumerate(PAD_NAMES,1)}
            board=Board(name=name, extracted={'nets':[{'node':p['node']} for p in pads.values()],
                'components':[{'ref':ref,'value':'Virtual Pico','footprint':'Virtual:40Pads','pads':pads}]})
        else:
            ref=ref or 'U_PICO'
            actual={p.pad for p in board.pins.values() if p.ref==ref}
            if actual != {str(i) for i in range(1,41)}:
                raise ValueError('Existing Pico footprint must have exactly physical pads 1..40')
        self.board=board; self.ref=ref; self.code=code; self.source=source
        self.emu=None; self.now=0.; self.globals={}; self.error=None; self.done=False
        self.cv=threading.Condition(); self.request=None; self.response=None
        self.ready=False; self.closed=False; self.thread=None; self.pins={}; self.timers=[]
        self.bus_handlers={}; self._irq_events=[]; self._pwm={}
        self.machine,self.time,self.rp2=self._modules()
    def pin(self, identifier):
        if isinstance(identifier,int): identifier=f'GP{identifier}'
        if identifier.startswith('GP'):
            return self.board.pin(self.ref,GPIO_PADS[int(identifier[2:])])
        if identifier.isdecimal(): return self.board.pin(self.ref,identifier)
        return self.board.pin(self.ref,str(PAD_NAMES.index(identifier)+1))
    def attach(self, emu):
        self.emu=emu
        if self.board.name not in emu.boards: emu.add_board(self.board)
        elif emu.boards[self.board.name] is not self.board: raise ValueError('Board name collision')
        for i,n in enumerate(PAD_NAMES,1):
            if n in ('GND','AGND'): emu.drive(self.board.pin(self.ref,str(i)),0.)
        for n,v in [('3V3',3.3),('ADC_VREF',3.3),('3V3_EN',3.3),('RUN',3.3),('VSYS',5.),('VBUS',5.)]:
            emu.drive(self.pin(n),v)
        return self
    def start(self):
        if self.emu is None: raise RuntimeError('Attach before starting')
        if self.thread: return self
        text=self.source if self.source is not None else Path(self.code).read_text()
        compiled=compile(text,str(self.code or '<pico>'),'exec')
        original=builtins.__import__
        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            modules={'machine':self.machine,'time':self.time,'utime':self.time,'rp2':self.rp2}
            if level==0 and name in modules:return modules[name]
            return original(name,globals,locals,fromlist,level)
        custom=dict(vars(builtins));custom['__import__']=importing
        self.globals={'__builtins__':custom,'__name__':'__main__','__file__':str(self.code or '<pico>')}
        def run():
            try: exec(compiled,self.globals)
            except _Stopped: pass
            except BaseException as exc: self.error=exc
            finally:
                with self.cv:self.done=True;self.cv.notify_all()
        self.thread=threading.Thread(target=run,name=f'firmware-{self.board.name}',daemon=True)
        self.thread.start();return self
    def _call(self, fn, deadline=None):
        with self.cv:
            if self.closed:raise _Stopped()
            self.request=(fn,deadline);self.ready=False;self.cv.notify_all()
            self.cv.wait_for(lambda:self.ready or self.closed)
            if self.closed:raise _Stopped()
            result=self.response
            self.request=None;self.ready=False;self.cv.notify_all()
        # IRQ callbacks execute in the firmware thread, never recursively in solver.
        events,self._irq_events=self._irq_events,[]
        for cb,pin in events:cb(pin)
        if isinstance(result,BaseException):raise result
        return result
    def step_due(self, now, max_operations=10000, watchdog=2.):
        if now<self.now:raise ValueError('Simulated time cannot go backwards')
        self.now=float(now);self.start()
        for p,pwm in list(self._pwm.items()):
            self.emu.drive(self.pin(p),3.3 if (self.now*pwm._freq)%1 < pwm._duty/65535 else 0.)
        for pin in self.pins.values():
            if pin.handler and pin.gpio in GPIO_PADS:
                value=int(self.emu.read(self.pin(pin.gpio))>=1.65)
                if value!=pin.last and pin.trigger & (pin.IRQ_RISING if value else pin.IRQ_FALLING):self._irq_events.append((pin.handler,pin))
                pin.last=value
        for timer in self.timers:
            if timer.active and self.now>=timer.due:
                self._irq_events.append((timer.callback,timer))
                if timer.mode==timer.ONE_SHOT:timer.active=False
                else:timer.due=self.now+timer.period
        for _ in range(max_operations):
            with self.cv:
                if not self.cv.wait_for(lambda:(self.request is not None and not self.ready) or self.done,watchdog):
                    raise RuntimeError('Firmware did not yield (CPU loop or blocking host operation)')
                if self.done:
                    if self.error:raise self.error
                    return
                fn,deadline=self.request
                if deadline is not None and deadline>self.now:return
                try:
                    self.response=fn()
                    # Commit queued callback drives and settle each digital transition.
                    # Without this, multiple bitbang edges within one host tick vanish.
                    self.emu.drives.update(self.emu.pending);self.emu.pending.clear()
                    settle=getattr(self.emu,'_solve',None)
                    if settle is not None:settle(advance=True,time=self.now)
                except Exception as exc:self.response=exc
                self.ready=True;self.cv.notify_all()
                if not self.cv.wait_for(lambda:not self.ready or self.done,watchdog):raise RuntimeError('Firmware stalled')
    advance=step_due
    def close(self):
        with self.cv:self.closed=True;self.cv.notify_all()
        if self.thread:self.thread.join(timeout=.2)
    def _modules(self):
        pico=self
        class Pin:
            IN=0;OUT=1;OPEN_DRAIN=2;PULL_UP=1;PULL_DOWN=2;IRQ_RISING=1;IRQ_FALLING=2
            def __new__(cls,id,*a,**kw):
                if isinstance(id,cls):return id
                n=25 if id=='LED' else int(str(id).removeprefix('GP'))
                if not 0<=n<=29:raise ValueError('GPIO outside 0..29')
                if n in pico.pins:return pico.pins[n]
                obj=super().__new__(cls);pico.pins[n]=obj;return obj
            def __init__(self,id,mode=None,pull=None,value=None):
                if not hasattr(self,'gpio'):
                    self.gpio=25 if id=='LED' else int(str(id).removeprefix('GP'));self.mode=self.IN;self.pull=None;self.state=0;self.handler=None;self.trigger=3;self.last=0
                if mode is not None or pull is not None or value is not None:self.init(mode,pull,value=value)
            def init(self,mode=None,pull=None,*,value=None):
                def apply():
                    if mode is not None:self.mode=mode
                    self.pull=pull
                    if value is not None:self.state=int(bool(value))
                    if self.gpio in GPIO_PADS:
                        key=pico.pin(self.gpio)
                        if self.mode==self.OUT:pico.emu.drive(key,3.3*self.state)
                        elif self.mode==self.OPEN_DRAIN and not self.state:pico.emu.drive(key,0.)
                        else:
                            pico.emu.drives.pop(key.key,None);pico.emu.pending.pop(key.key,None)
                            if pull is not None:pico.emu.drive(key,3.3 if pull==self.PULL_UP else 0.)
                return pico._call(apply)
            def value(self,v=None):
                def operation():
                    if v is None:
                        if self.gpio in GPIO_PADS:return int(pico.emu.read(pico.pin(self.gpio))>=1.65)
                        if self.gpio==24:return int(pico.emu.read(pico.pin('VBUS'))>1.)
                        return self.state
                    self.state=int(bool(v))
                    if self.gpio in GPIO_PADS:
                        key=pico.pin(self.gpio)
                        if self.mode==self.OUT:pico.emu.drive(key,3.3*self.state)
                        elif self.mode==self.OPEN_DRAIN:
                            if self.state:pico.emu.drives.pop(key.key,None)
                            else:pico.emu.drive(key,0.)
                return pico._call(operation)
            __call__=value
            def on(self):return self.value(1)
            def off(self):return self.value(0)
            def toggle(self):return self.value(not self.value())
            def irq(self,handler=None,trigger=3,**kw):
                def install():self.handler=handler;self.trigger=trigger
                pico._call(install);return self
        class ADC:
            def __init__(self,id):
                n=id.gpio if isinstance(id,Pin) else int(id)
                self.channel=n-26 if n>=26 else n
                if not 0<=self.channel<=4:raise ValueError('Invalid ADC channel')
            def read(self):
                def sample():
                    if self.channel==4:raise NotImplementedError('Temperature sensor is not modeled')
                    voltage=pico.emu.read(pico.pin(26+self.channel)) if self.channel<3 else pico.emu.read(pico.pin('VSYS'))/3
                    reference=pico.emu.read(pico.pin('ADC_VREF'))
                    if reference<=0:raise ValueError('ADC reference is not powered')
                    return int(round(max(0,min(1,voltage/reference))*4095))
                return pico._call(sample)
            def read_u16(self):return (self.read()*65535)//4095
        class PWM:
            def __init__(self,pin,*,freq=1000,duty_u16=0):
                self.pin=Pin(pin);self._freq=freq;self._duty=duty_u16
                pico._call(lambda:pico._pwm.__setitem__(self.pin.gpio,self))
            def freq(self,value=None):
                if value is None:return pico._call(lambda:self._freq)
                if value<=0:raise ValueError('Frequency must be positive')
                pico._call(lambda:setattr(self,'_freq',value))
            def duty_u16(self,value=None):
                if value is None:return pico._call(lambda:self._duty)
                if not 0<=value<=65535:raise ValueError('Duty outside 0..65535')
                pico._call(lambda:setattr(self,'_duty',value))
            def deinit(self):pico._call(lambda:pico._pwm.pop(self.pin.gpio,None))
        class Bus:
            kind='bus'
            def __init__(self,id=0,**kw):self.id=id;self.options=kw
            def _op(self,method,*args):
                def exchange():
                    handler=pico.bus_handlers.get((self.kind,self.id))
                    if handler is None:raise NotImplementedError(f'No attached {self.kind} device for bus {self.id}')
                    return handler(method,*args)
                return pico._call(exchange)
            def init(self,**kw):self.options.update(kw)
            def deinit(self):pass
        class SPI(Bus):
            kind='SPI'
            def write(self,buf):return self._op('write',bytes(buf))
            def read(self,n,write=0):return self._op('read',n,write)
            def readinto(self,buf,write=0):buf[:]=self.read(len(buf),write)
            def write_readinto(self,a,b):b[:]=self._op('write_readinto',bytes(a))
        class I2C(Bus):
            kind='I2C'
            def scan(self):return self._op('scan')
            def writeto(self,addr,buf,stop=True):return self._op('writeto',addr,bytes(buf),stop)
            def readfrom(self,addr,n,stop=True):return self._op('readfrom',addr,n,stop)
            def readfrom_into(self,addr,buf,stop=True):buf[:]=self.readfrom(addr,len(buf),stop)
            def writeto_mem(self,addr,memaddr,buf,*,addrsize=8):return self._op('writeto_mem',addr,memaddr,bytes(buf),addrsize)
            def readfrom_mem(self,addr,memaddr,n,*,addrsize=8):return self._op('readfrom_mem',addr,memaddr,n,addrsize)
        class UART(Bus):
            kind='UART'
            def write(self,buf):return self._op('write',buf.encode() if isinstance(buf,str) else bytes(buf))
            def read(self,n=None):return self._op('read',n)
            def readline(self):return self._op('readline')
            def any(self):return self._op('any')
            def readinto(self,buf):
                data=self.read(len(buf))
                if data is None:return None
                buf[:len(data)]=data;return len(data)
        class Timer:
            ONE_SHOT=0;PERIODIC=1
            def __init__(self,id=-1,**kw):
                self.active=False;pico.timers.append(self)
                if kw:self.init(**kw)
            def init(self,*,mode=1,period=-1,freq=-1,callback):
                seconds=1/freq if freq>0 else period/1000
                if seconds<=0:raise ValueError('Timer period must be positive')
                def apply():self.mode=mode;self.period=seconds;self.callback=callback;self.due=pico.now+seconds;self.active=True
                pico._call(apply)
            def deinit(self):pico._call(lambda:setattr(self,'active',False))
        def sleep(seconds):
            if seconds<0:raise ValueError('Negative sleep')
            pico._call(lambda:None,pico.now+seconds)
        def ticks(scale):return pico._call(lambda:int(pico.now*scale)%(1<<30))
        def unsupported(*a,**kw):raise NotImplementedError('RP2040 PIO execution is not emulated')
        def asm_pio(*a,**kw):
            def decorate(fn):return fn
            return decorate
        return (SimpleNamespace(Pin=Pin,ADC=ADC,PWM=PWM,SPI=SPI,SoftSPI=SPI,I2C=I2C,SoftI2C=I2C,UART=UART,Timer=Timer),
            SimpleNamespace(sleep=sleep,sleep_ms=lambda ms:sleep(ms/1000),sleep_us=lambda us:sleep(us/1e6),
                ticks_ms=lambda:ticks(1000),ticks_us=lambda:ticks(1e6),ticks_cpu=lambda:ticks(125e6),
                ticks_add=lambda a,b:(a+b)%(1<<30),ticks_diff=lambda a,b:((a-b+(1<<29))%(1<<30))-(1<<29)),
            SimpleNamespace(asm_pio=asm_pio,StateMachine=unsupported,PIO=SimpleNamespace(OUT_LOW=0,OUT_HIGH=1,IN_LOW=0,IN_HIGH=1,SHIFT_LEFT=0,SHIFT_RIGHT=1)))
