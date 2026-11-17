import {api} from './api.js';
const $=id=>document.getElementById(id),number=n=>new Intl.NumberFormat('ko-KR').format(n);
const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value??'';return el;};
export class EmployeePerformance {
  constructor(){this.sequence=0;this.last=null;this.site='';$('performance-month').onchange=()=>this.load(this.site);$('performance-retry').onclick=()=>this.load(this.site);}
  clear(){this.sequence++;this.last=null;$('performance-rows').replaceChildren();$('today-call-attempts').textContent=$('today-call-connected').textContent='조회 전';$('performance-status').textContent='월간 실적을 조회해 주세요.';$('performance-coverage').textContent='';$('performance-retry').hidden=true;}
  async load(site){
    this.site=site;const sequence=++this.sequence,month=$('performance-month').value,same=this.last?.site_id===(site||null)&&this.last.month===month;
    if(!same){$('performance-rows').replaceChildren();$('today-call-attempts').textContent=$('today-call-connected').textContent='조회 중…';}
    $('monthly-performance').setAttribute('aria-busy','true');$('performance-status').textContent=same?'실적 갱신 중 · 마지막 결과를 표시합니다.':'실적을 불러오고 있습니다…';$('performance-retry').hidden=true;
    try{
      const params=new URLSearchParams();if(site)params.set('site_id',site);if(month)params.set('month',month);
      const data=await api('/api/dashboard/performance?'+params,undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});
      if(sequence!==this.sequence)return;
      if(site&&data.site_id!==site)throw new Error('선택한 현장의 실적을 다시 확인해 주세요.');
      this.last=data;$('performance-month').value=data.month;$('performance-month').max=data.business_date.slice(0,7);
      $('today-call-attempts').textContent=data.today.attempts===null?'집계 자료 없음':number(data.today.attempts)+'콜';
      $('today-call-connected').textContent=data.today.connected===null?'집계 자료 없음':number(data.today.connected)+'콜';
      $('today-call-basis').textContent=`${data.today.date} · 한국 시간 · 선택 현장에서 내가 기록한 발신 · 연결 확인된 통화만 연결 수에 포함`+(data.today.status==='partial'?' · 기록 도입일의 일부 실적입니다.':'');
      const rows=data.rows.map(item=>{const row=text('tr','');row.dataset.date=item.date;if(item.date===data.business_date)row.className='performance-today';
        const heading=text('th',String(Number(item.date.slice(8)))+'일');heading.scope='row';row.append(heading);
        for(const metric of ['call','prospect','visit']){const cell=text('td',item.is_future?'—':item[metric+'_count']===null?'집계 자료 없음':number(item[metric+'_count']));cell.dataset.status=item[metric+'_status'];if(item[metric+'_status']==='partial')cell.title='기록이 시작된 날의 일부 실적입니다.';row.append(cell);}return row;});
      $('performance-rows').replaceChildren(...rows);
      $('performance-status').textContent=`${data.month} · 한국 날짜 1일부터 순서대로 · ${new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(data.as_of))} 조회`;
      const from=value=>value?new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).format(new Date(value)):'미확인';
      $('performance-coverage').textContent=`통화·실제 방문 기록 도입: ${from(data.coverage.calls_from)} (한국 시간). 도입일은 일부 기록이며 이전 날짜는 집계 자료 없음입니다. 가망은 ${from(data.coverage.prospects_from)}부터 보관된 상담 이력 기준입니다. 최초 기록일은 일부 실적일 수 있습니다. 스냅샷이 부족한 날은 집계하지 않습니다. 가장 이른 자료 월: ${data.earliest_month}.`;
    }catch(error){if(sequence!==this.sequence)return;
      if([401,403].includes(error.status)){this.clear();$('performance-status').textContent='다시 로그인해 주세요.';return;}
      if(same){$('performance-month').value=this.last.month;}
      if(!same)$('today-call-attempts').textContent=$('today-call-connected').textContent='조회 실패';
      $('performance-status').textContent=`실적 조회 실패. ${same?'마지막 성공 결과를 표시합니다. ':''}${error.message}`;$('performance-retry').hidden=false;
    }finally{if(sequence===this.sequence)$('monthly-performance').setAttribute('aria-busy','false');}
  }
}
