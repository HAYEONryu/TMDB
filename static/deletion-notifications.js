import {confirmAction} from './shared-ui.js';
import {announceAdminUpdate} from './admin-updates.js';
import {newRequestId} from './request-id.js';
import {api} from './api.js';
import {PendingOperation} from './pending-operation.js';
const $=selector=>document.querySelector(selector),root=$('#deletion-notifications'),userId=document.body.dataset.userId;
const request=(url,body)=>api(url,body,'POST',{'X-TM-Actor':userId});
const pending=new PendingOperation('deletion-approve',userId,/^\/api\/deletion-requests\/(?:[0-9a-f-]+\/approve|bulk-approve)$/,request);
const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;};
let busy=false,loading=false,stopped=false,queuedRefresh=false,timer,page=1,hasNext=false,items=[],selected=new Set();
function status(){
  $('#approval-pending').hidden=!pending.value;$('#approval-retry').disabled=busy||stopped;$('#approval-discard').disabled=busy;
  const blocked=busy||!!pending.value||stopped;
  root.querySelectorAll('.approve-request,.request-selection').forEach(control=>control.disabled=blocked||loading);
  $('#approve-selected').disabled=blocked||loading||!selected.size;
  $('#delete-request-select-all').disabled=blocked||loading||!items.length;
  $('#delete-request-select-all').checked=!!items.length&&selected.size===items.length;
  $('#delete-request-select-all').indeterminate=selected.size>0&&selected.size<items.length;
  $('#delete-request-page').textContent='전체 현장 · '+page+'페이지 · 현재 페이지 선택 '+selected.size+'건';
  $('#requests-previous').disabled=loading||busy||page<=1;$('#requests-next').disabled=loading||busy||!hasNext;
}
function schedule(){clearTimeout(timer);if(!stopped&&!busy&&document.visibilityState==='visible')timer=setTimeout(()=>load(page),60000);}
async function load(number=1){
  if(stopped||document.visibilityState!=='visible')return;if(loading){queuedRefresh=true;return;}loading=true;root.setAttribute('aria-busy','true');clearTimeout(timer);status();
  try{
    const data=await request('/api/deletion-requests?'+new URLSearchParams({page:number}));if(stopped)return;
    if(data.page!==page)selected.clear();page=data.page;hasNext=data.has_next;items=data.items;
    selected=new Set([...selected].filter(id=>items.some(item=>item.id===id)));
    root.dataset.empty=String(data.total===0);$('#delete-request-count').textContent='고객정보 삭제 요청 '+data.total+'건';
    $('#delete-request-rows').replaceChildren(...items.map(item=>{
      const row=document.createElement('tr');row.dataset.requestId=item.id;
      const selection=document.createElement('td'),check=document.createElement('input');selection.className='request-select-column';check.type='checkbox';check.className='request-selection';check.checked=selected.has(item.id);
      check.setAttribute('aria-label',item.site_name+' · '+(item.customer_name||'이름 미입력')+' 삭제 요청 선택');
      check.onchange=()=>{if(check.checked)selected.add(item.id);else selected.delete(item.id);status();};selection.append(check);row.append(selection);
      for(const value of [item.site_name,item.customer_name,item.phone.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'),item.requested_by,new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'short',hourCycle:'h23'}).format(new Date(item.requested_at))])row.append(text('td',value));
      const cell=document.createElement('td'),button=text('button','승인');button.className='approve-request btn btn-sm btn-outline-danger';button.onclick=()=>approve(item);cell.append(button);row.append(cell);return row;
    }));
    $('#delete-request-page').textContent='전체 현장 · '+page+'페이지';$('#notification-message').textContent='';
  }catch(error){
    root.dataset.empty='false';$('#notification-message').textContent=error.message;
    if([401,403].includes(error.status)){stopped=true;selected.clear();items=[];$('#delete-request-rows').replaceChildren();$('#bulk-approval-results').replaceChildren();$('#delete-request-count').textContent='삭제 요청 알림 확인 불가';}
  }finally{
    loading=false;root.setAttribute('aria-busy','false');status();
    const again=queuedRefresh&&!stopped&&document.visibilityState==='visible';queuedRefresh=false;if(again)load(page);else schedule();
  }
}
function showBulk(result){
  const title=text('p','승인 '+result.approved_count+'건 · 제외 '+result.excluded_count+'건'+(result.failed_count?' · 실패 '+result.failed_count+'건 (같은 요청으로 재시도 가능)':''));
  const list=document.createElement('ul');
  for(const item of result.items){
    const label=({approved:'승인',excluded:'제외',failed:'실패',pending:'대기'})[item.status];
    const row=text('li',item.site_name+' · '+(item.customer_name||'이름 미입력')+' · '+label+(item.message?' · '+item.message:'')+(item.phone?' · '+item.phone.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'):''));
    row.dataset.requestId=item.request_id;row.dataset.result=item.status;list.append(row);
  }
  $('#bulk-approval-results').replaceChildren(title,list);
}
async function submit(value){
  if(busy||stopped)return;busy=true;clearTimeout(timer);status();
  const original=value||pending.value;
  try{
    const result=await pending.execute(value);
    if(result.items){showBulk(result);if(result.failed_count)pending.set(original);}
    selected.clear();await load(1);announceAdminUpdate();
    $('#notification-message').textContent=result.items?'승인 '+result.approved_count+'건 · 제외 '+result.excluded_count+'건'+(result.failed_count?' · 실패 '+result.failed_count+'건':''):'삭제 요청 승인을 확인했습니다.';
  }catch(error){await load(page);$('#notification-message').textContent=error.message;}
  finally{busy=false;status();schedule();}
}
async function approve(item){
  if(busy||stopped||pending.value)return;
  if(!await confirmAction(item.site_name+' · '+item.customer_name+' 고객의 삭제 요청을 승인합니다. 현재 배정은 종료되고 고객정보와 상담·재콜 이력은 휴지통에 보관됩니다.',{title:'삭제 요청 승인',confirmText:'승인하고 휴지통으로 이동',danger:true}))return;
  await submit({endpoint:'/api/deletion-requests/'+item.id+'/approve',body:{idempotency_key:newRequestId()}});
}
$('#delete-request-select-all').onchange=event=>{
  selected=event.target.checked?new Set(items.map(item=>item.id)):new Set();
  root.querySelectorAll('.request-selection').forEach((check,index)=>check.checked=selected.has(items[index].id));status();
};
$('#approve-selected').onclick=async()=>{
  if(busy||pending.value||stopped||!selected.size)return;
  const ids=[...selected],groups=new Map();
  for(const item of items.filter(item=>selected.has(item.id)))groups.set(item.site_name,(groups.get(item.site_name)||0)+1);
  const context=['선택한 삭제 요청 '+ids.length+'건을 일괄 승인합니다.',...[...groups].map(([name,count])=>name+': '+count+'건'),'이미 처리되거나 유효하지 않은 요청은 제외합니다. 승인한 고객은 배정이 종료되고 휴지통으로 이동하며 상담·재콜 이력은 보존합니다.'];
  if(await confirmAction(context.join('\n'),{title:'선택 요청 일괄 승인',confirmText:'선택 요청 일괄 승인',danger:true}))
    await submit({endpoint:'/api/deletion-requests/bulk-approve',body:{request_ids:ids,idempotency_key:newRequestId()}});
};
$('#approval-retry').onclick=()=>submit();
$('#approval-discard').onclick=async()=>{
  if(await confirmAction('삭제 승인 확인 알림을 닫습니다. 이미 처리된 승인과 휴지통 고객은 유지됩니다. 실패한 요청은 남아 있으므로 목록을 확인하세요.',{title:'확인 알림 닫기',confirmText:'알림 닫기'})){
    pending.clear();status();load(page);
  }
};
$('#requests-refresh').onclick=()=>load(page);$('#requests-previous').onclick=()=>load(page-1);$('#requests-next').onclick=()=>load(page+1);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load(page);else clearTimeout(timer);});window.addEventListener('focus',()=>load(page));
window.addEventListener('tm-auth-context',event=>{
  if(event.detail.user!==userId||event.detail.role!=='ADMIN'||event.detail.initial){
    stopped=true;clearTimeout(timer);selected.clear();items=[];$('#delete-request-rows').replaceChildren();$('#bulk-approval-results').replaceChildren();$('#notification-message').textContent='로그인 정보가 변경되었습니다. 다시 로그인해 주세요.';status();
  }
});
status();load(1);
