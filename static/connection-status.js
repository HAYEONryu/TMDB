if (globalThis.isSecureContext === false && document.body.dataset.userId) {
  const warning = document.getElementById('connection-warning');
  if (warning) {
    warning.textContent = '현재 HTTP 연결입니다. 로그인·고객정보 보호와 직원 상담 저장을 위해 HTTPS로 접속해 주세요.';
    warning.hidden = false;
  }
}
