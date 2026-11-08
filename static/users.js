import {api} from "./api.js";
import {PendingOperation} from "./pending-operation.js";
const $=selector=>document.querySelector(selector),userId=$("#user-management").dataset.userId,notice=message=>{$("#user-message").textContent=message;};
const reset=new PendingOperation("user-reset",userId,/^\/api\/users\/[0-9a-f-]+\/reset-password$/);
let busy=true,leaving=false,page=1,lastPage=1,q="",transferPage=1,transferLast=1,records=new Map(),drafts=new Map(),saveBody=null,createBody=null,createUnknown=false,resetTarget;
function status(){
  const locked=busy||!!saveBody||!!reset.value;
  document.querySelectorAll("#user-rows input").forEach(input=>input.disabled=locked||input.dataset.bootstrapProtected==="true");
  document.querySelectorAll("#user-rows button").forEach(button=>button.disabled=locked);
  for(const id of ["add-user","reload-users","user-search","user-search-form button","transfer-previous","transfer-next"]){const button=$("#"+id);if(button)button.disabled=busy||!!reset.value;}
  $("#save-users").disabled=busy||!!reset.value||(!drafts.size&&!saveBody);
  $("#user-previous").disabled=busy||!!reset.value||page<=1;$("#user-next").disabled=busy||!!reset.value||page>=lastPage;
  $("#transfer-previous").disabled ||= transferPage<=1;$("#transfer-next").disabled ||= transferPage>=transferLast;
  $("#user-dirty").textContent=saveBody?"저장 응답 미확인 · 같은 요청으로 다시 확인하세요.":drafts.size?`미저장 ${drafts.size}명`:"변경사항 없음";
  $("#reset-pending").hidden=!reset.value;
  for(const id of ["reset-retry","reset-discard","user-save-confirm","user-save-cancel","reset-confirm","reset-cancel"])$("#"+id).disabled=busy;
  for(const id of ["new-user-name","new-user-phone","new-user-admin"])$("#"+id).disabled=busy||createUnknown;
  $("#add-user-submit").disabled=busy;$("#add-user-cancel").disabled=busy;
}
function current(){return [...records.values()].map(person=>({...person,...drafts.get(person.id)}));}
function render(){
  $("#user-rows").replaceChildren(...current().map(person=>{
    const tr=document.createElement("tr");tr.dataset.id=person.id;
    for(const [field,label,type,value] of [["name","이름","text",person.name],["phone","전화번호","tel",person.phone],["is_active","비활성화","checkbox",!person.is_active],["role","관리자","checkbox",person.role==="ADMIN"]]){
      const td=document.createElement("td"),input=document.createElement("input");input.type=type;input.setAttribute("aria-label",label);input.dataset.field=field;
      if(person.phone==="admin"&&["phone","role"].includes(field)){input.dataset.bootstrapProtected="true";if(field==="phone"){input.type="text";input.setAttribute("aria-label","최초 관리자 아이디");}}
      if(type==="checkbox"){input.className="form-check-input";input.checked=value;}else{input.className="form-control";input.value=value;input.maxLength=field==="name"?100:20;}
      input.oninput=()=>{const changed={...person,...drafts.get(person.id)};changed[field]=type==="checkbox"?field==="role"?(input.checked?"ADMIN":"EMPLOYEE"):!input.checked:input.value;const base=records.get(person.id);if(["name","phone","is_active","role"].some(key=>changed[key]!==base[key]))drafts.set(person.id,changed);else drafts.delete(person.id);status();};td.append(input);tr.append(td);
    }
    for(const value of [person.must_change_password?"첫 변경 필요":"사용 가능",`${person.transfer_needed_count}건`]){const td=document.createElement("td");td.textContent=value;tr.append(td);}
    const td=document.createElement("td"),button=document.createElement("button");button.className="btn btn-sm btn-outline-secondary";button.textContent="비밀번호 재설정";button.onclick=()=>guarded(()=>{resetTarget=person.id;$("#reset-name").textContent=`${person.name}님의 비밀번호를 재설정하시겠습니까?`;$("#reset-dialog").showModal();});td.append(button);tr.append(td);return tr;
  }));status();
}
async function transfers(target=transferPage){
  const data=await api("/api/users/transfer-needed?"+new URLSearchParams({page:target}));transferPage=target;transferLast=data.last_page;
  $("#transfer-rows").replaceChildren(...data.items.map(person=>{const tr=document.createElement("tr");for(const value of [person.site_name,person.customer_name,person.phone.replace(/^(010)(\d{4})(\d{4})$/,"$1-$2-$3"),person.employee_name]){const td=document.createElement("td");td.textContent=value;tr.append(td);}const td=document.createElement("td"),link=document.createElement("a");link.textContent="DB 관리에서 이관";link.href="/app/admin/customers?"+new URLSearchParams({site_id:person.site_id,assignee_id:person.employee_id});td.append(link);tr.append(td);return tr;}));
  $("#transfer-page").textContent=`이관 필요 ${data.total}건 · ${transferPage} / ${transferLast}페이지`;status();
}
async function load(target=page,search=q){
  const data=await api("/api/users?"+new URLSearchParams({page:target,q:search}));page=target;lastPage=data.last_page;q=search;
  records=new Map(data.items.map(person=>[person.id,person]));render();$("#user-page").textContent=`사용자 ${data.total}명 · ${page} / ${lastPage}페이지`;await transfers();
}
async function run(action){if(busy)return;busy=true;status();notice("");try{await action();}catch(error){notice(error.message);}finally{busy=false;status();}}
async function guarded(action){
  if(busy)return;
  if(drafts.size||saveBody){const discard=await new Promise(resolve=>{const dialog=$("#user-dirty-dialog");let done=false;const finish=value=>{if(done)return;done=true;dialog.close();resolve(value);};$("#user-stay").onclick=()=>finish(false);$("#user-discard").onclick=()=>finish(true);dialog.oncancel=event=>{event.preventDefault();finish(false);};dialog.showModal();});if(!discard)return;drafts.clear();saveBody=null;render();}
  await action();
}
$("#save-users").onclick=()=>{$("#user-save-count").textContent=`${drafts.size}명의 변경을 한 번에 저장합니다. 오류가 있으면 전부 저장하지 않습니다.`;$("#user-save-dialog").showModal();};
$("#user-save-cancel").onclick=()=>$("#user-save-dialog").close();
$("#user-save-confirm").onclick=()=>run(async()=>{
  saveBody ||= {idempotency_key:crypto.randomUUID(),rows:[...drafts.values()].map(person=>({id:person.id,name:person.name,phone:person.phone,role:person.role,is_active:person.is_active,expected_version:records.get(person.id).version}))};
  try{const result=await api("/api/users/batch-update",saveBody);drafts.clear();saveBody=null;$("#user-save-dialog").close();if(result.requires_relogin){leaving=true;location.href="/auth/login";return;}await load();notice(`${result.updated_count}명 저장 · 미진행 ${result.recalled_count}건 회수했습니다.`);}
  catch(error){if(error.status>=400&&error.status<500)saveBody=null;$("#user-save-dialog").close();notice(error.message);}
});
$("#reload-users").onclick=()=>guarded(()=>run(()=>load()));
$("#user-search-form").onsubmit=event=>{event.preventDefault();const value=$("#user-search").value;guarded(()=>run(()=>load(1,value)));};
$("#user-previous").onclick=()=>guarded(()=>run(()=>load(page-1)));
$("#user-next").onclick=()=>guarded(()=>run(()=>load(page+1)));
$("#transfer-previous").onclick=()=>run(()=>transfers(transferPage-1));$("#transfer-next").onclick=()=>run(()=>transfers(transferPage+1));
$("#add-user").onclick=()=>guarded(()=>{if(!createUnknown){createBody=null;$("#add-user-form").reset();}$("#add-user-error").textContent="";$("#add-user-dialog").showModal();status();});
$("#add-user-cancel").onclick=()=>$("#add-user-dialog").close();
$("#add-user-form").onsubmit=event=>{event.preventDefault();run(async()=>{
  createBody ||= {name:$("#new-user-name").value,phone:$("#new-user-phone").value,role:$("#new-user-admin").checked?"ADMIN":"EMPLOYEE",idempotency_key:crypto.randomUUID()};
  try{await api("/api/users",createBody);createBody=null;createUnknown=false;$("#add-user-dialog").close();await load(1,"");notice("사용자를 추가했습니다. 첫 로그인에서 비밀번호 변경이 필요합니다.");}
  catch(error){createUnknown=!error.status||error.status>=500;if(!createUnknown)createBody=null;$("#add-user-error").textContent=error.message+(createUnknown?" 입력값을 유지하고 같은 요청으로 다시 확인해 주세요.":"");}
});};
async function doReset(value){
  try{const result=await reset.execute(value);$("#reset-dialog").close();if(result.id===userId){leaving=true;location.href="/auth/login";return;}await load();notice("초기 비밀번호로 재설정했습니다. 기존 세션을 종료하고 첫 변경을 요구합니다.");}
  catch(error){$("#reset-dialog").close();notice(error.message);}
}
$("#reset-cancel").onclick=()=>$("#reset-dialog").close();$("#reset-confirm").onclick=()=>run(()=>doReset({endpoint:`/api/users/${resetTarget}/reset-password`,body:{idempotency_key:crypto.randomUUID()}}));
$("#reset-retry").onclick=()=>run(()=>doReset());$("#reset-discard").onclick=()=>run(async()=>{reset.clear();await load();notice("대기 정보를 폐기했습니다. 현재 계정 상태를 확인해 주세요.");});
document.addEventListener("click",event=>{const link=event.target.closest("a[href]");if(!link)return;if(busy){event.preventDefault();return;}if(drafts.size||saveBody){event.preventDefault();guarded(()=>{location.href=link.href;});}},true);
document.querySelector('form[action="/auth/logout"]')?.addEventListener("submit",event=>{if(busy||drafts.size||saveBody){event.preventDefault();event.stopImmediatePropagation();guarded(()=>event.target.submit());}},true);
window.addEventListener("beforeunload",event=>{if(!leaving&&(busy||drafts.size||saveBody||createUnknown)){event.preventDefault();event.returnValue="";}});
status();try{await load();}catch(error){notice(error.message);}finally{busy=false;status();}
