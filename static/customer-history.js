const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=value??'';return node;};
const date=value=>value?new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'short',hourCycle:'h23'}).format(new Date(value)):'';
import {customerLabels as labels} from './customer-columns.js';
const sources={MANUAL:'업무 저장',IMPORT:'엑셀 등록',BASELINE:'도입 기준 기록',AI_APPLIED:'AI 추천 적용',SYSTEM_DELETE_NOTE:'삭제 승인 문구'};
export function installHistory(request){
  const schema=JSON.parse(document.querySelector('#customer-schema').textContent);
  const value=(field,item)=>item==null||item===''?'(빈 값)':['visit_at','callback_due_at'].includes(field)?date(item):schema[field]?.[item]??String(item);
  const dialog=document.querySelector('#history-dialog'),body=document.querySelector('#history-content');let row,kind='callbacks',page=1,generation=0;
  const load=async()=>{
    const token=++generation;
    body.replaceChildren();document.querySelector('#history-error').textContent='';
    try{const query=new URLSearchParams({kind,page,...(row.assignment_id?{assignment_id:row.assignment_id}:{})});const data=await request(`/api/customers/${row.id}/history?`+query);if(token!==generation)return;
      body.replaceChildren(...data.data.map(item=>{const section=text('section','');section.className='history-entry';
        if(kind==='callbacks'){section.append(text('h3',`${date(item.due_at)} · ${{PENDING:'미완료',COMPLETED:'완료',CANCELLED:'취소'}[item.status]}`),text('p',`등록 ${item.created_by} · ${date(item.created_at)} / 수정 ${item.updated_by} · ${date(item.updated_at)}`));if(item.completed_at)section.append(text('p',`완료 ${item.completed_by} · ${date(item.completed_at)}`));if(item.cancelled_at)section.append(text('p',`취소 ${item.updated_by} · ${date(item.cancelled_at)}`));}
        else{
          section.append(text('h3',`버전 ${item.customer_version} · ${item.actor||'기준 기록'} · ${date(item.saved_at)} · ${sources[item.source]||'저장 이력'}`));
          const table=document.createElement('table');table.className='table history-comparison';const head=document.createElement('thead'),tr=document.createElement('tr');tr.append(text('th','항목'),text('th','변경 전'),text('th','변경 후'));head.append(tr);table.append(head);const body=document.createElement('tbody');
          for(const field of item.changed_fields.length?item.changed_fields:Object.keys(item.after_values)){const row=document.createElement('tr');row.append(text('th',labels[field]||'기타 항목'),text('td',value(field,item.before_values[field])),text('td',value(field,item.after_values[field])));body.append(row);}table.append(body);section.append(table);
        }
        return section;}));if(!data.total)body.append(text('p','저장된 이력이 없습니다.'));
      document.querySelector('#history-page').textContent=`전체 ${data.total}건 · ${page}페이지`;document.querySelector('#history-previous').disabled=page<=1;document.querySelector('#history-next').disabled=!data.has_next;
    }catch(error){if(token===generation){body.replaceChildren();document.querySelector('#history-error').textContent=error.message;}}
  };
  document.querySelector('#history-kind').onchange=event=>{kind=event.target.value;page=1;load();};document.querySelector('#history-previous').onclick=()=>{page--;load();};document.querySelector('#history-next').onclick=()=>{page++;load();};
  return async value=>{row=value;kind='callbacks';page=1;document.querySelector('#history-kind').value=kind;document.querySelector('#history-title').textContent=`${row.customer_name} · 서버 저장 이력`;dialog.showModal();await load();};
}
