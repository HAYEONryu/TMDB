"""Privacy-safe projection of a Playwright trace; raw traces are temporary only."""
import json
import logging
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import urlsplit
import urllib.request
import zipfile

from scripts.verification_evidence import artifact_path,run_directory,write_new


def route_category(url):
    try:
        parsed=urlsplit(url)
        if parsed.scheme=='chrome-error':return 'chrome-error://chromewebdata/'
        if parsed.hostname not in {'localhost','127.0.0.1','::1'}:return '<external>'
        path=parsed.path
        if path in {'/auth/login','/auth/password','/auth/logout','/api/me','/healthz'}:return path
        for prefix in ['/api/employee/','/api/customers','/api/ai/','/api/dashboard','/app/','/static/']:
            if path.startswith(prefix):return prefix+'<redacted>'
    except (ValueError,TypeError):pass
    return '<redacted>'


def net_error(value):
    match=re.search(r'\b(?:net::)?ERR_[A-Z_]{1,64}\b',str(value or ''))
    return match.group(0) if match else 'UNCLASSIFIED_FAILURE'


def project_trace(raw,target):
    events=[]
    with zipfile.ZipFile(raw) as archive:
        for name in archive.namelist():
            if not name.endswith('.trace'):continue
            for line in archive.read(name).splitlines():
                try:event=json.loads(line)
                except (ValueError,TypeError):continue
                if event.get('type') not in {'before','after','context-options'}:continue
                safe={'type':event['type']}
                for key in ['callId','apiName','method','class','browserName']:
                    value=event.get(key)
                    if isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',value):safe[key]=value
                for key in ['startTime','endTime','version']:
                    value=event.get(key)
                    if type(value) in {int,float} and 0<=value<10**16:safe[key]=value
                if event.get('error'):safe['failed']=True
                # Params include fill(password), URLs, auth and request bodies.
                # Never copy params/results/stacks/snapshots/network/resources.
                events.append(safe)
    write_new(target,{'format':'playwright-trace-allowlist-v1','raw_trace_retained':False,
        'omitted':['params','results','stacks','snapshots','screenshots','network','headers','cookies','bodies','resources'],
        'events':events})


class ServerEvents(logging.Handler):
    def __init__(self,rows):super().__init__();self.rows=rows
    def emit(self,record):
        if record.name not in {'django.request','django.server'}:return
        row={'level':record.levelname,'logger':record.name}
        status=getattr(record,'status_code',None)
        if type(status) is int:row['status_code']=status
        self.rows.append(row)


class BrowserObservation:
    def __init__(self,context,health_url,server_thread=None):
        self.context=context;self.health_url=health_url;self.server_thread=server_thread
        self.failed=[];self.server_events=[];self.started=time.monotonic();self.finished=False
        self.target=artifact_path('network-observation-'+__import__('uuid').uuid4().hex)
        self.target.mkdir(mode=0o700)
        self.handler=ServerEvents(self.server_events)
        logging.getLogger('django').addHandler(self.handler)
        context.on('requestfailed',self.failure)
        context.tracing.start(screenshots=False,snapshots=False,sources=False)

    def failure(self,request):
        self.failed.append({'elapsed_seconds':round(time.monotonic()-self.started,3),
            'route':route_category(request.url),'method':request.method if request.method in {'GET','POST','PATCH','PUT','DELETE','HEAD','OPTIONS'} else 'OTHER',
            'failure':net_error(request.failure)})

    def finish(self):
        if self.finished:return
        self.finished=True
        try:
            state={'run_id':run_directory().name,'server_thread_alive':self.server_thread.is_alive() if self.server_thread else None,
                'chrome_error_observed':any(p.url.startswith('chrome-error://') for p in self.context.pages),
                'root_cause':'UNCONFIRMED','trace_status':'not_saved'}
            try:
                with urllib.request.urlopen(self.health_url,timeout=3) as response:state['health_status']=response.status
            except Exception:state['health_status']='unavailable'
            # Raw trace is never stored under the run artifact directory. It is
            # deleted even if allowlist processing fails; no raw fallback exists.
            try:
                with tempfile.TemporaryDirectory(prefix='tm-private-trace-') as directory:
                    raw=Path(directory)/'raw.zip'
                    self.context.tracing.stop(path=str(raw))
                    raw.chmod(0o600)
                    project_trace(raw,self.target/'browser-trace.json')
                state['trace_status']='sanitized_projection_saved'
            except Exception:
                state['trace_status']='capture_failed_raw_not_retained'
            write_new(self.target/'observation.json',state)
            write_new(self.target/'failed-requests.json',self.failed)
            write_new(self.target/'server-events.json',self.server_events)
        finally:
            logging.getLogger('django').removeHandler(self.handler)
