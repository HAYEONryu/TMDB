"""Build the current acceptance matrix from one explicit verification run."""
import json
import argparse
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.verify_acceptance import verify,source_digest
from scripts.verification_evidence import write_new


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--boundary',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads((args.run_dir/'results.json').read_text())
    boundary=json.loads(args.boundary.read_text())
    result=verify(ROOT,report,suite='all',boundary=boundary)
    rows=[]
    for row in result['items']:
        values=row['evidence'].values()
        status='통과' if row['status']=='passed' else '실패' if any(v in {'failed','error','unexpected_success'} for v in values) else '미검증'
        rows.append({**row,'current_criterion':row['criterion'],'current_status':status})
    result['items']=rows
    result['counts']={status:sum(r['current_status']==status for r in rows) for status in ['통과','실패','미검증']}
    result['scope']='Fresh synthetic local checks; AI semantic accuracy limited to fixtures; production readiness separately assessed.'
    write_new(args.run_dir/'acceptance.json',result)
    lines=['# 현재 인수 기준 검증 결과','',
        f"검사 완료(UTC): `{report['finished_at']}`. 현재 실행 Django {report['tests_run']}개. 소스 SHA `{source_digest(ROOT)}`.",'',
        '저장소의 docs/ACCEPTANCE_CRITERIA.md 및 검수 manifest의 현재 기준을 사용한다.',
        '이번 실행의 개별 결과와 동일 소스만 사용했다. 누락·skip·환경 미실행은 미검증이며 과거 통과를 가져오지 않는다. AI 사실성·공격 방어 통과는 모의 응답과 지정 근거 사례 범위이며 실제 모델의 모든 출력 품질을 보증하지 않는다. 실제 23시 벽시계 관찰·운영 HTTPS·서버 성능은 이 표 밖 운영 미검증 항목이다.','',
        '| ID | 현재 인수 기준 | 결과 | 이번 실행 근거 |','|---|---|---|---|']
    for row in rows:
        evidence='<br>'.join(f'`{name}`: {value}' for name,value in row['evidence'].items())
        lines.append(f"| {row['id']} | {row['current_criterion']} | {row['current_status']} | {evidence} |")
    lines+=['',f"**통과 {result['counts']['통과']} · 실패 {result['counts']['실패']} · 미검증 {result['counts']['미검증']} / 92항목.**",'',
        f"재현 원시 결과: `{args.run_dir / 'results.json'}`, `{args.boundary}`. 현재 보고서는 이 실행 디렉터리의 `acceptance.json`과 `acceptance.md`에 기록한다.",'']
    with (args.run_dir/'acceptance.md').open('x') as handle:handle.write('\n'.join(lines))
    print(json.dumps(result['counts'],ensure_ascii=False))


if __name__=='__main__':
    main()
