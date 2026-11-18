const text=(tag,value,cls)=>{const el=document.createElement(tag);el.textContent=value??'';if(cls)el.className=cls;return el;};
export const metricValue=(value,unit='')=>value==null?'집계 자료 없음':new Intl.NumberFormat('ko-KR').format(value)+unit;
export function totalValue(item,unit){return metricValue(item?.count,unit)+(item?.status==='partial'?' · 일부 기간':'');}
export function dailyChart(target,data,onSelect){
  target.replaceChildren();
  const values=data.rows.filter(r=>!r.is_future),max=Math.max(1,...values.map(r=>r.call_count||0));
  const chart=text('div','','daily-bar-chart');chart.style.setProperty('--days',data.rows.length);
  for(const row of data.rows){
    const slot=text('div','','day-bar-slot'),bar=text('button','','day-bar');bar.type='button';bar.dataset.date=row.date;
    const missing=row.call_count===null,day=Number(row.date.slice(8));bar.disabled=row.is_future;
    bar.style.setProperty('--amount',row.is_future||missing?'0%':Math.max(2,row.call_count/max*100)+'%');
    bar.classList.toggle('no-data',missing);bar.classList.toggle('zero',row.call_count===0);
    const description=row.is_future?'미래 날짜':metricValue(row.call_count,'콜');bar.title=row.date+' · '+description;
    bar.setAttribute('aria-label',bar.title);bar.setAttribute('aria-pressed','false');bar.append(text('span',missing?'—':row.call_count,'bar-number'));
    bar.onclick=()=>onSelect(row.date);slot.append(bar,text('span',day===1||day%5===0||day===data.rows.length?day+'일':'','bar-day'));chart.append(slot);
  }
  target.append(text('h3','일별 콜 수'),chart);
}
export function dailyValues(target,row){
  target.replaceChildren();if(!row)return;
  target.append(text('strong',row.date));
  for(const [key,label,unit] of [['call','콜 수','콜'],['prospect','가망고객','명'],['visit','실제 방문','명']])target.append(text('span',label+' '+(row.is_future?'—':metricValue(row[key+'_count'],unit))));
}
