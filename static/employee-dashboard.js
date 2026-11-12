import {api,option} from './api.js';
import {renderDashboard} from './dashboard.js';
import {syncEmployeeSiteLinks} from './employee-navigation.js';
import {customerLabels,choiceLabel} from './customer-columns.js';

const $=id=>document.getElementById(id),select=$('employee-dashboard-site');
const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value;if(cls)node.className=cls;return node;};
const number=value=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:1}).format(value);
const categories={held:'현재 보유 고객',callbacks_today:'오늘 재콜',new_today:'오늘 새로 받은 고객',overdue:'기한 지난 재콜'};
const panel=$('employee-customer-panel'),lists={details:{area:$('employee-customer-list'),sequence:0},visits:{area:$('employee-visits-list'),sequence:0}};
let generation=0,selectedCategory=null,defaultSite='';
const date=(value,time=false)=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',...(time?{hour:'2-digit',minute:'2-digit',hourCycle:'h23'}:{})}).format(new Date(value)):'-';
const phone=value=>value?value.replace(/^(010)(\d{4})(\d{4})$/,'$1-$2-$3'):'-';

function syncButtons(){
  for(const button of document.querySelectorAll('[data-customer-category]'))button.setAttribute('aria-expanded',String(!panel.hidden&&button.dataset.customerCategory===selectedCategory));
}
function closeDetails(){selectedCategory=null;panel.hidden=true;lists.details.sequence++;lists.details.area.replaceChildren();syncButtons();}
$('employee-customer-close').onclick=closeDetails;
$('dashboard-summary').addEventListener('click',event=>{
  const button=event.target.closest('[data-customer-category]');if(!button)return;
  const category=button.dataset.customerCategory;
  if(selectedCategory===category&&!panel.hidden){closeDetails();return;}
  selectedCategory=category;panel.hidden=false;$('employee-customer-title').textContent=categories[category];syncButtons();
  void loadList('details',category);
});

function customerCard(row,schema){
  const card=text('article','','employee-customer'),heading=text('div','','employee-customer-heading');card.dataset.customerId=row.id;
  heading.append(text('h4',row.customer_name||'이름 미입력'),text('span',phone(row.phone_normalized)));card.append(heading);
  const facts=document.createElement('dl');facts.className='employee-customer-facts';
  for(const field of ['call_result','contract_status','callback_due_at','visit_at','residence','housing_status','route','assigned_at','notes','memo']){
    const item=document.createElement('div');if(['notes','memo'].includes(field))item.className='customer-long-text';
    const value=['callback_due_at','assigned_at'].includes(field)?date(row[field]):field==='visit_at'?date(row[field],true):choiceLabel(schema,field,row[field]);
    item.append(text('dt',customerLabels[field]),text('dd',value));facts.append(item);
  }
  card.append(facts);return card;
}

async function loadList(kind,category,page=1){
  const list=lists[kind],sequence=++list.sequence,revision=generation,site=select.value;
  list.area.setAttribute('aria-busy','true');list.area.replaceChildren(text('p','고객 목록을 불러오고 있습니다…','text-secondary'));
  try{
    const params=new URLSearchParams({category,page});if(site)params.set('site_id',site);
    const data=await api('/api/dashboard/customers?'+params,undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});
    if(sequence!==list.sequence||revision!==generation)return;
    const summary=text('p',`총 ${number(data.total)}건${data.total?` · ${data.page} / ${data.last_page}페이지`:''}`,'customer-list-summary');
    list.area.replaceChildren(summary,...data.data.map(row=>customerCard(row,data.schema)));
    if(kind==='visits')$('employee-visits-count').textContent=`${number(data.total)}건`;
    if(!data.total)list.area.append(text('p',category==='visits'?'오늘 방문예약이 없습니다.':'해당하는 고객이 없습니다.','customer-list-empty'));
    if(data.last_page>1){
      const pagination=text('div','','customer-list-pagination');
      for(const [label,next,disabled] of [['이전',data.page-1,data.page<=1],['다음',data.page+1,data.page>=data.last_page]]){
        const button=text('button',label,'btn btn-sm btn-outline-secondary');button.type='button';button.disabled=disabled;button.setAttribute('aria-label',(kind==='visits'?'방문예약':'고객 목록')+' '+label+' 페이지');button.onclick=()=>loadList(kind,category,next);pagination.append(button);
      }
      list.area.append(pagination);
    }
  }catch(error){if(sequence===list.sequence&&revision===generation)list.area.replaceChildren(text('p',error.message,'text-danger'));}
  finally{if(sequence===list.sequence&&revision===generation)list.area.setAttribute('aria-busy','false');}
}

function work(data){
  const e=data.employee,area=$('dashboard-statistics'),title=text('div','','tm-heading'),score=text('strong',`${number(e.tm.percent)}%(${number(e.tm.completed)}/${number(e.tm.total)})`);score.id='employee-tm-value';
  title.append(text('h3','TM 달성률'),score);
  const progress=text('div','','employee-tm-track'),fill=document.createElement('span');fill.style.width=e.tm.percent+'%';progress.append(fill);
  progress.setAttribute('role','progressbar');progress.setAttribute('aria-label','TM 달성률');progress.setAttribute('aria-valuemin','0');progress.setAttribute('aria-valuemax','100');progress.setAttribute('aria-valuenow',String(e.tm.percent));
  area.replaceChildren(title,progress,text('p','오늘 받은 고객과 오늘까지의 재콜 대상 중 완료한 고객 수 · 같은 고객은 1건으로 집계합니다. 배정 고객은 상담 저장, 재콜은 완료 체크 시 반영됩니다.','tm-basis'));
  $('employee-visits-count').textContent=`${number(e.visits_today)}건`;
  const contracts=$('employee-contracts'),heading=text('h2','선택 현장 계약 현황'),count=text('strong',number(e.site_contracted_total)+'건');count.id='employee-site-contract-count';
  const emoji=text('span',e.site_contracted_total?'🎉':'👍');emoji.setAttribute('aria-hidden','true');heading.prepend(emoji);
  contracts.replaceChildren(heading,count,text('p',`내 담당 고객의 계약 ${number(e.contracted_held)}건 · 현재 계약 상태 기준`));
  void loadList('visits','visits');
}

async function refresh(){
  const revision=++generation;closeDetails();lists.visits.sequence++;
  $('employee-visits-count').textContent='';lists.visits.area.replaceChildren();$('employee-contracts').replaceChildren();
  syncEmployeeSiteLinks(select.value,defaultSite);
  const data=await renderDashboard(select.value);if(revision!==generation||!data)return;
  work(data);
}
try{
  const data=await api('/api/sites');defaultSite=data.default_site_id||'';select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));
  select.value=new URL(location.href).searchParams.get('site_id')||defaultSite;
  select.onchange=refresh;$('dashboard-refresh').onclick=refresh;await refresh();
}catch(error){$('dashboard-message').textContent=error.message;}
