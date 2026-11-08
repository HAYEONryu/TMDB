# AI 비활성 상태와 키 관리

현재 기준은 [현재 운영 기준](CURRENT_OPERATING_BASELINE.md)이다. **gemini / gemini-3.5-flash-lite / free**, 유료 승인$0이며 **AI_ENABLED=false·AI_FREE_TIER_CONFIRMED=false**를 유지한다. 이 준비 단계에서는 활성화하거나 실제 API를 호출하지 않는다.

`.env.ai.example`은 빈 값 예시다. 기존 실제 `.env.ai`를 덮어쓰지 않는다. 키는 서버의0600 파일 `AI_GEMINI_API_KEY`에만 두며 채팅·CLI 인수·Git·브라우저·로그에 넣지 않는다. web/ai_worker만 보호된 파일을 읽는다. 운영 UID10001의 읽기 권한을 파일 소유권으로 준비하고0644로 완화하지 않는다.

직원 세 기능 합산 KST 하루40회와 프로젝트 전체 한도를 분리하며 공용 한도를 먼저 검사한다. RPD500·RPM15·입력 TPM250,000은 **현재 계정에서 재확인되지 않은 과거 기록**이다. 실제 활성화 전에 Google 계정의 무료 티어·결제 미연결·정확한 모델/한도·잔여량·다른 앱 사용을 별도로 확인해야 한다. 확인 없이 true로 바꾸거나 이전 한도값을 보장값으로 복사하지 않는다.

무료 확인과 실사용 활성화가 별도 승인된 뒤에만 운영자는 보호된 파일을 편집하고 web/worker를 같은 DB·설정으로 재시작한다. 이번 단계에서는 실행하지 않는다. 중지할 때는 worker 종료→AI_ENABLED=false→web 재시작이다. 기존 결과는 권한 범위에서 조회할 수 있고 AI 장애/미설정 시 일반 고객관리는 계속 동작한다.

[이전 활성화 안내 원문](history/AI_ACTIVATION.before_operations_stage1_20261108.md)은 당시 확인 상태·모델·한도·검사 결과를 보존한 역사적 문서다. 그 문서의 true/유료 설정을 현재 운영값으로 사용하지 않는다.
