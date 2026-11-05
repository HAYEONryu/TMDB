import {api} from './api.js';
let generation=0;
const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=value??'';return node;};
export async function renderDashboard(site){
  const current=++generation,area=document.querySelector('#dashboard-statistics'),message=document.querySelector('#dashboard-message');
  message.textContent='조회 중…';area.replaceChildren();
  try{
    const data=await api('/api/dashboard'+(site?'?'+new URLSearchParams({site_id:site}):''),undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});if(current!==generation)return;
    area.replaceChildren();message.textContent=`${data.business_date} · 한국 시각 기준 · 조회 시점 ${new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',timeStyle:'short',hourCycle:'h23'}).format(new Date(data.as_of))}`;
    if(data.employee){
      const e=data.employee,items=[['오늘 할당받은 고유 DB',e.assigned_today_unique],['오늘 재콜할 DB (오늘·과거 미완료)',e.callbacks_due_today_or_past],['오늘 신규 할당 현재 보유',e.current_assignment_today_held],['기한 지난 재콜',e.callbacks_overdue],['현재 보유 전체',e.held_total]];
      const list=document.createElement('dl');list.className='dashboard-cards';for(const [label,value] of items){const card=document.createElement('div');card.append(text('dt',label),text('dd',value));list.append(card);}area.append(list);
    }else{
      const table=document.createElement('table');table.className='table dashboard-table';const head=document.createElement('thead'),header=document.createElement('tr');
      for(const label of ['활성 직원','오늘 할당 고유 DB','오늘 할당 작업 횟수','현재 보유 전체','오늘 할당 중 현재 보유','회수·이관·삭제된 DB','미진행: 오늘 할당 중 현재 보유','미진행: 현재 보유 전체','오늘 할당 중 현재 보유의 통화결과'])header.append(text('th',label));head.append(header);table.append(head);const body=document.createElement('tbody');
      for(const e of data.employees){const tr=document.createElement('tr');tr.dataset.employeeId=e.id;for(const value of [e.name,e.assigned_today_unique,e.assignment_operations_today,e.held_total,e.assigned_today_held,e.assigned_today_removed,e.unprogressed_today_held,e.unprogressed_total,e.call_results.map(r=>`${r.label} ${r.count}`).join(' · ')])tr.append(text('td',value));body.append(tr);}table.append(body);area.append(table,text('p',`비활성 직원의 진행 DB · 이관 필요 ${data.transfer_needed}건 (선택 현장)`));
      if(!data.employees.length)area.append(text('p','활성 직원이 없습니다.'));
    }
  }catch(error){if(current===generation){area.replaceChildren();message.textContent=error.message;}}
}
