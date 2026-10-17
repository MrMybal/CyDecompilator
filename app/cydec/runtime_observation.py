"""Job-owned TCP observations and replayable desktop/renderer scenarios."""
import hashlib
import os
import shutil
import socket
import threading
import time
from pathlib import Path
from cytools_core import CyToolError
from . import process
from .engines.base import EngineContext
from .paths import ENGINES, read_json, write_json

_build_lock=threading.Lock()


def validate(options):
    if options is not None and not isinstance(options,dict):
        raise CyToolError('InvalidParameters','Runtime observation options must be an object.')
    options=dict(options or {})
    allowed={'driver','network','url','targetUrl','steps','settleMs','headless','stopAfterScenario'}
    if set(options)-allowed:
        raise CyToolError('InvalidParameters','Unknown runtime observation option.')
    driver=options.get('driver','none')
    if driver not in ('none','windows','chromium','electron'):
        raise CyToolError('InvalidParameters','Choose a supported scenario driver.')
    for key in ('network','headless','stopAfterScenario'):
        if key in options and not isinstance(options[key],bool):
            raise CyToolError('InvalidParameters','Scenario flags must be boolean.')
    steps=options.get('steps',[])
    settle=options.get('settleMs',500)
    if not isinstance(steps,list) or len(steps)>30 or not isinstance(settle,int) or not 0<=settle<=3000:
        raise CyToolError('InvalidParameters','Use at most 30 scenario steps and a settle delay up to 3000 ms.')
    normalized=[]
    for raw in steps:
        if not isinstance(raw,dict) or set(raw)-{'action','selector','text','key','url','ms','timeoutMs','label'}:
            raise CyToolError('InvalidParameters','Invalid graphical scenario step.')
        step={**raw,'timeoutMs':raw.get('timeoutMs',5000)}
        action=step.get('action')
        actions=('click','fill','toggle','select','waitFor','assertText','snapshot','wait') if driver=='windows' else (
            'click','fill','press','navigate','waitFor','assertText','snapshot','wait')
        if driver=='none' or action not in actions:
            raise CyToolError('InvalidParameters','This action is not supported by the scenario driver.')
        if not isinstance(step['timeoutMs'],int) or not 100<=step['timeoutMs']<=10000:
            raise CyToolError('InvalidParameters','Step timeout must be between 100 and 10000 ms.')
        if action in ('click','fill','press','toggle','select','waitFor','assertText'):
            selector=step.get('selector')
            if driver=='windows':
                if not isinstance(selector,dict) or not selector or set(selector)-{'automationId','name','controlType'} or any(
                    not isinstance(v,str) or not v or len(v)>500 for v in selector.values()):
                    raise CyToolError('InvalidParameters','Choose a Windows control by automationId, name or controlType.')
            elif not isinstance(selector,str) or not selector or len(selector)>1000:
                raise CyToolError('InvalidParameters','Choose a bounded CSS selector for the web scenario.')
        for key in ('text','label'):
            if key in step and (not isinstance(step[key],str) or len(step[key])>4000):
                raise CyToolError('InvalidParameters','Scenario text must be a string up to 4000 characters.')
        if action in ('fill','assertText') and 'text' not in step:
            raise CyToolError('InvalidParameters','This scenario step requires text.')
        if action=='press' and step.get('key') not in ('Enter','Tab','Escape','ArrowDown','ArrowUp','Space'):
            raise CyToolError('InvalidParameters','Choose a supported scenario key.')
        if action=='wait' and (not isinstance(step.get('ms'),int) or not 0<=step['ms']<=10000):
            raise CyToolError('InvalidParameters','Scenario waits must be between 0 and 10000 ms.')
        if action=='navigate':
            navigation_url(step.get('url'))
        normalized.append(step)
    for key in ('url','targetUrl'):
        value=options.get(key,'')
        if not isinstance(value,str) or len(value)>4096:
            raise CyToolError('InvalidParameters','Invalid scenario URL.')
        if value:
            navigation_url(value)
    if driver=='none' and any(options.get(k) for k in ('url','targetUrl','headless')):
        raise CyToolError('InvalidParameters','Choose a renderer driver before setting web options.')
    if driver=='windows' and os.name!='nt':
        raise CyToolError('Unsupported','Windows UI Automation requires Windows.')
    if driver=='windows' and any(options.get(k) for k in ('url','targetUrl','headless')):
        raise CyToolError('InvalidParameters','Web options require a renderer driver.')
    if driver=='electron' and options.get('headless'):
        raise CyToolError('InvalidParameters','Headless capture requires the Chromium driver.')
    return {'driver':driver,'network':options.get('network',False),'steps':normalized,
            'settleMs':settle,'url':options.get('url',''),'targetUrl':options.get('targetUrl',''),
            'headless':options.get('headless',False),'stopAfterScenario':options.get('stopAfterScenario',True)}


