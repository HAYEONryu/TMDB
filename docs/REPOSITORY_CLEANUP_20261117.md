# 오래된 문서·화면 자료·미사용 코드 정리

2026-11-17 KST. `main` / `7386728bb9215f2ea076e2619f4c0ddc75e93744`에서 진행했다. 기존 미커밋 UI 변경과 최신 화면·검증 자료를 보존하고 변경을 로컬 작업 트리에 남겼다.

## 제거·통합

| 대상 | 정리 내용 |
|---|---|
| 대체된 문서 48개 | P1~P13 단계별 보고서·검수표, 이전 전체 설계/계획/진행 로그, 이전 AI 모델·요금 안내, 중복 대시보드 설명, 이전 시연 안내, `docs/history/` 제거 |
| 이전 화면 자료 5개 | 현재 상단 메뉴와 다른 `outputs/ui-blue/*.png` 제거. 최신 `outputs/ui-consistency-20261116/` 보존 |
| 이전 엑셀 산출물 4개 | 9열 시연 파일과 이전 주택상황 제목의 빈 양식 복사본 제거. 현재 양식은 앱의 엑셀 업로드 화면에서 생성·다운로드 |
| 미사용 CSS | `static/app.css`에서 템플릿·화면 스크립트에 참조가 없는 30개 클래스 계열의 선택자 145개와 이전 사이드바 폭·배치 규칙 제거 |
| 검수 도구 | 오래된 설계서 파싱·P8 기본 파일 경로·P13 문구 덮어쓰기 제거. 실제 실행 결과를 명시적으로 받고 새 결과 파일만 생성 |
| 검수 목록 | 현재 이름/연락처 편집 권한·전체 현장 중복 정책·AI 40회 경계를 반영. 사라진 테스트 참조와 29/30회라는 오래된 테스트 이름 수정 |
| 현재 문서 | README·운영 기준을 현행 안내로 통합. 현재 문서 링크·화면 버튼 이름·직원 이름 편집 권한·migration 안내 정리 |

기존 92개 검수 ID와 실제 실행 근거 연결은 [현재 검수 기준](ACCEPTANCE_CRITERIA.md)에 보존했다. 이 목록은 전체 통과 결과가 아니다. 이전 버전은 Git 이력에서 확인할 수 있다. 실행별 원시 검증 자료는 `.local/verification-runs/`에 보존한다.

DB migration·업무 서비스·동작하는 입력 호환 코드·운영/데모 DB·비밀 파일은 변경하지 않았다. 기존 9열 업로드를 읽는 서버 호환 기능은 유지한다. 이 작업에서 커밋·푸시·배포·실제 AI 호출 명령은 실행하지 않았다. 최종 확인 중 외부에서 HEAD가 `1079c71`로 변경되어 앞선 UI 변경과 정리 내용이 커밋된 것을 확인했으며 되돌리지 않았다. 그 뒤 추가한 문서 정리는 미커밋 상태로 남겼다.

## 이번 검증

| 검사 | 결과 |
|---|---|
| 서버·Chromium 114개 | 모두 통과. 검수 근거 누락/skip/소스 변경 거절, 결과 덮어쓰기 방지, 현재 테스트 참조, AI 40회 경합, 권한·연락처 중복·업로드, 데스크톱/320px/390px 메뉴·대화상자·초점·상태 확인 |
| Node 50개 | 모두 통과. `node --test --test-reporter=dot tests/*.test.mjs` |
| Django 시스템·migration drift | 통과 |
| Python 구문·`git diff --check` | 통과 |
| README·현재 문서의 로컬 링크 | 끊어진 파일 링크 없음 |

서버·브라우저 실행 ID: `20261116T154649337489Z-79e679558cfb428e8ccf68761312b91a`.
시스템 검사 실행 ID: `20261116T154755302640Z-5dfb14f87915420691e086bb896390e6`.
서버·브라우저 실행의 `source_unchanged_during_run`은 true이며 최종 소스 해시도 일치한다. 시스템 검사·migration drift는 각각 종료 코드 0이다. 서로 다른 소스의 결과를 합산하지 않았다.

```sh
.venv/bin/python scripts/run_final_verification.py start
.venv/bin/python scripts/run_final_verification.py test --label outdated-cleanup \
  tests.test_acceptance tests.test_stage1_evidence tests.test_p9 \
  tests.test_customer_identity tests.test_live_contact_policy tests.test_imports \
  tests.browser_common_ui tests.browser_ui
.venv/bin/python scripts/run_final_verification.py check --label outdated-cleanup-check
node --test --test-reporter=dot tests/*.test.mjs
.venv/bin/python scripts/run_final_verification.py stop
```

이번 검증은 정리 영향 범위다. 전체 92개 인수 항목 재실행, 실제 Docker 이미지·운영 서버·공인 HTTPS·외부 AI 품질 검증은 수행하지 않았다. 앞선 UI 구현의 검증 기록은 [별도 UI 기록](UI_CONSISTENCY_20261116.md)에 유지하며 이번 결과와 구분한다.
