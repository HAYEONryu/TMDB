"""Durable ten-request limit for this explicitly authorized free-tier experiment."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo
import fcntl
import json
import os
import tempfile

MODEL = 'gemini-3.5-flash-lite'
MAX_REQUESTS = 10
FEATURES = {'SUMMARY','CLEANUP','NEXT_QUESTIONS','WEEKLY_BRIEFING','EMPLOYEE_COACHING','TEAM_GUIDE'}
PACIFIC = ZoneInfo('America/Los_Angeles')


class ExperimentStopped(Exception): pass


class ExperimentWait(Exception):
    def __init__(self, seconds): self.seconds=seconds


class ExperimentBudget:
    def __init__(self, directory, confirmation, *, clock=None):
        self.directory=Path(directory)
        self.confirmation=confirmation
        self.clock=clock or (lambda: datetime.now(timezone.utc))

    def validate_confirmation(self):
        c=self.confirmation;now=self.clock()
        if (c.get('provider')!='gemini' or c.get('model')!=MODEL or not c.get('project_id')
            or c.get('free_tier') is not True or c.get('billing_linked') is not False
            or c.get('credential_replaced') is not True or c.get('other_apps_paused') is not True):
            raise ExperimentStopped('FREE_TIER_CONFIRMATION_REQUIRED')
        for name in ['rpm','tpm','rpd','remaining_rpd']:
            if type(c.get(name)) is not int or c[name]<=0: raise ExperimentStopped('QUOTA_CONFIRMATION_REQUIRED')
        if c['remaining_rpd']>c['rpd']: raise ExperimentStopped('QUOTA_CONFIRMATION_INVALID')
        try: observed=datetime.fromisoformat(c['observed_at'])
        except (KeyError,TypeError,ValueError): raise ExperimentStopped('CONFIRMATION_TIME_REQUIRED') from None
        if (observed.tzinfo is None or observed>now or now-observed>timedelta(hours=2)
            or observed.astimezone(PACIFIC).date()!=now.astimezone(PACIFIC).date()):
            raise ExperimentStopped('CONFIRMATION_EXPIRED')
        return sha256((c['project_id']+'\0'+MODEL).encode()).hexdigest()

    @contextmanager
    def locked(self):
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(self.directory/'budget.lock',os.O_CREAT|os.O_RDWR,0o600)
        with os.fdopen(fd,'r+') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield

    def read(self):
        path=self.directory/'state.json'
        if not path.exists():return {'version':1,'model':MODEL,'limit':MAX_REQUESTS,'calls':[]}
        try: state=json.loads(path.read_text())
        except (OSError,ValueError): raise ExperimentStopped('BUDGET_LEDGER_INVALID') from None
        if (state.get('version')!=1 or state.get('model')!=MODEL or state.get('limit')!=MAX_REQUESTS
            or not isinstance(state.get('calls'),list) or len(state['calls'])>MAX_REQUESTS):
            raise ExperimentStopped('BUDGET_LEDGER_INVALID')
        return state

    def save(self,state):
        fd,name=tempfile.mkstemp(prefix='budget-',dir=self.directory)
        try:
            with os.fdopen(fd,'w') as handle:
                json.dump(state,handle,ensure_ascii=False,indent=2);handle.write('\n');handle.flush();os.fsync(handle.fileno())
            os.replace(name,self.directory/'state.json')
        finally:
            if os.path.exists(name):os.unlink(name)

    def eligible(self,state,input_cap):
        if state.get('closed'):raise ExperimentStopped('EXPERIMENT_COMPLETED')
        scope=self.validate_confirmation();now=self.clock();c=self.confirmation
        if state.get('project_scope',scope)!=scope:raise ExperimentStopped('PROJECT_CHANGED')
        if len(state['calls'])>=MAX_REQUESTS:raise ExperimentStopped('EXPERIMENT_TEN_REQUEST_LIMIT')
        today=now.astimezone(PACIFIC).date()
        day_calls=[row for row in state['calls'] if datetime.fromisoformat(row['started_at']).astimezone(PACIFIC).date()==today]
        # Conservative on resume: subtract all our same-day starts, including unknowns.
        if len(day_calls)>=min(c['rpd'],c['remaining_rpd']):raise ExperimentStopped('FREE_DAILY_LIMIT')
        if type(input_cap) is not int or not 0<input_cap<=c['tpm']:raise ExperimentStopped('INPUT_TOKEN_LIMIT')
        recent=[row for row in state['calls'] if row['status'] in {'STARTED','UNKNOWN'} or datetime.fromisoformat(row['started_at'])+timedelta(seconds=60)>now]
        if len(recent)>=c['rpm'] or sum(row.get('prompt_tokens',row['input_cap']) for row in recent)+input_cap>c['tpm']:
            deadlines=[datetime.fromisoformat(row['started_at'])+timedelta(seconds=60) for row in recent if row['status'] not in {'STARTED','UNKNOWN'}]
            seconds=max(1,int((min(deadlines)-now).total_seconds())+1) if deadlines else 60
            raise ExperimentWait(min(seconds,60))
        return scope

    def check(self,input_cap):
        with self.locked():self.eligible(self.read(),input_cap)

    def send(self,feature,input_cap,body,key,transport):
        if feature not in FEATURES:raise ExperimentStopped('FEATURE_INVALID')
        with self.locked():
            state=self.read();scope=self.eligible(state,input_cap)
            state['project_scope']=scope
            number=len(state['calls'])+1
            state['calls'].append({'number':number,'feature':feature,'started_at':self.clock().isoformat(),
                                   'input_cap':input_cap,'status':'STARTED'})
            self.save(state)  # Persist before touching the network. Never decrement.
        try: status,data,tier=transport(body,key)
        except Exception:
            with self.locked():
                state=self.read();state['calls'][number-1]['status']='UNKNOWN';self.save(state)
            raise ExperimentStopped('TRANSPORT_OUTCOME_UNKNOWN') from None
        with self.locked():
            state=self.read();row=state['calls'][number-1]
            row.update(status='HTTP_'+str(status),finished_at=self.clock().isoformat())
            usage=data.get('usageMetadata',{}) if isinstance(data,dict) else {}
            for source,target in [('promptTokenCount','prompt_tokens'),('candidatesTokenCount','output_tokens'),('thoughtsTokenCount','thinking_tokens'),('cachedContentTokenCount','cached_tokens'),('totalTokenCount','total_tokens')]:
                if source not in usage:continue
                value=usage[source]
                if type(value) is int and value>=0:row[target]=value
            if isinstance(data,dict) and isinstance(data.get('error'),dict):
                code=data['error'].get('status')
                if code in {'INVALID_ARGUMENT','UNAUTHENTICATED','PERMISSION_DENIED','NOT_FOUND','RESOURCE_EXHAUSTED','INTERNAL','UNAVAILABLE','FAILED_PRECONDITION'}:row['error_code']=code
            self.save(state)
        return status,data,tier
