import {api} from './api.js';
import {metricValue,totalValue,dailyChart,dailyValues} from './performance-view.js';
const $=id=>document.getElementById(id),text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value??'';return el;};
export class StaffPerformance{
  constructor(){this.sequence=0;this.site='';this.data=null;this.metric='call';$('staff-month').onchange=()=>this.load(this.site);for(const button of document.querySelectorAll('[data-staff-metric]'))button.onclick=()=>{this.metric=button.dataset.staffMetric;this.chart();};}
  chart(){
    const target=$('staff-month-chart');target.replaceChildren();for(const button of document.querySelectorAll('[data-staff-metric]'))button.setAttribute('aria-pressed',String(button.dataset.staffMetric===this.metric));
    if(!this.data)return;const max=Math.max(1,...this.data.employees.map(p=>p.totals[this.metric].count||0)),list=text('ul','');list.className='staff-comparison';
    for(const person of this.data.employees){const row=text('li',''),meter=document.createElement('meter');meter.min=0;meter.max=max;meter.value=person.totals[this.metric].count||0;meter.setAttribute('aria-label',person.name);row.append(text('span',person.name),meter,text('strong',totalValue(person.totals[this.metric],this.metric==='call'||this.metric==='connected'?'콜':'명')));list.append(row);}target.append(list);
  }
  details(person){
    const panel=$('staff-day-detail');panel.hidden=false;panel.replaceChildren();const title=text('h3',person.name+' · '+this.data.month+' 일별 실적'),close=text('button','닫기');close.type='button';close.className='text-control';close.onclick=()=>{panel.hidden=true;document.querySelector(`[data-staff-detail="${person.id}"]`)?.focus();};
    const chart=text('div',''),values=text('div',''),select=document.createElement('select');select.className='form-select';select.setAttribute('aria-label',person.name+' 실적 날짜');
    const show=day=>{select.value=day;dailyValues(values,person.rows.find(r=>r.date===day));for(const bar of chart.querySelectorAll('[data-date]'))bar.setAttribute('aria-pressed',String(bar.dataset.date===day));};
    dailyChart(chart,person,show);for(const row of person.rows.filter(r=>!r.is_future)){const option=text('option',row.date);option.value=row.date;select.append(option);}select.onchange=()=>show(select.value);
    const wrap=text('div','');wrap.className='table-responsive';const table=text('table','');table.className='table';const head=text('thead',''),hr=text('tr',''),body=text('tbody','');for(const label of ['날짜','콜 수','연결된 통화','가망고객 수','실제 방문고객 수'])hr.append(text('th',label));head.append(hr);
    for(const row of person.rows){const tr=text('tr','');tr.append(text('th',row.date));for(const key of ['call','connected','prospect','visit'])tr.append(text('td',row.is_future?'—':metricValue(row[key+'_count'])));body.append(tr);}table.append(head,body);wrap.append(table);
    panel.append(title,close,chart,select,values,wrap);show(person.rows.find(r=>r.date===this.data.business_date)?.date||person.rows.filter(r=>!r.is_future).at(-1)?.date);title.tabIndex=-1;title.focus();
  }
  async load(site){
    this.site=site;const sequence=++this.sequence,month=$('staff-month').value;
    // Do not leave another site's staff data visible while loading or on error.
    this.data=null;this.chart();$('staff-month-table').replaceChildren();$('staff-day-detail').hidden=true;$('staff-month-status').textContent='직원별 월간 실적을 불러오고 있습니다…';
    try{const params=new URLSearchParams();if(site)params.set('site_id',site);if(month)params.set('month',month);const data=await api('/api/dashboard/staff-performance?'+params,undefined,'GET',{'X-TM-Actor':document.body.dataset.userId});if(sequence!==this.sequence)return;
      this.data=data;$('staff-month').value=data.month;$('staff-month').max=data.business_date.slice(0,7);this.chart();
      const table=text('table','');table.className='table';const head=text('thead',''),header=text('tr',''),body=text('tbody','');for(const label of ['직원','통화 시도','연결된 통화','가망고객','실제 방문','세부 실적']){const th=text('th',label);th.scope='col';header.append(th);}head.append(header);
      for(const person of data.employees){const row=text('tr','');row.dataset.employeeId=person.id;row.append(text('th',person.name));for(const metric of ['call','connected','prospect','visit'])row.append(text('td',totalValue(person.totals[metric],metric==='call'||metric==='connected'?'콜':'명')));const action=text('td',''),button=text('button','일별 실적 보기');button.type='button';button.className='text-control';button.dataset.staffDetail=person.id;button.onclick=()=>this.details(person);action.append(button);row.append(action);body.append(row);}table.append(head,body);$('staff-month-table').append(table);
      $('staff-month-status').textContent=data.month+' · '+(data.employees.length?'직원 화면과 같은 기준으로 조회했습니다.':'표시할 직원이 없습니다.');
    }catch(error){if(sequence!==this.sequence)return;$('staff-month-status').textContent='직원별 실적을 불러오지 못했습니다. 다시 조회해 주세요.';}
  }
}
