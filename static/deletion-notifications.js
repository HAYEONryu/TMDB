import {confirmAction} from './shared-ui.js';
import {newRequestId} from './request-id.js';
import {api} from './api.js';
import {PendingOperation} from './pending-operation.js';
const $=selector=>document.querySelector(selector),root=$('#deletion-notifications'),userId=document.body.dataset.userId;
const request=(url,body)=>api(url,body,'POST',{'X-TM-Actor':userId});
const pending=new PendingOperation('deletion-approve',userId,/^\/api\/deletion-requests\/[0-9a-f-]+\/approve$/,request);
const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el;};
let busy=false,loading=false,stopped=false,queuedRefresh=false,timer,page=1,hasNext=false;
function status(){
  $('#approval-pending').hidden=!pending.value;$('#approval-retry').disabled=busy||stopped;$('#approval-discard').disabled=busy;
  root.querySelectorAll('.approve-request').forEach(button=>button.disabled=busy||!!pending.value||stopped);
  $('#requests-previous').disabled=loading||page<=1;$('#requests-next').disabled=loading||!hasNext;
}
function schedule(){clearTimeout(timer);if(!stopped&&!busy&&document.visibilityState==='visible')timer=setTimeout(()=>load(1),60000);}
async function load(number=1){
  if(stopped||document.visibilityState!=='visible')return;if(loading){queuedRefresh=true;return;}loading=true;root.setAttribute('aria-busy','true');clearTimeout(timer);status();
  try{
    const data=await request('/api/deletion-requests?'+new URLSearchParams({page:number}));if(stopped)return;
    page=data.page;hasNext=data.has_next;root.dataset.empty=String(data.total===0);$('#delete-request-count').textContent=`고객정보 삭제 요청 ${data.total}건`;
    $('#delete-request-rows').replaceChildren(...data.items.map(item=>{const row=document.createElement('tr');
      for(const value of [item.site_name,item.customer_name,item.phone.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'),item.requested_by,new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'short',hourCycle:'h23'}).format(new Date(item.requested_at))])row.append(text('td',value));
      const cell=document.createElement('td'),button=text('button','승인');button.className='approve-request btn btn-sm btn-outline-danger';button.onclick=()=>approve(item);cell.append(button);row.append(cell);return row;}));
    $('#delete-request-page').textContent=`전체 현장 · ${page}페이지`;$('#notification-message').textContent='';
  }catch(error){root.dataset.empty='false';$('#notification-message').textContent=error.message;if([401,403].includes(error.status)){stopped=true;$('#delete-request-rows').replaceChildren();$('#delete-request-count').textContent='삭제 요청 알림 확인 불가';}}
  finally{loading=false;root.setAttribute('aria-busy','false');status();const again=queuedRefresh&&!stopped&&document.visibilityState==='visible';queuedRefresh=false;if(again)load(1);else schedule();}
}
async function approve(item){
  if(busy||stopped||item&&pending.value)return;
  if(item&&!await confirmAction(`${item.site_name} · ${item.customer_name} 고객의 삭제 요청을 승인합니다. 현재 배정은 종료되고 고객정보와 상담·재콜 이력은 휴지통에 보관됩니다.`,{title:'삭제 요청 승인',confirmText:'승인하고 휴지통으로 이동',danger:true}))return;
  busy=true;clearTimeout(timer);status();
  try{await pending.execute(item?{endpoint:`/api/deletion-requests/${item.id}/approve`,body:{idempotency_key:newRequestId()}}:undefined);await load(1);$('#notification-message').textContent='삭제 요청 승인을 확인했습니다.';}
  catch(error){await load(1);$('#notification-message').textContent=error.message;}
  finally{busy=false;status();schedule();}
}
$('#approval-retry').onclick=()=>approve();$('#approval-discard').onclick=async()=>{if(await confirmAction('삭제 승인 확인 알림을 닫습니다. 이미 휴지통으로 이동한 고객은 그대로 유지됩니다.',{title:'확인 알림 닫기',confirmText:'알림 닫기'})){pending.clear();status();load(1);}};
$('#requests-refresh').onclick=()=>load(1);$('#requests-previous').onclick=()=>load(page-1);$('#requests-next').onclick=()=>load(page+1);
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load(1);else clearTimeout(timer);});window.addEventListener('focus',()=>load(1));
window.addEventListener('tm-auth-context',event=>{if(event.detail.user!==userId||event.detail.role!=='ADMIN'||event.detail.initial){stopped=true;clearTimeout(timer);$('#delete-request-rows').replaceChildren();$('#notification-message').textContent='로그인 정보가 변경되었습니다. 다시 로그인해 주세요.';status();}});
status();load(1);
