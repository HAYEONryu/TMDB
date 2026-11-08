import {newRequestId} from './request-id.js';
import {api,option} from "./api.js";
import {PendingOperation} from "./pending-operation.js";
const $=selector=>document.querySelector(selector),notice=message=>{$("#assignment-message").textContent=message;};
const operation=new PendingOperation("allocation",$("#assignment-management").dataset.userId,/^\/api\/assignments\/(distribute|recall)$/);
let busy=true,checked=false,recallBody;
function status(){
  const pending=!!operation.value;
  $("#assignment-pending").hidden=!pending;
  $("#assignment-site").disabled=busy||pending;$("#check-availability").disabled=busy||pending||!$("#assignment-site").value;
  for(const id of ["assignment-employee","assignment-quantity","distribute","recall"])$("#"+id).disabled=busy||pending||!checked;
  for(const id of ["distribute","recall"])$("#"+id).disabled ||= !$("#assignment-employee").value;
  for(const id of ["assignment-retry","assignment-discard","recall-confirm","recall-cancel"])$("#"+id).disabled=busy;
}
async function availability(){
  const selected=$("#assignment-employee").value;
  const data=await api("/api/assignments/availability?"+new URLSearchParams({site_id:$("#assignment-site").value}));
  $("#availability-count").textContent=`분배 가능 ${data.available_count}건 · 활성 직원 ${data.employees.length}명`;
  $("#assignment-employee").replaceChildren(option("all","전체 팀원"),...data.employees.map(person=>option(person.id,`${person.name} · ${person.phone.replace(/^(010)(\d{4})(\d{4})$/,"$1-$2-$3")}`)));
  if(selected&&selected!=="all"&&!data.employees.some(person=>person.id===selected)){
    $("#assignment-employee").prepend(option("","직원을 다시 선택해 주세요."));$("#assignment-employee").value="";
  }else $("#assignment-employee").value=selected||"all";
  checked=true;
}
async function run(action){if(busy)return;busy=true;status();notice("");try{await action();}catch(error){notice(error.message);}finally{busy=false;status();}}
function body(){return {site_id:$("#assignment-site").value,employee_id:$("#assignment-employee").value};}
async function execute(value){
  try{
    const result=await operation.execute(value);
    $("#assignment-result").replaceChildren();
    const summary=document.createElement("p");summary.textContent=result.allocated_count!==undefined?`총 ${result.allocated_count}건 분배했습니다.`:`${result.business_date} 할당 ${result.recalled_count}건을 회수했습니다.`;$("#assignment-result").append(summary);
    for(const person of result.employees||[]){const p=document.createElement("p");p.className="small mb-1";p.textContent=`${person.name}: ${person.count}건`;$("#assignment-result").append(p);}
    try{await availability();}catch(error){notice("처리는 완료되었습니다. 잔여 수 조회: "+error.message);checked=false;}
  }catch(error){notice(error.message);if(!operation.value){try{await availability();}catch{checked=false;}}}
}
$("#assignment-site").onchange=()=>{checked=false;$("#assignment-employee").replaceChildren();$("#assignment-quantity").value="";$("#availability-count").textContent="현장을 확인해 주세요.";$("#assignment-result").replaceChildren();status();};
$("#check-availability").onclick=()=>run(availability);
$("#assignment-employee").onchange=status;
$("#distribute").onclick=()=>run(async()=>{const quantity=Number($("#assignment-quantity").value);if(!Number.isSafeInteger(quantity)||quantity<=0)throw new Error("직원당 수량은 양의 정수로 입력해 주세요.");await execute({endpoint:"/api/assignments/distribute",body:{...body(),quantity,idempotency_key:newRequestId()}});});
$("#recall").onclick=()=>run(async()=>{recallBody=body();const preview=await api("/api/assignments/recall-preview",recallBody);$("#recall-preview").textContent=`${preview.business_date} · ${preview.employee_count}명 · 현재 대상 ${preview.target_count}건을 회수하시겠습니까?`;$("#recall-dialog").showModal();});
$("#recall-cancel").onclick=()=>$("#recall-dialog").close();
$("#recall-confirm").onclick=()=>run(async()=>{$("#recall-dialog").close();await execute({endpoint:"/api/assignments/recall",body:{...recallBody,idempotency_key:newRequestId()}});});
$("#assignment-retry").onclick=()=>run(()=>execute());
$("#assignment-discard").onclick=()=>run(async()=>{operation.clear();checked=false;notice("대기 정보를 폐기했습니다. 현재 잔여 수를 확인한 뒤 작업해 주세요.");});
window.addEventListener("beforeunload",event=>{if(busy||operation.value){event.preventDefault();event.returnValue="";}});
status();
try{const data=await api("/api/sites");$("#assignment-site").replaceChildren(...data.items.map(site=>option(site.id,site.name)));$("#assignment-site").value=operation.value?.body.site_id||data.default_site_id||"";if(!data.items.length)notice("등록된 현장이 없습니다. DB 관리에서 현장을 생성해 주세요.");}
catch(error){notice(error.message);}finally{busy=false;status();}
