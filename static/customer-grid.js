import {newRequestId} from './request-id.js';
import {api, option} from "./api.js";
import {PendingOperation} from "./pending-operation.js";
import {CallbackAction} from './callback-action.js';
import {installHistory} from './customer-history.js';
import {HardDelete} from './hard-delete.js';
import {customerLabels as labels,customerFields,choiceLabel} from './customer-columns.js';
import {openGridFilter,renderFilterChips,columnFilterButton,markFilterHeaders} from './grid-filter.js';
import {setupDateInput,dateInputTimestamp} from './date-input.js';

const $ = selector => document.querySelector(selector);
const trash = $("#management").dataset.trash === "true";
const schema = JSON.parse($("#customer-schema").textContent);
const editableFields = ["customer_name", "phone_normalized", "call_result", "visit_at", "contract_status", "notes", "callback_due_at", "housing_status", "residence", "route", "memo", "admin_notes"];
const multiline = new Set(['notes','memo','admin_notes']);
const dates = new Set(["visit_at", "callback_due_at", "assigned_at"]);
const pending = new Map();
const assigneeOperation=new PendingOperation("assignee",$("#management").dataset.userId,/^\/api\/customers\/[0-9a-f-]+\/assignee$/);
let state = {site:"", page:1, size:50, q:"", sort:"-created_at", filters:{},assignee:new URL(location.href).searchParams.get("assignee_id")||""}, busy = false, lastPage = 1,assigneeRow;
let siteInfo, rows = new Map(), conflictId, bulkBody, loadedState,callbacks,hard,renameTarget,activeDateEditor;
const actorRequest=(url,body)=>api(url,body,'POST',{'X-TM-Actor':$('#management').dataset.userId});
const openHistory=installHistory(actorRequest);
const notice = message => { $("#message").textContent = message; };
const text = (tag, value) => { const el = document.createElement(tag); el.textContent = value; return el; };
const display = (field, value) => field === "phone_normalized" && value ? String(value).replace(/^(010)(\d{4})(\d{4})$/,"$1-$2-$3") : choiceLabel(schema,field,value);
const localDate = value => value ? new Intl.DateTimeFormat("sv-SE", {timeZone:"Asia/Seoul",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(new Date(value)).replace(" ", "T") : "";
const normalize = (field, value) => dates.has(field) ? (value ? new Date(value.includes("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value+":00+09:00").toISOString() : null) : field === "call_result" ? value || null : field === "contract_status" ? value || "UNKNOWN" : ['housing_status','residence','route'].includes(field) ? (value || "").trim() : (value || "").replace(/\r\n?/g,"\n");
const params = () => new URLSearchParams({site_id:state.site, view:trash?"trash":"all", q:state.q, filters:JSON.stringify(state.filters),...(state.assignee?{assignee_id:state.assignee}:{})});
function status() {
  const blocked=busy||callbacks?.busy||!!callbacks?.pending.value||hard?.busy||!!hard?.pending.value||(!trash&&!!assigneeOperation.value);
  $("#dirty-count").textContent = pending.size ? `미저장 ${pending.size}행` : "변경사항 없음";
  if ($("#save")) $("#save").disabled = blocked || !pending.size;
  $("#bulk").disabled = blocked || !rows.size;
  $("#previous").disabled = blocked || state.page <= 1;
  $("#next").disabled = blocked || state.page >= lastPage;
  $("#site").disabled = blocked; $("#page-size").disabled = blocked; $("#sort").disabled = blocked;
  $("#filter-apply").disabled=busy;$("#filter-reset").disabled=busy;
  for(const selector of ["#create-site","#clear-filters","#search-form button"]){const button=$(selector);if(button)button.disabled=blocked;}
  if($('#rename-site'))$('#rename-site').disabled=blocked||!siteInfo?.items.some(site=>site.id===state.site);
  document.querySelectorAll(".assignee-action").forEach(button=>button.disabled=blocked);
  document.querySelectorAll('.callback-action').forEach(button=>{const row=table.getRow(button.dataset.customerId);button.disabled=blocked||!row||!row.getData().callback_id;});
  document.querySelectorAll('.hard-customer').forEach(button=>button.disabled=blocked);if($('#delete-site'))$('#delete-site').disabled=blocked||!state.site;
  if(!trash){$("#assignee-pending").hidden=!assigneeOperation.value;for(const id of ["assignee-retry","assignee-discard","assignee-confirm","assignee-cancel"])$("#"+id).disabled=busy;}
  const importsLink=$("#open-imports");if(importsLink){importsLink.classList.toggle("disabled",busy);importsLink.setAttribute("aria-disabled",String(busy));}
}
function rowStyle(row) {
  const item = pending.get(row.getData().id);
  row.getElement().classList.toggle("pending-row", !!item);
  row.getElement().classList.toggle("failed-row", !!item?.error);
}
function refreshRows() {
  table.getRows().forEach(row=>{const item=pending.get(row.getData().id);row.getCell("_status")?.setValue(item?`${item.mutation}:${item.error?.code||"pending"}`:"saved");row.reformat();});
}
function dateEditor(cell, onRendered, success, cancel) {
  const field=cell.getField(),original=cell.getValue(),allowTime=field==='visit_at';
  const input=setupDateInput(document.createElement('input'),{allowTime});
  input.value=allowTime?localDate(original).replace('T',' '):localDate(original).slice(0,10);input.setAttribute('aria-label',labels[field]);
  let done=false,touched=false;
  const finish=()=>{
    if(done)return true;
    try{
      const value=touched?dateInputTimestamp(input.value,{allowTime}):original;
      done=true;activeDateEditor=null;success(value);return true;
    }catch(error){input.setCustomValidity(error.message);input.reportValidity();notice(error.message);return false;}
  };
  onRendered(()=>{activeDateEditor={finish};input.focus();});
  input.addEventListener('input',()=>{touched=true;});
  input.addEventListener('blur',()=>{if(!finish())setTimeout(()=>input.focus(),0);});
  input.addEventListener('keydown',event=>{
    if(event.key.startsWith('Arrow')||event.key==='Tab')event.stopPropagation();
    if(event.key==='Enter'){event.preventDefault();finish();}
    if(event.key==='Escape'){event.preventDefault();done=true;activeDateEditor=null;cancel();}
  });
  return input;
}
function column(field) {
  const canEdit = editableFields.includes(field) && !trash;
  const definition = {title:labels[field], field, minWidth:field === "notes" ? 300 : dates.has(field) ? 185 : 145, width:field === "notes" ? 330 : field === "phone_normalized" ? 160 : undefined,
    headerSort:false, formatter:cell => text("span", dates.has(field) ? (field==='visit_at'?localDate(cell.getValue()).replace('T',' '):localDate(cell.getValue()).slice(0,10))||"-" : display(field, cell.getValue())),
    titleFormatter:() => { const wrap = text("span", labels[field]);wrap.append(columnFilterButton(field,labels[field],()=>guarded(()=>openFilter(field)).catch(showError)));return wrap; }};
  if(field==="assignee_name"&&!trash){definition.minWidth=245;definition.formatter=cell=>{const wrap=text("span",cell.getValue()||"-");const button=text("button","담당 변경");button.className="assignee-action btn btn-sm btn-outline-secondary ms-2";button.disabled=busy||!!assigneeOperation.value;button.onclick=()=>guarded(()=>openAssignee(cell.getRow().getData().id)).catch(showError);wrap.append(button);return wrap;};}
  if (canEdit) Object.assign(definition, {editable:cell => !busy && !callbacks?.busy && !callbacks?.pending.value && !assigneeOperation.value && !pending.get(cell.getRow().getData().id)?.uncertain,
    editor: dates.has(field) ? dateEditor : schema[field] ? "list" : multiline.has(field) ? "textarea" : "input",
    ...(schema[field] ? {editorParams:{values:schema[field],clearable:false,autocomplete:false}} : {}),
    ...(multiline.has(field) ? {variableHeight:true} : {})});
  return definition;
}
const table = new Tabulator("#customer-grid", {height:"min(60vh, 640px)", layout:"fitData", index:"id", data:[], placeholder:"표시할 고객정보가 없습니다.", selectableRows:true,
  rowFormatter:rowStyle, columns:[{formatter:"rowSelection",titleFormatter:"rowSelection",hozAlign:"center",headerSort:false,width:45,cellClick:(_event,cell)=>cell.getRow().toggleSelect()},
    ...customerFields({admin:true}).map(column),
    ...(trash ? [{title:"현장",field:"site_name",headerSort:false,minWidth:140,formatter:cell=>text("span",cell.getValue())}] : []),
    {title:'작업',field:'_actions',headerSort:false,minWidth:255,formatter:cell=>{const data=cell.getRow().getData(),wrap=document.createElement('span'),history=text('button','상담·재콜 이력');history.className='btn btn-sm btn-outline-secondary';history.onclick=()=>guarded(()=>openHistory(data)).catch(showError);wrap.append(history);if(!trash){const complete=text('button','재콜 완료');complete.className='callback-action btn btn-sm btn-outline-secondary ms-2';complete.dataset.customerId=data.id;complete.disabled=!data.callback_id||callbacks?.busy||!!callbacks?.pending.value;complete.onclick=()=>{if(callbacks?.pending.value||callbacks?.busy)return;guarded(()=>callbacks.run(data.id)).catch(showError);};wrap.append(complete);}return wrap;}},
    ...(!trash ? [{title:"저장상태",field:"_status",headerSort:false,minWidth:160,formatter:cell=>{
      const item = pending.get(cell.getRow().getData().id); const wrap = text("span", item ? item.uncertain?"결과 확인 필요 ":item.error?"저장 실패 ":"미저장" : "저장됨");
      if (item?.error) { const button = text("button", "확인"); button.className="btn btn-sm btn-outline-secondary"; button.addEventListener("click",()=>openConflict(cell.getRow().getData().id)); wrap.append(button); } return wrap;
    }}] : [])]});
const ready = new Promise(resolve => table.on("tableBuilt",resolve));
table.on("cellEdited", cell => {
  const data = cell.getRow().getData(), field=cell.getField(), base=rows.get(data.id);
  if (!editableFields.includes(field) || !base) return;
  let item = pending.get(data.id) || {base:structuredClone(base), changes:{}, mutation:newRequestId()};
  const value = cell.getValue();
  if (normalize(field,value) === normalize(field,item.base[field])) delete item.changes[field]; else item.changes[field]=value;
  item.mutation=newRequestId(); item.error=null;
  if (Object.keys(item.changes).length) pending.set(data.id,item); else pending.delete(data.id);
  refreshRows(); status();
});
function commitEditor() { if(activeDateEditor)return activeDateEditor.finish();const input = $("#customer-grid .tabulator-editing input, #customer-grid .tabulator-editing textarea"); if (input) input.blur();return true; }
function showError(error) { notice(error.message); }
async function loadSites(selected) {
  siteInfo = await api("/api/sites");
  $("#site").replaceChildren(...(trash ? [option("all","전체 현장")] : []), ...siteInfo.items.map(site=>option(site.id,site.name)));
  state.site = selected ?? siteInfo.default_site_id ?? (trash?"all":"");
  $("#site").value=state.site;
}
async function load() {
  busy=true; status(); notice("");
  try {
    const query=params(); query.set("page",state.page); query.set("page_size",state.size); query.set("sort",state.sort);
    const data=await api("/api/customers?"+query);
    if (data.last_page<state.page) { state.page=data.last_page; busy=false; return load(); }
    rows=new Map(data.data.map(row=>[row.id,structuredClone(row)])); lastPage=data.last_page;
    await table.setData(data.data.map(row=>({...row,...pending.get(row.id)?.changes})));
    $("#page-info").textContent=`검색 ${data.total.toLocaleString()}건 · ${state.page} / ${lastPage}페이지`;
    $("#counts").textContent=data.counts?`전체 DB ${data.counts.total} · 미할당 ${data.counts.unassigned} · 휴지통 ${data.counts.trash}`:"";
    renderFilterChips($("#active-filters"),state.filters,labels,display,field=>guarded(async()=>{delete state.filters[field];state.page=1;await load();}).catch(showError));
    if(state.assignee){const button=text("button","담당직원 조건 해제 ×");button.type='button';button.className="filter-chip";button.onclick=()=>guarded(async()=>{state.assignee="";await load();}).catch(showError);$("#active-filters").append(button);}
    loadedState=structuredClone(state);markFilterHeaders(state.filters);
    if (!siteInfo.items.length) notice("등록된 현장이 없습니다. 현장을 생성해 주세요.");
  } catch(error) {
    if(loadedState){state=structuredClone(loadedState);$("#site").value=state.site;$("#sort").value=state.sort;$("#page-size").value=String(state.size);}
    throw error;
  } finally { busy=false; status(); }
}
async function save() {
  if(!commitEditor()||busy)return false; if (!pending.size) return true;
  busy=true; status(); notice("저장 중…");
  const entries=[...pending.entries()];
  const payload={rows:entries.map(([id,item])=>({customer_id:id,assignment_id:item.base.assignment_id,mutation_id:item.mutation,expected_version:item.base.version,changes:item.changes}))};
  try {
    const data=await api("/api/customers/batch-update",payload);
    for (const result of data.results) {
      const item=pending.get(result.customer_id); if (!item) continue;
      if (result.ok) pending.delete(result.customer_id);
      else { item.error=result.error; item.server=result.server_row; item.uncertain=false; }
    }
    notice(pending.size?`${pending.size}행을 저장하지 못했습니다. 행의 ‘확인’에서 변경값을 검토하세요.`:"저장했습니다.");
    if (!pending.size) { busy=false; await load(); notice("저장했습니다."); }
    else refreshRows();
    return !pending.size;
  } catch (error) {
    for (const [,item] of entries) { item.uncertain=true; item.error={code:"UNCERTAIN",message:error.message+" 동일한 저장 요청으로 재시도합니다. 결과 확인 전에는 이 행을 편집할 수 없습니다."}; }
    refreshRows(); showError(error); return false;
  } finally { busy=false; status(); }
}
async function guarded(action) {
  if(!commitEditor()||busy||callbacks?.busy||hard?.busy)return false;
  if(hard?.pending.value){notice('먼저 영구 삭제 결과를 확인하거나 대기 정보를 폐기해 주세요.');return false;}
  if(callbacks?.pending.value&&!await callbacks.run())return false;
  if (pending.size) {
    const decision=await new Promise(resolve=>{
      const dialog=$("#dirty-dialog"); let settled=false;
      const finish=value=>{if(settled)return;settled=true;dialog.close();resolve(value);};
      $("#dirty-stay").onclick=()=>finish("stay"); $("#dirty-discard").onclick=()=>finish("discard"); $("#dirty-save").onclick=()=>finish("save");
      dialog.oncancel=event=>{event.preventDefault();finish("stay");}; dialog.showModal();
    });
    if (decision==="stay") return false;
    if (decision==="save" && !await save()) return false;
    if (decision==="discard") { const original=[...pending.values()].map(item=>item.base);pending.clear();await table.updateData(original);refreshRows();status(); }
  }
  await action(); return true;
}
$("#save")?.addEventListener("click",save);
$("#site").addEventListener("change",async event=>{ const selected=event.target.value; if (!await guarded(async()=>{state.site=selected;state.page=1;await load();}).catch(showError)) event.target.value=state.site; });
$("#sort").addEventListener("change",async event=>{const sort=event.target.value; await guarded(async()=>{state.sort=sort;state.page=1;await load();}).catch(showError);event.target.value=state.sort;});
$("#page-size").addEventListener("change",async event=>{const size=Number(event.target.value);await guarded(async()=>{state.size=size;state.page=1;await load();}).catch(showError);event.target.value=String(state.size);});
$("#search-form").addEventListener("submit",event=>{event.preventDefault();const q=$("#search").value;guarded(async()=>{state.q=q;state.page=1;await load();}).catch(showError);});
$("#previous").onclick=()=>guarded(async()=>{state.page--;await load();}).catch(showError);
$("#next").onclick=()=>guarded(async()=>{state.page++;await load();}).catch(showError);
$("#clear-filters").onclick=()=>guarded(async()=>{state.filters={};state.assignee="";state.q="";$("#search").value="";state.page=1;await load();}).catch(showError);
window.addEventListener("beforeunload",event=>{const valid=commitEditor();if(!valid||pending.size||hard?.pending.value){event.preventDefault();event.returnValue="";}});
document.addEventListener("click",event=>{
  const link=event.target.closest("a[href]"); if(!link)return;if(!commitEditor()){event.preventDefault();event.stopImmediatePropagation();return;}if(!pending.size&&!busy&&!hard?.busy&&!hard?.pending.value)return;
  event.preventDefault(); event.stopImmediatePropagation(); guarded(()=>{location.href=link.href;}).catch(showError);
},true);
document.querySelector('form[action="/auth/logout"]')?.addEventListener("submit",event=>{
  if(!commitEditor()){event.preventDefault();event.stopImmediatePropagation();return;}
  if (!pending.size&&!busy&&!hard?.busy&&!hard?.pending.value)return;event.preventDefault();event.stopImmediatePropagation();const form=event.target;guarded(()=>form.submit()).catch(showError);
},true);
document.querySelectorAll("[data-close]").forEach(button=>button.onclick=()=>button.closest("dialog").close());
$("#create-site")?.addEventListener("click",()=>guarded(()=>{$("#site-error").textContent="";$("#site-name").value="";$("#site-dialog").showModal();}).catch(showError));
$("#site-form").onsubmit=async event=>{
  event.preventDefault(); const button=event.submitter;button.disabled=true;
  try { const site=await api("/api/sites",{name:$("#site-name").value}); await loadSites(site.id); state.page=1;state.filters={};state.q="";$("#search").value="";await load();$("#site-dialog").close(); }
  catch(error){$("#site-error").textContent=error.message;}finally{button.disabled=false;}
};
$('#rename-site')?.addEventListener('click',()=>guarded(()=>{
  renameTarget=siteInfo.items.find(site=>site.id===state.site);
  if(!renameTarget){notice('변경할 현장을 선택해 주세요.');return;}
  $('#rename-site-error').textContent='';$('#rename-site-name').value=renameTarget.name;
  $('#rename-site-dialog').showModal();$('#rename-site-name').focus();
}).catch(showError));
$('#rename-site-dialog')?.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
if($('#rename-site-form'))$('#rename-site-form').onsubmit=async event=>{
  event.preventDefault();if(busy||!renameTarget)return;
  const body={name:$('#rename-site-name').value,expected_version:renameTarget.version};
  busy=true;status();const controls=[...$('#rename-site-form').querySelectorAll('input,button')];controls.forEach(control=>control.disabled=true);
  try{
    const result=await api(`/api/sites/${renameTarget.id}`,body,'PATCH',{'X-TM-Actor':$('#management').dataset.userId});
    await loadSites(result.id);await load();$('#rename-site-dialog').close();
    notice(result.changed?'현장명을 변경했습니다.':'현장명이 이미 반영되어 있습니다.');
  }catch(error){$('#rename-site-error').textContent=error.message;}
  finally{busy=false;controls.forEach(control=>control.disabled=false);status();}
};
function openConflict(id) {
  const item=pending.get(id);if(!item)return;conflictId=id;
  const content=[item.error.message];
  if(item.server)content.push(`현재 고객: ${display('customer_name',item.server.customer_name)} · ${display('phone_normalized',item.server.phone_normalized)}`);
  for(const [field,value] of Object.entries(item.changes))content.push(`${labels[field]}\n${item.server?"서버":"편집 시작값 (최신 서버값 미확인)"}: ${display(field,(item.server||item.base)[field])}\n내 변경: ${display(field,value)}`);
  $("#conflict-values").textContent=content.join("\n\n");
  $("#conflict-reapply").disabled=!item.server || item.server.assignment_id!==item.base.assignment_id || item.server.deleted_at;
  $("#conflict-dialog").showModal();
}
$("#conflict-discard").onclick=async()=>{pending.delete(conflictId);$("#conflict-dialog").close();await load().catch(showError);};
$("#conflict-reapply").onclick=async()=>{const item=pending.get(conflictId);item.base=structuredClone(item.server);item.error=null;item.uncertain=false;item.mutation=newRequestId();await table.updateData([{...item.base,...item.changes}]);$("#conflict-dialog").close();refreshRows();status();};
$("#bulk").onclick=()=>guarded(()=>{
  const ids=table.getSelectedData().map(row=>row.id);if(!ids.length){notice("현재 페이지에서 고객을 선택해 주세요.");return;}
  bulkBody={customer_ids:ids,site_id:state.site,idempotency_key:newRequestId()};
  $("#bulk-summary").textContent=trash?`현재 페이지에서 선택한 ${ids.length}건을 복구합니다.`:`${ids.length}개의 정보를 삭제하시겠습니까?`;$("#bulk-dialog").showModal();
}).catch(showError);
$("#bulk-confirm").onclick=async()=>{
  const button=$("#bulk-confirm");button.disabled=true;busy=true;status();
  try {const result=await api(trash?"/api/customers/restore":"/api/customers/soft-delete",bulkBody);$("#bulk-dialog").close();busy=false;await load();notice(`${result.affected_count}건 처리했습니다.`);}
  catch(error){showError(error);$("#bulk-summary").textContent=error.message+" 같은 작업으로 재시도할 수 있습니다.";}
  finally{button.disabled=false;busy=false;status();}
};

function openFilter(field){
  void openGridFilter({field,label:labels[field],schema,current:state.filters[field],request:api,params,display,
    apply:async condition=>{
      const previous=structuredClone(state);
      if(condition===undefined)delete state.filters[field];else state.filters[field]=condition;
      state.page=1;
      try{await load();}catch(problem){state=previous;throw problem;}
    }}).catch(showError);
}
async function openAssignee(id){
  if(assigneeOperation.value)return;assigneeRow=rows.get(id);if(!assigneeRow)return;
  busy=true;status();
  try{const data=await api("/api/assignments/availability?"+new URLSearchParams({site_id:state.site}));$("#assignee-customer").textContent=`${assigneeRow.customer_name} · 현재 담당: ${assigneeRow.assignee_name||"미할당"}`;
    $("#assignee-target").replaceChildren(option("","미할당 · 회수"),...data.employees.map(person=>option(person.id,`${person.name} · ${person.phone}`)));
    if(assigneeRow.assignee_id&&!data.employees.some(person=>person.id===assigneeRow.assignee_id)){const current=option(assigneeRow.assignee_id,`${assigneeRow.assignee_name} · 현재 담당 (신규 배정 불가)`);current.disabled=true;$("#assignee-target").append(current);}
    $("#assignee-target").value=assigneeRow.assignee_id||"";$("#assignee-dialog").showModal();
  }finally{busy=false;status();}
}
async function executeAssignee(value){
  if(busy)return;busy=true;status();
  try{const result=await assigneeOperation.execute(value);$("#assignee-dialog").close();busy=false;await load();notice(result.changed?"담당자를 변경했습니다. 상담정보는 유지했습니다.":"같은 담당자이므로 변경하지 않았습니다.");}
  catch(error){$("#assignee-dialog").close();notice(error.message);if(!assigneeOperation.value){busy=false;try{await load();}catch{}notice(error.message);}}
  finally{busy=false;status();}
}
if(!trash){$("#assignee-cancel").onclick=()=>$("#assignee-dialog").close();$("#assignee-confirm").onclick=()=>executeAssignee({endpoint:`/api/customers/${assigneeRow.id}/assignee`,body:{site_id:state.site,employee_id:$("#assignee-target").value||null,assignment_id:assigneeRow.assignment_id,expected_version:assigneeRow.version,idempotency_key:newRequestId()}});
  $("#assignee-retry").onclick=()=>executeAssignee();$("#assignee-discard").onclick=async()=>{assigneeOperation.clear();await load().catch(showError);notice("대기 정보를 폐기했습니다. 현재 담당자를 확인해 주세요.");};}
await ready;
callbacks=new CallbackAction({userId:$('#management').dataset.userId,request:actorRequest,flush:async()=>!pending.size||save(),getRow:id=>rows.get(id),refresh:load,notice,changed:status});callbacks.update();
hard=new HardDelete({userId:$('#management').dataset.userId,request:actorRequest,refresh:async siteDeleted=>{if(siteDeleted){await loadSites();state.page=1;state.filters={};state.q='';state.assignee='';$('#search').value='';const url=new URL(location.href);if(state.site)url.searchParams.set('site_id',state.site);else url.searchParams.delete('site_id');url.searchParams.delete('assignee_id');history.replaceState(null,'',url);}await load();},notice,changed:status});hard.update();
$('#delete-site')?.addEventListener('click',()=>guarded(()=>{const site=siteInfo.items.find(site=>site.id===state.site);if(site)hard.openSite(site);}).catch(showError));
if(trash)await table.addColumn({title:'영구 삭제',field:'_hard',headerSort:false,minWidth:130,formatter:cell=>{const button=text('button','영구 삭제');button.className='hard-customer btn btn-sm btn-outline-danger';button.onclick=()=>guarded(()=>hard.openCustomer(cell.getRow().getData())).catch(showError);return button;}});
busy=true;status();
// Keyboard focus can scroll the clipped header independently of the row holder.
// Keep both native scroll containers aligned without changing vendor code.
const header=$("#customer-grid .tabulator-header-contents"), holder=$("#customer-grid .tabulator-tableholder");
header.addEventListener("scroll",()=>{if(Math.abs(holder.scrollLeft-header.scrollLeft)>1)holder.scrollLeft=header.scrollLeft;});
try {await loadSites((!trash&&assigneeOperation.value?.body.site_id)||new URL(location.href).searchParams.get("site_id")||undefined);await load();}catch(error){showError(error);}finally{busy=false;status();}
