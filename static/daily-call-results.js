import {api} from './api.js';
const $=id=>document.getElementById(id),kstDay=value=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date(value));
export class DailyCallResults{
  constructor(){
    this.sequence=0;this.site='';this.last=null;this.followToday=true;this.ready=false;
    $('call-results-date').onchange=()=>{this.followToday=!$('call-results-date').value||$('call-results-date').value===this.clock?.day;void this.load(this.site);};
    $('call-results-retry').onclick=()=>this.load(this.site);
    const refresh=()=>{if(this.ready&&document.visibilityState==='visible')void this.load(this.site);};
    window.addEventListener('focus',refresh);document.addEventListener('visibilitychange',refresh);
    setInterval(()=>{if(this.ready&&this.followToday&&this.clock&&document.visibilityState==='visible'&&navigator.onLine&&kstDay(this.clock.at+Date.now()-this.clock.received)!==this.clock.day)void this.load(this.site);},30000);
  }
  clear(){
    this.sequence++;this.ready=false;this.last=null;$('daily-call-results').setAttribute('aria-busy','false');$('call-results-status').textContent='일별 통화결과를 조회해 주세요.';
    document.querySelectorAll('[data-call-result]').forEach(cell=>{cell.textContent='조회 전';cell.parentElement.style.setProperty('--result-percent','0%');});
    $('call-results-coverage').textContent='';$('call-results-retry').hidden=true;
  }
  async load(site){
    this.site=site;this.ready=true;const sequence=++this.sequence,date=$('call-results-date').value;
    const same=this.last?.site_id===(site||null)&&this.last?.date===date;
    $('daily-call-results').setAttribute('aria-busy','true');$('call-results-status').textContent='일별 통화결과를 불러오고 있습니다…';$('call-results-retry').hidden=true;
    if(!same)document.querySelectorAll('[data-call-result]').forEach(cell=>{cell.textContent='조회 중…';cell.parentElement.style.setProperty('--result-percent','0%');});
    try{
      const params=new URLSearchParams();if(site)params.set('site_id',site);if(!this.followToday&&date)params.set('date',date);
      const data=await api('/api/dashboard/call-results?'+params,undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});
      if(sequence!==this.sequence)return;
      this.last=data;this.clock={at:new Date(data.as_of).getTime(),received:Date.now(),day:data.business_date};
      $('call-results-date').value=data.date;$('call-results-date').max=data.business_date;
      const maximum=Math.max(1,...data.items.map(item=>item.count||0));
      for(const item of data.items){const cell=document.querySelector('[data-call-result="'+item.code+'"]');cell.textContent=item.count===null?'집계 자료 없음':new Intl.NumberFormat('ko-KR').format(item.count)+'명';cell.parentElement.style.setProperty('--result-percent',(item.count==null?0:item.count/maximum*100)+'%');}
      $('call-results-status').textContent=data.date+' · 한국 시간 · '+(data.status==='unavailable'?'집계 자료 없음':data.status==='partial'?'이력 도입일의 일부 기록입니다.':'조회 완료');
      $('call-results-coverage').textContent=data.earliest_date?'상담 이력 도입: '+data.earliest_date+' · 이전 기간이나 결과 스냅샷이 부족한 날은 집계 자료 없음입니다.':'상담 이력 도입 시점을 확인할 수 없어 집계 자료 없음으로 표시합니다.';
    }catch(error){
      if(sequence!==this.sequence)return;
      if([401,403].includes(error.status)){this.clear();$('call-results-status').textContent='다시 로그인해 주세요.';return;}
      if(!same)document.querySelectorAll('[data-call-result]').forEach(cell=>cell.textContent='조회 실패');
      $('call-results-status').textContent='일별 통화결과를 불러오지 못했습니다. 다시 조회해 주세요.'+(same?' 마지막 성공 결과를 표시합니다.':'');$('call-results-retry').hidden=false;
    }finally{if(sequence===this.sequence)$('daily-call-results').setAttribute('aria-busy','false');}
  }
}
