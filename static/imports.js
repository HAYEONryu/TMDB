import {api,option} from "./api.js";
const $=selector=>document.querySelector(selector), message=text=>{$("#upload-message").textContent=text;};
const statusLabels={VALIDATED:"검증 완료 · 확정 전",COMMITTED:"등록 확정 완료",EXPIRED:"검증 결과 만료",FAILED:"등록 실패 · 재업로드 필요"};
let batchId=new URL(location.href).searchParams.get("batch_id"), result, page=1, busy=false, key;
const userId=$("#imports").dataset.userId;
function buttons(){
  $("#upload-site").disabled=busy||!!batchId;$("#upload-file").disabled=busy||!!batchId;
  $("#validate-file").disabled=busy||!!batchId||!$("#upload-site").value;
  $("#commit-upload").disabled=busy||!result?.can_commit;
  for(const id of ["refresh-result","new-upload","result-kind","commit-confirm","commit-cancel"])$("#"+id).disabled=busy;
  $("#result-previous").disabled=busy||page<=1;$("#result-next").disabled=busy||page>=(result?.last_page||1);
}
function url(){const value=new URL(location.href);if(batchId)value.searchParams.set("batch_id",batchId);else value.searchParams.delete("batch_id");history.replaceState(null,"",value);}
function requestKey(){
  const name=`tm:import:${userId}:${batchId}`;
  if(!key){try{key=sessionStorage.getItem(name);}catch{}}
  if(!key){key=crypto.randomUUID();try{sessionStorage.setItem(name,key);}catch{}}
  return key;
}
function render(){
  $("#import-result").hidden=false;$("#batch-site").textContent=`현장: ${result.site_name}`;
  $("#batch-status").textContent=statusLabels[result.status]||result.status;
  const c=result.validation_summary;
  $("#validation-counts").textContent=`검증 시 총 ${c.total??result.total_count}건 · 등록 가능 ${c.ready??0} · 파일 내 중복 ${c.duplicate_in_file??0} · 기존 중복 ${c.duplicate_existing??0} · 형식 오류 ${c.invalid??0}`;
  $("#commit-summary").textContent=result.status==="COMMITTED"?`엑셀 ${result.total_count.toLocaleString()}개 데이터 중 ${result.success_count.toLocaleString()}개 업로드를 성공했습니다. ${result.failure_count.toLocaleString()}개는 업로드를 실패했습니다. 실패 목록을 확인해 주세요.`:result.status==="FAILED"?"등록 중 오류가 발생해 전체 등록을 취소했습니다. 파일을 다시 업로드해 주세요.":"검증만으로는 고객이 등록되지 않습니다.";
  $("#result-retention").textContent=result.results_expired?"행별 결과 보관 기간이 끝났습니다. 집계만 확인할 수 있습니다.":`행별 결과 보관: ${new Date(result.expires_at).toLocaleString("ko-KR",{timeZone:"Asia/Seoul"})}까지 (한국 시각)`;
  const rows=result.rows.map(row=>{const tr=document.createElement("tr");for(const value of [row.row_number,row.customer_name,row.phone_input,row.success?result.status==="COMMITTED"?"등록 성공":"등록 가능":"실패",row.error_code,row.reason]){const td=document.createElement("td");td.textContent=String(value??"");tr.append(td);}return tr;});
  if(!rows.length){const tr=document.createElement("tr"),td=document.createElement("td");td.colSpan=6;td.textContent=result.results_expired?"행 원문이 정리되었습니다.":"표시할 행이 없습니다.";tr.append(td);rows.push(tr);}
  $("#import-rows").replaceChildren(...rows);
  $("#result-page").textContent=`${result.total_rows}행 · ${result.page} / ${result.last_page}페이지 (최대 100행)`;
  $("#commit-upload").hidden=result.status!=="VALIDATED";
  buttons();
}
async function loadResult(){
  result=await api(`/api/imports/${batchId}?page=${page}&kind=${$("#result-kind").value}`);
  $("#upload-site").value=result.site_id;render();url();
}
async function run(action){if(busy)return;busy=true;buttons();message("");try{await action();}catch(error){message(error.message);}finally{busy=false;buttons();}}
$("#upload-form").onsubmit=event=>{event.preventDefault();run(async()=>{
  const file=$("#upload-file").files[0];if(!file)return;
  if(!file.name.toLowerCase().endsWith(".xlsx"))throw new Error(".xlsx 파일만 선택해 주세요.");
  if(file.size>10485760)throw new Error("파일은 10MB까지 업로드할 수 있습니다.");
  const body=new FormData();body.append("site_id",$("#upload-site").value);body.append("file",file);
  const data=await api("/api/imports/validate",body);batchId=data.id;page=1;key=undefined;url();await loadResult();$("#upload-file").value="";
});};
$("#upload-site").onchange=buttons;
$("#refresh-result").onclick=()=>run(loadResult);
$("#result-kind").onchange=()=>run(async()=>{page=1;await loadResult();});
$("#result-previous").onclick=()=>run(async()=>{page--;await loadResult();});
$("#result-next").onclick=()=>run(async()=>{page++;await loadResult();});
$("#new-upload").onclick=()=>{batchId=null;result=null;key=undefined;$("#import-result").hidden=true;$("#upload-file").value="";page=1;url();buttons();message("다른 파일을 선택해 검증해 주세요.");};
$("#commit-upload").onclick=()=>{$("#confirm-counts").textContent=`검증 시 등록 가능 ${result.validation_summary.ready}건을 확정하시겠습니까?`;$("#commit-dialog").showModal();};
$("#commit-cancel").onclick=()=>$("#commit-dialog").close();
$("#commit-confirm").onclick=()=>run(async()=>{
  try{const data=await api(`/api/imports/${batchId}/commit`,{site_id:result.site_id,idempotency_key:requestKey()});$("#commit-dialog").close();await loadResult();message(data.message);}
  catch(error){$("#commit-dialog").close();
    if(error.data?.status==="FAILED"||error.code==="IMPORT_EXPIRED"){result={...result,status:error.code==="IMPORT_EXPIRED"?"EXPIRED":"FAILED",can_commit:false,rows:[],total_rows:0,last_page:1};render();}
    if(["SITE_DELETED","IMPORT_NOT_FOUND","UNAUTHENTICATED","FORBIDDEN"].includes(error.code))result.can_commit=false;
    try{await loadResult();}catch{}
    if(result?.status==="COMMITTED")message("서버에서 등록 완료를 확인했습니다. 결과를 확인해 주세요.");
    else message(error.message+(["FAILED","EXPIRED"].includes(result?.status)?"":" 같은 요청으로 다시 시도하거나 결과를 새로고침해 주세요."));
  }
});
document.addEventListener("click",event=>{if(busy&&event.target.closest("a[href]")){event.preventDefault();message("요청 처리 중입니다. 결과를 확인한 뒤 이동해 주세요.");}},true);
window.addEventListener("beforeunload",event=>{if(busy){event.preventDefault();event.returnValue="";}});
busy=true;buttons();
try{const sites=await api("/api/sites");$("#upload-site").replaceChildren(...sites.items.map(site=>option(site.id,site.name)));if(sites.default_site_id)$("#upload-site").value=sites.default_site_id;if(!sites.items.length)message("등록된 현장이 없습니다. DB 관리에서 먼저 현장을 생성해 주세요.");if(batchId)await loadResult();}
catch(error){message(error.message);if(error.status===404){batchId=null;key=undefined;url();}}finally{busy=false;buttons();}
