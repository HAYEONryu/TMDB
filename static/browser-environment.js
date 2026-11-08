const httpsMessage = '직원 상담 저장은 HTTPS 접속이 필요합니다. 관리자에게 HTTPS 주소를 요청해 주세요. 현재 연결에서는 상담 편집을 시작할 수 없습니다.';
function issue(code, message) { return Object.assign(new Error(message), {code}); }

export function storageSupportError(env = globalThis) {
  if (env.isSecureContext === false) return issue('HTTPS_REQUIRED', httpsMessage);
  try {
    const crypto = env.crypto;
    if (typeof env.TextEncoder !== 'function' || typeof env.TextDecoder !== 'function') {
      return issue('SECURE_STORAGE_UNSUPPORTED', '안전한 상담 저장을 지원하는 최신 브라우저를 사용해 주세요.');
    }
    if (!['importKey', 'encrypt', 'decrypt'].every(name => typeof crypto?.subtle?.[name] === 'function')
        || typeof crypto?.getRandomValues !== 'function') {
      return issue('SECURE_STORAGE_UNSUPPORTED', '안전한 상담 저장을 지원하는 최신 브라우저에서 HTTPS로 접속해 주세요.');
    }
    if (typeof env.indexedDB?.open !== 'function') {
      return issue('STORAGE_UNAVAILABLE', '브라우저 저장소를 사용할 수 없습니다. 사이트 저장 권한과 브라우저 설정을 확인해 주세요.');
    }
  } catch {
    return issue('STORAGE_UNAVAILABLE', '브라우저 저장소 접근이 차단되어 상담 편집을 시작할 수 없습니다. 사이트 저장 권한을 확인해 주세요.');
  }
  return null;
}

export function lockSupportError(env = globalThis) {
  if (env.isSecureContext === false) return issue('HTTPS_REQUIRED', httpsMessage);
  try {
    if (typeof env.navigator?.locks?.request === 'function') return null;
  } catch {}
  return issue('SAVE_LOCK_UNSUPPORTED', '안전한 다중 탭 저장을 지원하지 않습니다. 최신 Chrome 또는 Edge에서 HTTPS로 접속해 주세요.');
}

export function employeeSupportError(env = globalThis) {
  return storageSupportError(env) || lockSupportError(env);
}
