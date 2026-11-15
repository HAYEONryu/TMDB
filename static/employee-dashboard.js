import {api,option} from './api.js';
import {renderDashboard,dashboardTime,showDashboardSetupError} from './dashboard.js';
import {syncEmployeeSiteLinks} from './employee-navigation.js';
import {customerLabels,choiceLabel} from './customer-columns.js';

const $=id=>document.getElementById(id),select=$('employee-dashboard-site'),panel=$('employee-customer-panel'),area=$('employee-customer-list');
const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value??'';if(cls)node.className=cls;return node;};
const number=value=>new Intl.NumberFormat('ko-KR').format(value);
const categories={held:'현재 보유 고객',callbacks_remaining:'오늘 남은 재콜',new_today:'오늘 받은 고객',overdue:'기한 지난 재콜',visits:'오늘 방문예약',contracted:'내 담당 계약'};
let generation=0,listSequence=0,selectedCategory=null,defaultSite='',activeSite=null,lastList=null,counts={};
const date=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)):'-';
function syncButtons(){for(const button of document.querySelectorAll('[data-customer-category]'))button.setAttribute('aria-expanded',String(!panel.hidden&&button.dataset.customerCategory===selectedCategory));}
function closeDetails(){selectedCategory=null;panel.hidden=true;listSequence++;area.replaceChildren();area.setAttribute('aria-busy','false');lastList=null;syncButtons();}
$('employee-customer-close').onclick=()=>{const category=selectedCategory;closeDetails();document.querySelector(`[data-customer-category="${category}"]`)?.focus();};
document.addEventListener('click',event=>{
  const button=event.target.closest('[data-customer-category]');if(!button)return;const category=button.dataset.customerCategory;
  if(selectedCategory===category&&!panel.hidden){closeDetails();return;}
  selectedCategory=category;panel.hidden=false;$('employee-customer-title').textContent=categories[category];syncButtons();void loadList(category);
});
function customerCard(row,schema){
  const card=text('article','','employee-customer'),heading=text('div','','employee-customer-heading');card.dataset.customerId=row.id;
  heading.append(text('h4',row.customer_name||'이름 미입력'),text('span',row.phone_normalized.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3')));card.append(heading);
  const facts=text('dl','','employee-customer-facts');
  for(const field of ['callback_due_at','visit_at','assigned_at','call_result']){const item=text('div',''),value=field==='call_result'?choiceLabel(schema,field,row[field]):date(row[field]);item.append(text('dt',customerLabels[field]),text('dd',value));facts.append(item);}
  card.append(facts);
  if(row.notes)card.append(text('p',row.notes.length>200?row.notes.slice(0,200)+'…':row.notes,'customer-note-preview'));
  const link=text('a','고객 열기','btn btn-sm btn-outline-primary');link.href='/app/employee/mine?'+new URLSearchParams({site_id:row.site_id,q:row.phone_normalized});link.setAttribute('aria-label',(row.customer_name||'이름 미입력')+' 고객 열기');card.append(link);return card;
}
async function loadList(category,page=1){
  const sequence=++listSequence,revision=generation,site=select.value,same=lastList?.site===site&&lastList.category===category&&lastList.page===page;
  area.setAttribute('aria-busy','true');let status;
  if(!same){area.replaceChildren();status=text('p','고객 목록을 불러오고 있습니다…','customer-list-summary');area.append(status);}
  else{status=area.querySelector('.customer-list-summary');status.textContent='목록 갱신 중 · 마지막 결과를 표시합니다.';}
  try{
    const params=new URLSearchParams({category,page});if(site)params.set('site_id',site);
    const data=await api('/api/dashboard/customers?'+params,undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});
    if(sequence!==listSequence||revision!==generation)return;
    const difference=counts[category]!==undefined&&counts[category]!==data.total?` · 카드 조회 당시 ${number(counts[category])}명`:'';
    area.replaceChildren(text('p',`현재 ${number(data.total)}명 · ${dashboardTime(data.as_of)} 목록 조회${difference}${data.total?` · ${data.page} / ${data.last_page}페이지`:''}`,'customer-list-summary'),...data.data.map(row=>customerCard(row,data.schema)));
    if(!data.total)area.append(text('p',category==='visits'?'오늘 방문예약이 없습니다.':'해당하는 고객이 없습니다.','customer-list-empty'));
    if(data.last_page>1){const pagination=text('div','','customer-list-pagination');for(const [label,next,disabled] of [['이전',data.page-1,data.page<=1],['다음',data.page+1,data.page>=data.last_page]]){const button=text('button',label,'btn btn-sm btn-outline-secondary');button.type='button';button.disabled=disabled;button.setAttribute('aria-label','고객 목록 '+label+' 페이지');button.onclick=()=>loadList(category,next);pagination.append(button);}area.append(pagination);}
    lastList={site,category,page:data.page};
  }catch(error){if(sequence!==listSequence||revision!==generation)return;
    if([401,403].includes(error.status)){closeDetails();return;}
    status.textContent=`목록 조회 실패. ${same?'마지막 성공 목록을 표시합니다. ':''}${error.message}`;status.setAttribute('role','alert');const retry=text('button','목록 다시 조회','btn btn-sm btn-outline-secondary');retry.type='button';retry.onclick=()=>loadList(category,page);status.append(retry);
  }finally{if(sequence===listSequence&&revision===generation)area.setAttribute('aria-busy','false');}
}
function metricButton(category,value,label){const button=text('button',number(value)+'명','metric-details-button');button.type='button';button.dataset.customerCategory=category;button.setAttribute('aria-controls','employee-customer-panel');button.setAttribute('aria-expanded','false');button.setAttribute('aria-label',label+' '+number(value)+'명 목록 열기');return button;}
function work(data){
  const e=data.employee,p=e.consultation_progress,progress=text('article','','employee-work-result'),completed=text('article','','employee-work-result');
  const score=text('strong',p.total?`${number(p.completed)} / ${number(p.total)}명`:'오늘 배정된 고객 없음');score.id='employee-consultation-value';
  progress.append(text('h3','오늘 상담 저장'),score,text('p','오늘 받은 고객 중 현재 배정에서 내가 유효한 상담 변경을 저장한 고유 고객 수입니다. 이름·연락처·관리자 비고만 정정한 기록은 제외합니다.','tm-basis'));
  const value=text('strong',number(e.callbacks_completed_today)+'건');value.id='employee-callback-completed';completed.append(text('h3','오늘 재콜 완료'),value,text('p','선택 현장에서 내가 오늘 완료한 재콜 일정 수입니다. 예정일과 현재 담당자가 바뀌어도 완료한 작업은 유지됩니다.','tm-basis'));
  $('dashboard-statistics').replaceChildren(progress,completed);
  const holdings=text('div','','employee-holdings'),held=text('div',''),contract=text('div','');
  held.append(text('h3','현재 보유'),metricButton('held',e.held_total,'현재 보유'));contract.append(text('h3','내 담당 계약'),metricButton('contracted',e.contracted_held,'내 담당 계약'));holdings.append(held,contract);
  $('employee-contracts').replaceChildren(text('h2','현재 보유와 내 담당 계약','h5'),holdings,text('p','선택 현장 · 현재 유효한 내 배정 · 현재 계약 상태 기준','tm-basis'));
  counts={held:e.held_total,callbacks_remaining:e.callbacks_remaining,overdue:e.callbacks_overdue,new_today:e.current_assignment_today_held,visits:e.visits_today,contracted:e.contracted_held};
  syncButtons();if(selectedCategory&&!panel.hidden)void loadList(selectedCategory,lastList?.page||1);
}
function clear(){closeDetails();$('employee-contracts').replaceChildren();}
async function refresh(){
  $('dashboard-refresh').onclick=refresh;
  if(activeSite!==select.value){generation++;clear();activeSite=select.value;}
  syncEmployeeSiteLinks(select.value,defaultSite);
  const url=new URL(location.href);if(select.value&&select.value!==defaultSite)url.searchParams.set('site_id',select.value);else url.searchParams.delete('site_id');history.replaceState(null,'',url);
  await renderDashboard(select.value,{draw:work,clear});
}
try{const data=await api('/api/sites');defaultSite=data.default_site_id||'';select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));select.value=new URL(location.href).searchParams.get('site_id')||defaultSite;select.onchange=refresh;$('dashboard-refresh').onclick=refresh;await refresh();}catch(error){showDashboardSetupError(error,{clear});}
