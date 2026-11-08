"""Append-only, value-free verification evidence. No raw subprocess output."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[1]
RUNS=ROOT/'.local/verification-runs'


def instant():
    return datetime.now(timezone.utc).isoformat()


def write_new(path, value):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as handle:
        json.dump(value,handle,ensure_ascii=False,indent=2)
        handle.write('\n');handle.flush();os.fsync(handle.fileno())


def code_version(root=ROOT):
    from scripts.verify_acceptance import source_digest
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
    status=subprocess.run(['git','status','--porcelain','-z'],cwd=root,capture_output=True,check=True).stdout
    # Names/content of untracked credentials or customer files are not recorded.
    return {'git_head':head,'worktree_dirty':bool(status),'source_digest':source_digest(root)}


class RunRecord:
    def __init__(self,label,command,*,root=RUNS,version=None):
        if not re.fullmatch(r'[\w.-]{1,80}',label):raise ValueError('Invalid human label')
        # Commands must be supplied as public, structured metadata by the caller;
        # actual credentials are passed via env/files and never CLI arguments.
        if any(not isinstance(a,str) or re.search(r'://|(?i:password|api[_-]?key|token)=',a) for a in command):
            raise ValueError('Command metadata may not contain credentials or URLs')
        root=Path(root);root.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex
        self.path=root/self.run_id
        self.path.mkdir(mode=0o700)
        write_new(self.path/'started.json',{'run_id':self.run_id,'label':label,'started_at':instant(),
            'process_id':os.getpid(),
            'code_version':version if version is not None else code_version(),
            'command':command,'result_file':'results.json','log_file':'events.jsonl',
            'raw_stdout_stderr_retained':False,'sensitive_values_policy':'allowlist only; no bodies, cookies, headers, raw exceptions'})
        self.event('started')

    def event(self,name,**fields):
        row={'run_id':self.run_id,'at':instant(),'event':name,**fields}
        fd=os.open(self.path/'events.jsonl',os.O_WRONLY|os.O_APPEND|os.O_CREAT,0o600)
        with os.fdopen(fd,'w') as handle:handle.write(json.dumps(row,ensure_ascii=False)+'\n')

    def finish(self,exit_code,*,status=None,reason=None):
        # Separate immutable end record; SIGKILL leaves started.json without a
        # finish, explicitly an interrupted run rather than a false success.
        value={'run_id':self.run_id,'finished_at':instant(),'exit_code':exit_code,
            'status':status or ('passed' if exit_code==0 else 'failed'),
            'result_file':'results.json' if (self.path/'results.json').exists() else None}
        if reason:value['reason']=reason
        write_new(self.path/'finished.json',value)
        self.event('finished',exit_code=exit_code,status=value['status'])


def run_directory():
    value=os.environ.get('TM_EVIDENCE_RUN_DIR')
    if not value:return None
    path=Path(value).resolve()
    if not (path/'started.json').is_file():raise RuntimeError('Evidence run was not initialized')
    return path


def artifact_path(name):
    """Keep legacy test artifacts away from historical and parallel runs."""
    path=run_directory()
    if path is None:
        # Direct manage.py test without our runner still gets isolated artifacts.
        record=RunRecord('unmanaged-tests',['manage.py','test'])
        os.environ['TM_EVIDENCE_RUN_DIR']=str(record.path);path=record.path
    test=os.environ.get('TM_EVIDENCE_TEST_ID','suite')
    key=hashlib.sha256(test.encode()).hexdigest()[:16]
    clean=Path(name)
    if clean.is_absolute() or '..' in clean.parts:raise ValueError('Artifact path must be relative')
    target=path/'artifacts'/key/clean
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    return target