def navigation_url(value):
    from urllib.parse import urlsplit
    if not isinstance(value,str) or len(value)>4096 or urlsplit(value).scheme not in ('http','https','file','about'):
        raise CyToolError('InvalidParameters','Invalid scenario URL.')


def desktop_helper(context):
    source=Path(__file__).resolve().parents[1]/'desktop_capture/Program.cs'
    fingerprint=hashlib.sha256(source.read_bytes()).hexdigest()[:20]
    destination=ENGINES/'desktop-capture'/fingerprint/'DesktopCapture.exe'
    with _build_lock:
        if destination.is_file():
            return destination
        framework=Path(os.environ.get('SystemRoot','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319'
        compiler=framework/'csc.exe'
        references=[framework/'System.Web.Extensions.dll',framework/'System.Drawing.dll',
                    *[framework/'WPF'/name for name in ('UIAutomationClient.dll','UIAutomationTypes.dll','WindowsBase.dll')]]
        if not compiler.is_file() or not all(p.is_file() for p in references):
            raise CyToolError('MissingDependency','Windows desktop capture requires the .NET Framework compiler and UI Automation assemblies.')
        destination.parent.mkdir(parents=True,exist_ok=True)
        code,out,err=process.run([compiler,'/nologo','/target:exe','/out:'+str(destination),
            *['/reference:'+str(r) for r in references],source],context=context,timeout=60,log_name='desktop-capture-build')
        if code!=0 or not destination.is_file():
            raise CyToolError('EngineFailed','Desktop capture helper build failed: '+process.tail(out+err,10))
    return destination


class Token:
    def __init__(self,parent,stop):
        self.parent,self.stop=parent,stop
    def check(self):
        if self.parent:
            self.parent.check()
        if self.stop.is_set():
            raise CyToolError('Cancelled','Runtime observer stopped.')


class Observer:
    def __init__(self,context,directory,options,arguments):
        self.context,self.directory,self.options=context,Path(directory),validate(options)
        self.stop,self.finished=threading.Event(),threading.Event()
        self.worker=None
        self.connections=[]
        self.seen=set()
        self.unknowns=[]
        self.gui={'driver':self.options['driver'],'complete':self.options['driver']=='none','steps':[],'states':[],'requests':[],'unknowns':[]}
        self.last_tick=0
        self.owned=[]
        self.pids_dirty=True
        self.port=None
        self.controlled_stop=False
        self.helper=None
        self.node=None
        self.private_profile=None
        self.directory.mkdir(parents=True,exist_ok=True)
        self.pids_file=self.directory/'owned-pids.json'
        self.output=self.directory/'graphical.json'
        driver=self.options['driver']
        self.arguments=list(arguments)
        if driver=='windows':
            self.helper=desktop_helper(context)
        elif driver in ('chromium','electron'):
            self.node=shutil.which('node')
            if not self.node:
                raise CyToolError('MissingDependency','Web and Electron capture require Node.js 22 or newer on PATH.')
            if any(str(a).startswith(('--remote-debugging','--user-data-dir','--profile-directory')) for a in arguments):
                raise CyToolError('InvalidParameters','Remote debugging and browser profile arguments are managed by the capture.')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));self.port=listener.getsockname()[1]
            # Chromium still creates paths that exceed MAX_PATH in deep project
            # stores. A new short temporary profile belongs only to this capture.
            import tempfile
            profile=Path(tempfile.mkdtemp(prefix='cydec-browser-'))
            self.private_profile=profile
            self.arguments.extend(['--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(self.port),
                '--user-data-dir='+str(profile)])
            if driver=='chromium':
                self.arguments.extend(['--no-first-run','--no-default-browser-check','--disable-background-networking','about:blank'])
                if self.options['headless']:
                    self.arguments.append('--headless=new')
        if self.options['network']:
            self.unknowns.append({'code':'tcp-sampling-can-miss-short-connections'})
        if driver in ('chromium','electron'):
            self.unknowns.append({'code':'http-capture-selected-renderer-only'})
            if driver=='electron':
                self.unknowns.append({'code':'renderer-startup-before-attachment-not-observed'})
        if driver=='windows':
            self.unknowns.append({'code':'native-screenshots-provider-dependent'})

    def start(self,target):
        self.target=target
        self.created=time.monotonic()
        self.tick(target,force=True)
        if self.options['driver']!='none':
            self.worker=threading.Thread(target=self._record,daemon=True)
            self.worker.start()

    def tick(self,target,force=False):
        if not force and time.monotonic()-self.last_tick<0.25:
            return
        self.last_tick=time.monotonic()
        import psutil
        try:
            root=psutil.Process(target.pid)
            processes=[root,*root.children(recursive=True)]
        except psutil.NoSuchProcess:
            return
        owned=[]
        for p in processes:
            try:owned.append({'pid':p.pid,'created':p.create_time()})
            except psutil.NoSuchProcess:pass
        if owned!=self.owned or self.pids_dirty:
            self.owned=owned
            try:
                write_json(self.pids_file,owned)
                self.pids_dirty=False
            except PermissionError:self.pids_dirty=True
        if self.options['network']:
            try:
                pids={p['pid'] for p in owned}
                for c in psutil.net_connections(kind='tcp'):
                    if c.pid not in pids or not c.raddr or c.raddr.port==self.port or c.laddr.port==self.port:
                        continue
                    key=(c.pid,c.laddr.ip,c.laddr.port,c.raddr.ip,c.raddr.port,c.status)
                    if key in self.seen:continue
                    if len(self.connections)>=5000:
                        if not any(r['code']=='network-connection-limit' for r in self.unknowns):self.unknowns.append({'code':'network-connection-limit'})
                        continue
                    self.seen.add(key)
                    self.connections.append({'pid':c.pid,'localAddress':c.laddr.ip,'localPort':c.laddr.port,
                        'remoteAddress':c.raddr.ip,'remotePort':c.raddr.port,'status':c.status,'elapsed':time.monotonic()-self.created})
            except (psutil.AccessDenied,PermissionError):
                if not any(r['code']=='network-observation-denied' for r in self.unknowns):self.unknowns.append({'code':'network-observation-denied'})

    def _record(self):
        ctx=EngineContext(Token(self.context.cancellation,self.stop),workdir=self.directory/'helper-logs',log=self.context._log)
        try:
            driver=self.options['driver']
            request=self.directory/'scenario.json'
            spec={**self.options,'pidsFile':str(self.pids_file)}
            if driver=='windows':
                command=[self.helper,request,self.output]
            else:
                import psutil
                deadline=time.monotonic()+15
                while True:
                    ctx.check()
                    owned={p['pid'] for p in self.owned}
                    listeners=[c for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==self.port and c.status=='LISTEN']
                    if listeners:
                        if any(c.pid not in owned for c in listeners):
                            raise CyToolError('AccessDenied','The renderer debug endpoint is not owned by this capture.')
                        break
                    if time.monotonic()>deadline:
                        raise CyToolError('Timeout','The application did not expose its renderer debug endpoint.')
                    time.sleep(0.1)
                spec['endpoint']='http://127.0.0.1:'+str(self.port)
                helper=Path(__file__).resolve().parents[1]/'javascript/capture.cjs'
                command=[self.node,'--max-old-space-size=256',helper,request,self.output]
            write_json(request,spec)
            code,out,err=process.run(command,context=ctx,timeout=300,log_name='graphical-capture',
                env={'NODE_OPTIONS':None,'NODE_PATH':None},output_limit=1024**2)
            self.gui=read_json(self.output)
            if not self.gui.get('driver'):
                self.gui={'driver':driver,'complete':False,'error':process.tail(out+err,10),'steps':[],'states':[],'requests':[],'unknowns':[]}
        except BaseException as error:
            self.gui=read_json(self.output) or self.gui
            self.gui.update(complete=False,error=str(error)[:2000])
        finally:
            self.finished.set()

    def should_stop(self):
        if self.worker and self.finished.is_set() and self.options['stopAfterScenario']:
            self.controlled_stop=True
            return True
        return False

    def close(self,target):
        self.stop.set()
        if self.worker:
            self.worker.join(timeout=15)
            if self.worker.is_alive():
                self.gui.update(complete=False,error='Runtime observer did not stop.')

    def result(self):
        limited=any(u['code'] in ('network-observation-denied','network-connection-limit') for u in self.unknowns)
        return {'options':self.options,'connections':self.connections,'gui':self.gui,
                'complete':bool(self.gui.get('complete')) and not limited,
                'unknowns':self.unknowns+[{'code':c} for c in self.gui.get('unknowns',[])],
                'termination':('scenario-failed' if self.gui.get('error') else 'scenario-complete') if self.controlled_stop else 'process-exit'}

    def cleanup(self):
        if self.private_profile:
            import tempfile
            from .javascript import is_link
            path=self.private_profile
            if path.parent.resolve()!=Path(tempfile.gettempdir()).resolve() or not path.name.startswith('cydec-browser-') or is_link(path):
                return
            shutil.rmtree(path,ignore_errors=True)
