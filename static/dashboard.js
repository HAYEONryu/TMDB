import {api} from './api.js';
let generation=0;
const $=id=>document.getElementById(id);
const text=(tag,value,cls)=>{const node=document.createElement(tag);node.textContent=value??'';if(cls)node.className=cls;return node;};
const ns='http://www.w3.org/2000/svg';
const svg=(tag,attrs={},content)=>{const node=document.createElementNS(ns,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,String(value));if(content!==undefined)node.textContent=content;return node;};
const format=n=>new Intl.NumberFormat('ko-KR').format(n);
const colors={DELETE_REQUEST:'#c05862',NEXT_SITE:'#7467bd',INTERESTED:'#2674ed',CALL_AGAIN:'#e7a52c',VISIT_BOOKED:'#2aaf9d',VISITED:'#8670db',REVISITED:'#b38cdf',NO_ANSWER:'#9caec6',REJECTED:'#e58080',null:'#d2dbe8'};
function icon(name){const node=svg('svg',{'class':'icon','aria-hidden':'true'});node.append(svg('use',{href:new URL('./icons.svg',import.meta.url).href+'#'+name}));return node;}
export const dashboardTime=value=>new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(value));
const siteLink=(path,site,category,employee,sort)=>path+'?'+new URLSearchParams({...(site?{site_id:site}:{}),...(category?{dashboard_category:category}:{}),...(employee?{assignee_id:employee}:{}),...(sort?{sort}: {})});
function renderSummary(data){
  const target=$('dashboard-summary'),e=data.employee,m=data.manager;
  const items=e?
    [['기한 지난 재콜',e.callbacks_overdue,'우선 연락 · 현재 시각 이전','calendar','overdue'],['오늘 남은 재콜',e.callbacks_remaining,'오늘 처리 · 현재 시각부터 자정 전','calendar','callbacks_remaining'],['오늘 방문예약',e.visits_today,'예약 확인 · 오늘 지난 시각도 포함','calendar','visits'],['오늘 받은 고객',e.current_assignment_today_held,'상담 시작 · 현재 배정 유지 고객','distribute','new_today']]:
    [['미배정 고객',data.counts.unassigned,'분배 대기 · 현재 유효한 배정 없음','distribute',null,siteLink('/app/admin/assignments',data.site_id)],['오늘 배정 유지',m.current_assignment_today_held,'현재 상태 · 회수된 고객 제외','customers',null,siteLink('/app/admin/customers',data.site_id,'new_today',null,'assigned_at')],['기한 지난 재콜',m.callbacks_overdue,'우선 확인 · 담당자와 예정 시각 확인','calendar',null,siteLink('/app/admin/customers',data.site_id,'overdue',null,'callback_due_at')],['이관 필요',data.transfer_needed,'담당자 확인 · 기존 이관 대상 기준','users',null,siteLink('/app/admin/users',data.site_id)+'#transfer-needed']];
  const list=document.createElement('dl');list.className='overview-metrics';
  items.forEach(([label,value,caption,symbol,category,href],index)=>{
    const card=document.createElement('div');card.className='overview-metric';card.dataset.metric=category||['unassigned','new_today','overdue','transfer'][index];card.dataset.tone=['amber','blue','teal','violet'][index];
    const title=text('dt',label);title.prepend(icon(symbol));const count=text('dd',''),control=text(href?'a':'button',format(value),'metric-details-button');
    if(href)control.href=href;else{control.type='button';control.dataset.customerCategory=category;control.setAttribute('aria-controls','employee-customer-panel');control.setAttribute('aria-expanded','false');}
    control.setAttribute('aria-label',`${label} ${format(value)}명 목록 열기`);control.append(text('span','명'));count.append(control);card.append(title,count,text('p',caption));list.append(card);
  });
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
  const rows=distribution.results;
  for(const row of rows){if(!row.count)continue;const length=row.count/distribution.total*circumference;
    const segment=svg('circle',{cx:110,cy:110,r:radius,fill:'none',stroke:colors[row.value],'stroke-width':26,'stroke-dasharray':`${length} ${circumference-length}`,'stroke-dashoffset':-offset,transform:'rotate(-90 110 110)'});segment.append(svg('title',{},`${row.label} ${format(row.count)}건`));drawing.append(segment);offset+=length;}
  drawing.append(svg('text',{x:110,y:108,'text-anchor':'middle','class':'donut-total'},format(distribution.total)+'명'),svg('text',{x:110,y:133,'text-anchor':'middle','class':'donut-caption'},distribution.total?'집계 대상':'집계 대상 없음'));
  area.replaceChildren(drawing);
  legend.replaceChildren(...rows.map(row=>{const item=document.createElement('li'),dot=text('span','','result-dot');dot.style.backgroundColor=colors[row.value];item.append(dot,text('span',row.label),text('strong',format(row.count)+'명'),text('small',distribution.total?(row.count/distribution.total*100).toFixed(1)+'%':'0%'));return item;}));
  const contracts=document.createElement('dl');contracts.className='contract-summary';
  const contractRate=distribution.total?(distribution.contracted_total/distribution.total*100).toFixed(1)+'%':'집계 대상 없음';
  for(const [label,value,id] of [['계약 상태 고객',format(distribution.contracted_total)+'명','contract-count'],['계약 비율',contractRate,'contract-rate']]){
    const item=document.createElement('div'),number=text('dd',value);number.id=id;item.append(text('dt',label),number);contracts.append(item);
  }
  $('contract-summary').replaceChildren(contracts);
  $('result-basis').textContent=(distribution.period==='all'?'선택 현장의 미삭제 고객 전체 · 현재 고객 상태':`${distribution.period==='week'?'금주 월요일 00:00부터':'오늘 00:00부터'} 조회 시각까지 유효한 상담을 저장한 고객별 마지막 결과`)+` · 집계 대상 ${format(distribution.total)}명 · 계약 ${format(distribution.contracted_total)} / ${format(distribution.total)}명`;

}
function table(headers){const node=document.createElement('table');node.className='table';const head=document.createElement('thead'),row=document.createElement('tr');for(const label of headers){const cell=text('th',label);cell.scope='col';row.append(cell);}head.append(row);const body=document.createElement('tbody');node.append(head,body);return {node,body};}
function staffTables(data){
  const workload=table(['직원','우선순위','현재 담당','오늘 배정 유지','미진행','기한 지난 재콜']);
  const history=table(['직원','오늘 배정 이력 고객','오늘 배정 작업','최근 7일 배정 고객','최근 7일 배정 작업']);
  const name=e=>{const cell=text('td',''),link=text('a',e.name,'staff-name');link.href=siteLink('/app/admin/customers',data.site_id,'held',e.id);cell.append(link);if(!e.is_active||!e.is_employee)cell.append(text('div',!e.is_active?'비활성 직원':'권한 변경 직원','staff-state'));return cell;};
  for(const e of data.manager.staff){
    const row=document.createElement('tr');row.dataset.employeeId=e.id;row.append(name(e),text('td',e.callbacks_overdue?'재콜 우선':e.unprogressed_total?'상담 대기':e.held_total?'진행 중':'현재 담당 없음',e.callbacks_overdue?'work-priority':'staff-state'));
    for(const [field,category,sort] of [['held_total','held'],['current_assignment_today_held','new_today','assigned_at'],['unprogressed_total','unprogressed'],['callbacks_overdue','overdue','callback_due_at']]){const cell=text('td',''),link=text('a',format(e[field]));link.href=siteLink('/app/admin/customers',data.site_id,category,e.id,sort);link.setAttribute('aria-label',`${e.name} ${workload.node.querySelectorAll('th')[row.children.length].textContent} ${e[field]}명 목록 열기`);cell.append(link);row.append(cell);}
    workload.body.append(row);
    const old=document.createElement('tr');old.dataset.employeeId=e.id;old.append(name(e));for(const value of [e.assigned_today_unique,e.assignment_operations_today,e.assigned_7d_unique,e.assignment_operations_7d])old.append(text('td',format(value)));history.body.append(old);
  }
  for(const list of [workload,history])if(!data.manager.staff.length){const row=text('tr',''),cell=text('td','표시할 직원이 없습니다.');cell.colSpan=6;row.append(cell);list.body.append(row);}
  $('staff-progress-table').replaceChildren(workload.node);$('staff-allocation-table').replaceChildren(history.node);
}
function legacyStatistics(data,area){
  area.replaceChildren();
  const {node,body}=table(['활성 직원','오늘 할당 고유 DB','오늘 할당 작업 횟수','현재 보유 전체','오늘 할당 중 현재 보유','회수·이관·삭제된 DB','미진행: 오늘 할당 중 현재 보유','미진행: 현재 보유 전체','오늘 할당 중 현재 보유의 통화결과']);node.classList.add('dashboard-table');
  for(const e of data.employees){const row=document.createElement('tr');row.dataset.employeeId=e.id;for(const value of [e.name,e.assigned_today_unique,e.assignment_operations_today,e.held_total,e.assigned_today_held,e.assigned_today_removed,e.unprogressed_today_held,e.unprogressed_total,e.call_results.map(r=>`${r.label} ${r.count}`).join(' · ')])row.append(text('td',value));body.append(row);}area.append(node,text('p',`비활성 직원의 진행 DB · 이관 필요 ${data.transfer_needed}건 (선택 현장)`));if(!data.employees.length)area.append(text('p','활성 직원이 없습니다.'));
}
let displayedSite=null,lastData=null;
const managerAreas=['staff-record-chart','call-result-chart','contract-summary','staff-allocation-table','staff-progress-table'];
function clearDashboard(message,extra){
  $('dashboard-summary').replaceChildren(text('p',message,'summary-loading'));$('dashboard-statistics').replaceChildren();
  for(const id of managerAreas)$(id)?.replaceChildren(text('p',message,'chart-empty'));
  $('call-result-legend')?.replaceChildren();if($('staff-record-range'))$('staff-record-range').textContent='';if($('result-basis'))$('result-basis').textContent='';if($('site-counts'))$('site-counts').textContent='';extra?.();
}
export function showDashboardSetupError(error,{clear}={}){
  generation++;
  if(!lastData){clearDashboard('현장 목록을 불러오지 못했습니다. 통계 새로고침으로 다시 확인해 주세요.',clear);$('dashboard-updated').textContent='조회 성공 기록이 없습니다.';}
  $('dashboard-message').dataset.state='error';
  $('dashboard-message').textContent=(lastData?'갱신 실패 · 마지막 성공 결과를 표시합니다. ':'현장 목록 조회 실패. ')+error.message;
  $('dashboard-summary').setAttribute('aria-busy','false');$('manager-dashboard')?.setAttribute('aria-busy','false');
  $('dashboard-refresh').onclick=()=>location.reload();
}
export async function renderDashboard(site,{draw,clear}={}){
  const current=++generation,key=site||'',message=$('dashboard-message'),summary=$('dashboard-summary');
  if(displayedSite!==key){displayedSite=key;lastData=null;clearDashboard('업무 현황을 불러오고 있습니다…',clear);$('dashboard-updated').textContent='선택 현장 조회 중';}
  summary.setAttribute('aria-busy','true');$('manager-dashboard')?.setAttribute('aria-busy','true');
  message.dataset.state='loading';message.textContent=lastData?'갱신 중 · 마지막 성공 결과를 표시합니다.':'최초 조회 중…';
  try{
    const params=new URLSearchParams();if(site)params.set('site_id',site);if($('result-period'))params.set('result_period',$('result-period').value);
    const data=await api('/api/dashboard'+(params.size?'?'+params:''),undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});if(current!==generation)return;
    if(site&&data.site_id!==site)throw new Error('선택한 현장의 응답을 확인하지 못했습니다. 다시 조회해 주세요.');
    renderSummary(data);if(data.manager){staffChart(data.manager);resultChart(data.manager.distribution);staffTables(data);legacyStatistics(data,$('dashboard-statistics'));$('site-counts').textContent=`현재 고객 ${format(data.counts.total)}명 · 현재 담당 ${format(data.manager.held_total)}명 · 휴지통 ${format(data.counts.trash)}명`;}
    draw?.(data);lastData=data;$('dashboard-updated').textContent=`마지막 성공 ${data.business_date} ${dashboardTime(data.as_of)} · ${data.site_name||'현장 없음'}`;
    message.dataset.state='success';message.textContent=(data.employee?data.employee.held_total:data.counts.total)?'선택 현장의 최신 결과입니다.':'선택 현장에 집계 대상 고객이 없습니다.';
    return data;
  }catch(error){
    if(current!==generation)return;
    if([401,403].includes(error.status)){lastData=null;clearDashboard('다시 로그인해 주세요.',clear);}
    if(!lastData){clearDashboard('업무 현황을 불러오지 못했습니다. 통계 새로고침으로 다시 확인해 주세요.',clear);$('dashboard-updated').textContent='이 현장의 조회 성공 기록이 없습니다.';}
    else if($('result-period'))$('result-period').value=lastData.manager.distribution.period;
    message.dataset.state='error';message.textContent=`${lastData?'갱신 실패 · 마지막 성공 결과를 표시합니다.':'조회 실패.'} ${error.message}`;
  }finally{if(current===generation){summary.setAttribute('aria-busy','false');$('manager-dashboard')?.setAttribute('aria-busy','false');}}
}
$('result-period')?.addEventListener('change',()=>renderDashboard($('default-site').value));
