"""Build the current P13 matrix without reusing old pass records."""
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
    overrides={
        '18.8-01':'직원의 세 AI 기능은 버튼을 눌렀을 때만 실행되고 합산 한국 날짜 하루 40회로 제한된다.',
        '18.8-03':'39회 성공 상태에서 여러 탭이 동시에 요청해도 성공+예약 합계가 40회를 넘지 않는다.',
        '18.8-06':'외부 처리 여부가 불명확한 timeout은 자동 재전송하지 않으며 유료 전환·다른 모델 자동 전환은 금지한다.'}
    rows=[]
    for row in result['items']:
        values=row['evidence'].values()
        status='통과' if row['status']=='passed' else '실패' if any(v in {'failed','error','unexpected_success'} for v in values) else '미검증'
        rows.append({**row,'current_criterion':overrides.get(row['id'],row['criterion']),'current_status':status})
    result['items']=rows
    result['counts']={status:sum(r['current_status']==status for r in rows) for status in ['통과','실패','미검증']}
    result['scope']='Fresh synthetic local checks; AI semantic accuracy limited to fixtures; production readiness separately assessed.'
    write_new(args.run_dir/'acceptance.json',result)
    lines=['# 최종 P13 인수 기준 — 현재 코드 재검증','',
        f"검사 완료(UTC): `{report['finished_at']}`. 현재 실행 Django {report['tests_run']}개. 소스 SHA `{source_digest(ROOT)}`.",'',
        '원 설계 v2.0의 92개 ID를 유지하며 18.8-01/03은 사용자 최종 승인인 40회·39회 경계로 대체했다. 원문과 과거 P13 기록은 보존한다. 유료 재시도 조건도 무료 전용 조건으로 대체한다.',
        '이번 실행의 개별 결과와 동일 소스만 사용했다. 누락·skip·환경 미실행은 미검증이며 과거 통과를 가져오지 않는다. AI 사실성·공격 방어 통과는 모의 응답과 지정 근거 사례 범위이며 실제 모델의 모든 출력 품질을 보증하지 않는다. 실제 23시 벽시계 관찰·운영 HTTPS·서버 성능은 이 표 밖 운영 미검증 항목이다.','',
        '| ID | 현재 인수 기준 | 결과 | 이번 실행 근거 |','|---|---|---|---|']
    for row in rows:
        evidence='<br>'.join(f'`{name}`: {value}' for name,value in row['evidence'].items())
        lines.append(f"| {row['id']} | {row['current_criterion']} | {row['current_status']} | {evidence} |")
    lines+=['',f"**통과 {result['counts']['통과']} · 실패 {result['counts']['실패']} · 미검증 {result['counts']['미검증']} / 92항목.**",'',
        '정원·권한 변경 후 AI·무료 전용·25명 부하·3자 경합 추가 검사는 [최종 통합 보고서](FINAL_VERIFICATION.md)에 별도로 연결한다. 재현 원시 결과: `.local/final-test/release-results.json`, `acceptance.json`, `boundary.json`.','']
    with (args.run_dir/'acceptance.md').open('x') as handle:handle.write('\n'.join(lines))
    print(json.dumps(result['counts'],ensure_ascii=False))


if __name__=='__main__':
    main()
