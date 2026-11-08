// Keep the timeout active until the complete action, including JSON parsing, ends.
export async function withRequestTimeout(action, milliseconds = 10000) {
  if (typeof globalThis.AbortController !== 'function') {
    throw new Error('요청을 안전하게 처리할 수 없습니다. 최신 브라우저를 사용해 주세요.');
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), milliseconds);
  try {
    const result = await action(controller.signal);
    // A caller may catch a body-read AbortError. Never report that as success.
    if (controller.signal.aborted) throw new Error('aborted');
    return result;
  } catch (error) {
    if (!controller.signal.aborted) throw error;
    throw Object.assign(new Error('요청 시간이 초과되었습니다. 저장 상태를 확인한 뒤 같은 요청으로 다시 시도해 주세요.'), {code: 'REQUEST_TIMEOUT'});
  } finally {
    clearTimeout(timer);
  }
}
