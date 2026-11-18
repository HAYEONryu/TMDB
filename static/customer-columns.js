// Business columns shared by manager and employee grids. Values/permissions
// still come from the server; this only controls presentation.
export const customerLabels={customer_name:'고객명',phone_normalized:'연락처',contract_status:'계약여부',
  admin_notes:'관리자 비고',assignee_name:'담당직원명',call_result:'통화결과',notes:'상담내용',
  callback_due_at:'재콜일정',visit_at:'방문예약 날짜',residence:'고객 거주지',housing_status:'주택보유상황',
  route:'루트',memo:'비고',assigned_at:'배정일'};
const order=['customer_name','phone_normalized','contract_status','admin_notes','assignee_name',
  'call_result','callback_due_at','visit_at','residence','housing_status','notes','route','memo','assigned_at'];
export const customerFields=({admin=false}={})=>order.filter(field=>admin||!['admin_notes','assignee_name'].includes(field));
const gridLabels = { ...customerLabels, last_tm_date: '최종 TM 날짜', residence: '거주지',
  memo: '메모', visit_at: '방문예약날짜' };
export const employeeGridLabels = gridLabels;
export const employeeGridFields = ['customer_name', 'phone_normalized', 'call_result', 'residence',
  'notes', 'callback_due_at', 'memo', 'visit_at'];
export function choiceLabel(schema,field,value){
  if(value==null||value===''||(field==='contract_status'&&value==='UNKNOWN'))return '-';
  if(schema[field])return schema[field][value]??`이전값: ${schema._legacy?.[field]?.[value]??value}`;
  return String(value);
}
