import {api} from './api.js';
let generation=0;
const $=id=>document.getElementById(id);
const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value??'';if(cls)node.className=cls;return node;};
const ns='http://www.w3.org/2000/svg';
const svg=(tag,attrs={},content)=>{const node=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));if(content!==undefined)node.textContent=content;return node;};
const format=n=>new Intl.NumberFormat('ko-KR').format(n);
const colors={INTERESTED:'#2674ed',CALL_AGAIN:'#e7a52c',VISIT_BOOKED:'#2aaf9d',VISITED:'#8670db',REVISITED:'#b38cdf',NO_ANSWER:'#9caec6',REJECTED:'#e58080',null:'#d2dbe8'};
const resultOrder=['INTERESTED','CALL_AGAIN','VISIT_BOOKED','VISITED','REVISITED','NO_ANSWER','REJECTED',null];
function icon(name){const node=svg('svg',{'class':'icon','aria-hidden':'true'});node.append(svg('use',{href:new URL('./icons.svg',import.meta.url).href+'#'+name}));return node;}
function summary(data){
  const target=$('dashboard-summary');if(!target)return;
  const items=data.employee?
    [['현재 보유 고객',data.employee.held_total,'내가 담당하고 있는 고객','customers'],['오늘까지 재콜',data.employee.callbacks_due_today_or_past,'오늘·기한 지난 미완료 재콜','calendar'],['오늘 새로 받은 고객',data.employee.assigned_today_unique,'오늘 배정받은 고유 고객','distribute'],['기한 지난 재콜',data.employee.callbacks_overdue,'지금까지 미완료인 재콜','calendar']]:
    [['전체 고객',data.counts.total,'선택 현장의 현재 고객','customers'],['미할당 고객',data.counts.unassigned,'직원 분배 대기','distribute'],['오늘 할당 DB',data.manager.assigned_today_unique,'중복 고객 제외 · 오늘 배정 이력','calendar'],['활성 직원',data.employees.length,'현재 업무 중인 직원','users']];
  const list=document.createElement('dl');list.className='overview-metrics';
  items.forEach(([label,value,caption,symbol],index)=>{const card=document.createElement('div');card.className='overview-metric';card.dataset.tone=['blue','teal','amber','violet'][index];const title=text('dt',label);title.prepend(icon(symbol));const number=text('dd',format(value));number.append(text('span',label==='활성 직원'?'명':'건'));card.append(title,number,text('p',caption));list.append(card);});
  target.replaceChildren(list);target.setAttribute('aria-busy','false');
}
function staffChart(report){
  const area=$('staff-record-chart');if(!area)return;
  if(!report.staff.length){area.replaceChildren(text('p','표시할 직원이 없습니다.','chart-empty'));return;}
  const width=Math.max(620,report.staff.length*88+70),height=282,left=48,right=18,top=22,bottom=222;
  const max=Math.max(1,...report.staff.map(e=>e.consultation_records_7d));
  const step=Math.max(1,Math.ceil(max/4)),ceiling=step*4;
  const drawing=svg('svg',{viewBox:`0 0 ${width} ${height}`,'class':'staff-chart',role:'img','aria-labelledby':'staff-chart-title staff-chart-desc'});
  drawing.append(svg('title',{id:'staff-chart-title'},'최근 7일 직원별 상담 고객 수'),svg('desc',{id:'staff-chart-desc'},'가로축 직원, 세로축 중복을 제외한 상담 고객 수. '+report.staff.map(e=>`${e.name} ${e.consultation_records_7d}명`).join(', ')));
  for(let i=0;i<=4;i++){const y=bottom-(bottom-top)*i/4;drawing.append(svg('line',{x1:left,x2:width-right,y1:y,y2:y,'class':i===0?'chart-baseline':'chart-gridline'}),svg('text',{x:left-10,y:y+4,'text-anchor':'end'},String(step*i)));}
  const slot=(width-left-right)/report.staff.length;
  report.staff.forEach((e,i)=>{const count=e.consultation_records_7d,barWidth=Math.min(42,slot*.52),x=left+slot*(i+.5),h=(bottom-top)*count/ceiling;
    const bar=svg('rect',{x:x-barWidth/2,y:bottom-h,width:barWidth,height:h,rx:4,'class':'staff-bar'});bar.append(svg('title',{},`${e.name}: ${format(count)}명`));drawing.append(bar,svg('text',{x,y:bottom-h-9,'text-anchor':'middle','class':'bar-value'},format(count)));
    const label=svg('text',{x,y:bottom+23,'text-anchor':'middle','class':'bar-label'},e.name.length>8?e.name.slice(0,8)+'…':e.name);label.append(svg('title',{},e.name));drawing.append(label);
    if(!e.is_active||!e.is_employee)drawing.append(svg('text',{x,y:bottom+42,'text-anchor':'middle'},!e.is_active?'비활성':'권한 변경'));
  });
  drawing.style.minWidth=width+'px';area.replaceChildren(drawing);
  const date=value=>new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',month:'numeric',day:'numeric'}).format(new Date(value));
  $('staff-record-range').textContent=`${date(report.records_start)}부터 오늘까지 · 같은 고객은 직원별 1명으로 집계`;
}
function resultChart(distribution){
  const area=$('call-result-chart'),legend=$('call-result-legend');if(!area||!legend)return;
  const drawing=svg('svg',{viewBox:'0 0 220 220','class':'donut-chart',role:'img','aria-labelledby':'result-chart-title result-chart-desc'});
  drawing.append(svg('title',{id:'result-chart-title'},'상담결과 비율'),svg('desc',{id:'result-chart-desc'},`${distribution.total}명의 고객. `+distribution.results.map(r=>`${r.label} ${r.count}건`).join(', ')));
  const radius=76,circumference=2*Math.PI*radius;
  drawing.append(svg('circle',{cx:110,cy:110,r:radius,fill:'none',stroke:'#edf2fa','stroke-width':26}));
  let offset=0;
  const rows=resultOrder.map(value=>distribution.results.find(r=>r.value===value)).filter(Boolean);
  for(const row of rows){if(!row.count)continue;const length=row.count/distribution.total*circumference;
    const segment=svg('circle',{cx:110,cy:110,r:radius,fill:'none',stroke:colors[row.value],'stroke-width':26,'stroke-dasharray':`${length} ${circumference-length}`,'stroke-dashoffset':-offset,transform:'rotate(-90 110 110)'});segment.append(svg('title',{},`${row.label} ${format(row.count)}건`));drawing.append(segment);offset+=length;}
  drawing.append(svg('text',{x:110,y:108,'text-anchor':'middle','class':'donut-total'},format(distribution.total)+'건'),svg('text',{x:110,y:133,'text-anchor':'middle','class':'donut-caption'},distribution.total?'집계 고객':'상담결과 없음'));
  area.replaceChildren(drawing);
  legend.replaceChildren(...rows.map(row=>{const item=document.createElement('li'),dot=text('span','','result-dot');dot.style.backgroundColor=colors[row.value];item.append(dot,text('span',row.label),text('strong',format(row.count)+'건'),text('small',distribution.total?(row.count/distribution.total*100).toFixed(1)+'%':'0%'));return item;}));
  $('result-basis').textContent=distribution.period==='all'?'선택한 현장의 현재 고객 상태':`${distribution.period==='week'?'금주 월요일부터 일요일':'오늘'} · 현재까지 저장한 고객별 마지막 결과`;
}
function table(headers){const node=document.createElement('table');node.className='table';const head=document.createElement('thead'),row=document.createElement('tr');for(const label of headers){const cell=text('th',label);cell.scope='col';row.append(cell);}head.append(row);const body=document.createElement('tbody');node.append(head,body);return {node,body};}
function staffTables(data){
  const allocation=table(['직원명','오늘 분배 DB','최근 7일 분배 DB','최근 7일 배정 횟수','현재 보유 DB']);
  const progress=table(['직원명','현재 보유','진행','미진행','상담 진행률','상담결과','계약']);
  const name=e=>{const cell=document.createElement('td'),link=text('a',e.name,'staff-name');link.href='/app/admin/customers?'+new URLSearchParams({site_id:data.site_id||'',assignee_id:e.id});cell.append(link);if(!e.is_active||!e.is_employee)cell.append(text('div',!e.is_active?'비활성 직원':'권한 변경 직원','staff-state'));return cell;};
  for(const e of data.manager.staff){
    const row=document.createElement('tr');row.dataset.employeeId=e.id;row.append(name(e));for(const value of [e.assigned_today_unique,e.assigned_7d_unique,e.assignment_operations_7d,e.held_total])row.append(text('td',format(value)));allocation.body.append(row);
    const p=document.createElement('tr');p.dataset.employeeId=e.id;p.append(name(e));for(const value of [e.held_total,e.progressed_total,e.unprogressed_total])p.append(text('td',format(value)));
    const ratio=e.held_total?Math.round(e.progressed_total/e.held_total*100):0,cell=document.createElement('td'),track=text('div','','progress-track'),fill=document.createElement('span');fill.style.width=ratio+'%';track.setAttribute('role','img');track.setAttribute('aria-label',`보유 ${e.held_total}건 중 진행 ${e.progressed_total}건`);track.append(fill);cell.append(track,text('div',e.held_total?`${ratio}% · ${format(e.progressed_total)} / ${format(e.held_total)}건`:'현재 보유 없음','progress-caption'));p.append(cell);
    const resultCell=document.createElement('td'),chips=text('div','','status-chips');for(const result of e.call_results.filter(r=>r.count))chips.append(text('span',`${result.label} ${format(result.count)}`,'status-chip'));if(!chips.childNodes.length)chips.append(text('span','현재 보유 없음','staff-state'));resultCell.append(chips);p.append(resultCell,text('td',format(e.contracted_total)+'건'));progress.body.append(p);
  }
  if(!data.manager.staff.length){for(const {body} of [allocation,progress]){const row=document.createElement('tr'),cell=text('td','표시할 직원이 없습니다.');cell.colSpan=8;row.append(cell);body.append(row);}}
  $('staff-allocation-table').replaceChildren(allocation.node);$('staff-progress-table').replaceChildren(progress.node);
}
function legacyStatistics(data,area){
  if(data.employee){const e=data.employee,items=[['오늘 할당받은 고유 DB',e.assigned_today_unique],['오늘 재콜할 DB (오늘·과거 미완료)',e.callbacks_due_today_or_past],['오늘 신규 할당 현재 보유',e.current_assignment_today_held],['기한 지난 재콜',e.callbacks_overdue],['현재 보유 전체',e.held_total]],list=document.createElement('dl');list.className='dashboard-cards';for(const [label,value] of items){const card=document.createElement('div');card.append(text('dt',label),text('dd',value));list.append(card);}area.append(list);return;}
  const {node,body}=table(['활성 직원','오늘 할당 고유 DB','오늘 할당 작업 횟수','현재 보유 전체','오늘 할당 중 현재 보유','회수·이관·삭제된 DB','미진행: 오늘 할당 중 현재 보유','미진행: 현재 보유 전체','오늘 할당 중 현재 보유의 통화결과']);node.classList.add('dashboard-table');
  for(const e of data.employees){const row=document.createElement('tr');row.dataset.employeeId=e.id;for(const value of [e.name,e.assigned_today_unique,e.assignment_operations_today,e.held_total,e.assigned_today_held,e.assigned_today_removed,e.unprogressed_today_held,e.unprogressed_total,e.call_results.map(r=>`${r.label} ${r.count}`).join(' · ')])row.append(text('td',value));body.append(row);}area.append(node,text('p',`비활성 직원의 진행 DB · 이관 필요 ${data.transfer_needed}건 (선택 현장)`));if(!data.employees.length)area.append(text('p','활성 직원이 없습니다.'));
}
export async function renderDashboard(site){
  const current=++generation,area=$('dashboard-statistics'),message=$('dashboard-message'),target=$('dashboard-summary');
  if(target){target.setAttribute('aria-busy','true');target.replaceChildren(text('p','업무 현황을 불러오고 있습니다…','summary-loading'));}
  const manager=$('manager-dashboard');if(manager){manager.setAttribute('aria-busy','true');for(const id of ['staff-record-chart','call-result-chart','staff-allocation-table','staff-progress-table'])$(id).replaceChildren(text('p','조회 중…','chart-empty'));$('call-result-legend').replaceChildren();$('staff-record-range').textContent='조회 중';$('result-basis').textContent='조회 중';}
  message.textContent='조회 중…';area.replaceChildren();
  try{
    const params=new URLSearchParams();if(site)params.set('site_id',site);if($('result-period'))params.set('result_period',$('result-period').value);
    const data=await api('/api/dashboard'+(params.size?'?'+params:''),undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});if(current!==generation)return;
    summary(data);message.textContent=`${data.business_date} · 한국 시각 기준 · 조회 시점 ${new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',timeStyle:'short',hourCycle:'h23'}).format(new Date(data.as_of))}`;
    if(data.manager){staffChart(data.manager);resultChart(data.manager.distribution);staffTables(data);manager?.setAttribute('aria-busy','false');}
    legacyStatistics(data,area);
  }catch(error){if(current!==generation)return;area.replaceChildren();message.textContent=error.message;if(target){target.replaceChildren(text('p','업무 현황을 불러오지 못했습니다. 통계 새로고침으로 다시 확인해 주세요.','summary-loading'));target.setAttribute('aria-busy','false');}if(manager){for(const id of ['staff-record-chart','call-result-chart','staff-allocation-table','staff-progress-table'])$(id).replaceChildren(text('p','현황을 불러오지 못했습니다. 새로고침해 주세요.','chart-empty'));manager.setAttribute('aria-busy','false');}}
}
$('result-period')?.addEventListener('change',()=>renderDashboard($('default-site').value));
for(const button of document.querySelectorAll('[data-staff-view]'))button.addEventListener('click',()=>{for(const item of document.querySelectorAll('[data-staff-view]'))item.setAttribute('aria-pressed',String(item===button));$('staff-allocation-panel').hidden=button.dataset.staffView!=='allocation';$('staff-progress-panel').hidden=button.dataset.staffView!=='progress';});
