# TMDB 화면 비교

원본은 사용자가 제공한 `tmdb-figma-followup/employee.html`과 `admin.html`이다. 구현 화면은 로컬 PostgreSQL의 가상 직원·관리자·고객으로 열었다. 원본 예시 수치와 검증 데이터가 다르므로 수치 일치는 비교 대상에서 제외했다.

원본과 구현은 Chromium에서 동일한 1440×960 CSS px, 배율 1로 각각 캡처했다. 배치 비교는 각 화면의 위쪽을 같은 폭으로 잘라 50% 크기로 나란히 배치했다. 그리드 상세 비교는 헤더와 행을 1:1 픽셀로 맞췄다. 각 원본 PNG의 실제 크기와 캡처 위치는 [캡처 목록](outputs/html-followup-20261118/screenshot-manifest.json)에 기록했다. 구현은 390×960, 320×960에서도 검사했다.

| 화면 | 비교 상태와 근거 |
|---|---|
| 직원 대시보드 | 홈 기본 조회, 일정 상세를 닫은 상태. 파스텔 통화 카드와 일정·결과 나란히 배치를 확인했다. 기존 업무·계약 카드에 이어 페이지 마지막에 월 합계·그래프·표가 있다. [화면 비교](outputs/html-followup-20261118/employee-dashboard-comparison-final.png) |
| 직원 그리드 | 나의 DB 기본 목록. 최종 TM 날짜부터 같은 순서로 표시하고 미기록 날짜에 연한 주황 배경을 쓴다. 상담 입력과 기록 버튼 폭을 확보하기 위해 나머지 열은 그리드에서 가로로 이동한다. [전체](outputs/html-followup-20261118/employee-grid-comparison-final.png) · [1:1 헤더와 행](outputs/html-followup-20261118/grid-detail-comparison.png) · [320px](outputs/html-followup-20261118/followup-employee-grid-320.png) |
| 관리자 대시보드 | 현장 조회, 요약 차트 접기, 삭제 요청과 월간 실적 순서. 최신 캡처에서 간결한 막대와 상세 차트 진입을 확인했다. [화면 비교](outputs/html-followup-20261118/admin-dashboard-comparison-final.png) |
| DB 관리 | 조회 조건, 제목의 추가·업로드 버튼, 표의 직원명 옆 담당 변경을 확인했다. 기존 열 편집과 저장에 맞춰 새 고객을 그리드에서 등록한다. [화면 비교](outputs/html-followup-20261118/admin-db-comparison-final.png) |
| 분배·회수 | 현장 카드, 직원 선택 표와 분배·회수 카드. 320px에서도 선택과 작업 버튼을 사용할 수 있다. [화면 비교](outputs/html-followup-20261118/admin-assignments-comparison-final.png) · [320px](outputs/html-followup-20261118/assignments-followup-320.png) |
| AI 보고서 | 원본은 팀 상담 가이드 예시를 열고 구현은 기존 주간 브리핑 기본값으로 시작한다. 생성 영역, 선택 종류 안내와 실제 상태 영역을 확인했다. [화면 비교](outputs/html-followup-20261118/admin-ai-comparison-final.png) |

초기 비교에서 관리자 상세 그래프 때문에 삭제 요청과 월간 실적이 첫 화면 아래로 밀렸다. 동일 집계의 가로 막대를 상단에 배치하고 상세 그래프를 접어 배치를 개선했다. 직원 목록은 편집·저장·AI 안내를 접을 수 있게 해 표가 앞쪽에 보이도록 했다. 폭 320px에서 현장 선택 아래에 생긴 공백은 세로 배열의 크기 규칙을 조정해 제거했다. 연속 스크롤은 가상화 렌더 뒤 높이가 바뀌는 경우까지 확인하도록 수정했다.

글꼴은 시안과 같은 한국어 시스템 대체 글꼴 순서를 사용하며, 본문 15px와 헤더 14px를 확인했다. 날짜·연락처·숫자에 고정 폭 숫자 서식을 적용했다. 카드 간격·모서리·조작 버튼 높이, 밝은 배경·네이비 버튼·파스텔 지표와 선택 상태를 비교했다. 원본의 글자 브랜드에는 기존 제품 로고와 계정 메뉴를 적용했다. 별도 사진이나 장식 이미지는 두 원본 모두 요구하지 않는다. 시안 제목과 실제 도입일·빈 상태·조회 실패 안내를 함께 비교했다.

기존 기능을 유지하는 차이는 실제 계정 메뉴, 휴지통·사용자 관리, 직원 자동 저장 안내, 조회 월·기간 조작, 추가 차트와 작업 열이다. DB 관리에는 기존 페이지 이동을 사용한다. 직원 목록의 실데이터는 무한 스크롤로 이어진다. 브라우저 검증 결과와 화면별 증거는 [검증 요약](outputs/html-followup-20261118/verification-summary.json)에 연결했다.

final result: passed
