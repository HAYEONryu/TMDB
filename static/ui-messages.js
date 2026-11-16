// A missing/5xx response does not prove that a write failed.
export const uncertainResult=error=>!error.status||error.status>=500||[408,429].includes(error.status);
export function mutationMessage(error,action='저장'){
  return uncertainResult(error)?`${action} 결과를 확인하지 못했습니다. ${error.message} 같은 요청으로 처리 결과를 확인하세요.`:`${action}하지 못했습니다. ${error.message}`;
}
