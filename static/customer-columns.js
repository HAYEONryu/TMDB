// Business columns shared by manager and employee grids. Values/permissions
// still come from the server; this only controls presentation.
export const customerLabels={customer_name:'고객명',phone_normalized:'연락처',contract_status:'계약여부',
  admin_notes:'관리자 비고',assignee_name:'담당직원명',call_result:'통화결과',notes:'상담내용',
  callback_due_at:'재콜일정',visit_at:'방문예약 날짜',residence:'고객 거주지',housing_status:'주택상황',
  route:'루트',memo:'비고',assigned_at:'할당일'};
const order=['customer_name','phone_normalized','contract_status','admin_notes','assignee_name',
  'call_result','notes','callback_due_at','visit_at','residence','housing_status','route','memo','assigned_at'];
export const customerFields=({admin=false}={})=>order.filter(field=>admin||field!=='admin_notes');
