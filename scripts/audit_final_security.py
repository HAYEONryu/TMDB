"""Read-only audit; records booleans/counts, never keys, PII, or DSNs."""
import hashlib
import argparse
import json
from pathlib import Path
import stat
import subprocess
import sys
from datetime import datetime,timezone
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_acceptance import source_digest
from scripts.verification_evidence import RunRecord,write_new


def main():
    record=RunRecord('security-audit',['python','scripts/audit_final_security.py'])
    ai=dict(dotenv_values(ROOT/'.env.ai',interpolate=False))
    secrets=[v.encode() for k,v in ai.items() if k in {'AI_GEMINI_API_KEY','AI_API_KEY'} and v]
    if not secrets:
        raise RuntimeError('No current credential available for equality audit')
    tracked=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True).stdout.split(b'\0')
    ignored=subprocess.run(['git','check-ignore','-q','.env.ai'],cwd=ROOT).returncode==0
    excluded={'.git','.venv','.cache','__pycache__','node_modules'}
    extensions={'.py','.js','.mjs','.css','.html','.json','.log','.txt','.md','.map','.svg','.yaml','.toml'}
    files=[]
    for p in ROOT.rglob('*'):
        if any(part in excluded for part in p.relative_to(ROOT).parts) or not p.is_file():continue
        if p.suffix in extensions and p.stat().st_size<30_000_000:files.append(p)
    matches=sum(any(key in p.read_bytes() for key in secrets) for p in files)
    index_matches=0
    for path in tracked:
        if not path:continue
        raw=subprocess.run(['git','show',':'+path.decode()],cwd=ROOT,capture_output=True,check=True).stdout
        index_matches+=any(key in raw for key in secrets)
    objects=subprocess.run(['git','rev-list','--objects','--all'],cwd=ROOT,capture_output=True,check=True).stdout.splitlines()
    history_matches=0
    for row in objects:
        oid=row.split(b' ',1)[0].decode()
        raw=subprocess.run(['git','cat-file','-p',oid],cwd=ROOT,capture_output=True,check=True).stdout
        history_matches+=any(key in raw for key in secrets)
    before=json.loads((ROOT/'.local/final-test/protected-before.json').read_text())
    unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest for p,digest in before.items())
    app=dict(dotenv_values(ROOT/'.env',interpolate=False))
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'source_digest':source_digest(ROOT),
        'key_file_mode_0600':stat.S_IMODE((ROOT/'.env.ai').stat().st_mode)==0o600,
        'key_file_git_ignored':ignored,'key_file_tracked':b'.env.ai' in tracked,
        'files_scanned':len(files),'current_key_matches_in_files':matches,
        'current_key_matches_in_index':index_matches,'current_key_matches_in_git_objects':history_matches,
        'protected_env_files_unchanged':unchanged,'ai_enabled':ai.get('AI_ENABLED')=='true',
        'free_tier_confirmed':ai.get('AI_FREE_TIER_CONFIRMED')=='true',
        'provider_model_match':(ai.get('AI_PROVIDER'),ai.get('AI_MODEL'))==('gemini','gemini-3.5-flash-lite'),
        'usage_tier_free':ai.get('AI_USAGE_TIER')=='free',
        'configured_limits':{name:int(ai.get('AI_FREE_'+name.upper()) or 0) for name in ['rpm','tpm','rpd']},
        'local_debug':app.get('DJANGO_DEBUG','false').lower()=='true',
        'docker_layers_verified':False,'remote_tier_and_remaining_verified':False}
    write_new(record.path/'results.json',report)
    code=int(bool(matches or index_matches or history_matches or not unchanged or not ignored or b'.env.ai' in tracked))
    record.finish(code)
    print(json.dumps({'run_id':record.run_id,'exit_code':code,'directory':str(record.path)}))
    return code


if __name__=='__main__':
    raise SystemExit(main())
