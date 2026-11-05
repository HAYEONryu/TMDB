export async function api(url, body, method = "POST", extraHeaders = {}) {
  const csrf = document.cookie.split("; ").find(v => v.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  const multipart = body instanceof FormData;
  const response = await fetch(url, {method: body === undefined ? "GET" : method,
    credentials: "same-origin", headers: {...(body === undefined ? {} : {...(multipart ? {} : {"Content-Type": "application/json"}), "X-CSRFToken": csrf || ""}),...extraHeaders},
    ...(body === undefined ? {} : {body: multipart ? body : JSON.stringify(body)})});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error?.message || `요청 실패 (${response.status}). 현재 화면에서 다시 시도해 주세요.`);
    error.code = data.error?.code;
    error.status = response.status;
    error.data = data;
    throw error;
  }
  return data;
}
export function option(value, label) { return new Option(label, value); }
