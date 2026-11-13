import {choiceFilter} from './choice-filter.js';
import {setupDateInput,readDateInput} from './date-input.js';

const dates=new Set(['visit_at','callback_due_at','assigned_at']);
const textFields=new Set(['notes','memo','admin_notes','residence']);
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
let session=0;

export function markFilterHeaders(filters){
  for(const button of document.querySelectorAll('[data-filter-field]'))button.setAttribute('aria-pressed',String(Object.hasOwn(filters,button.dataset.filterField)));
}

export function columnFilterButton(field,label,open){
  const button=node('button');button.type='button';button.className='column-filter';button.dataset.filterField=field;
  button.setAttribute('aria-label',label+' 필터');button.setAttribute('aria-haspopup','dialog');button.setAttribute('aria-controls','filter-dialog');button.setAttribute('aria-pressed','false');
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg'),path=document.createElementNS(svg.namespaceURI,'path');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');
  path.setAttribute('d','M4 5h16l-6 7v6l-4 2v-8z');svg.append(path);button.append(svg);
  button.onclick=event=>{event.stopPropagation();open();};return button;
}

export function filterDescription(field,condition,display){
  if(condition===undefined)return '전체 보기';
  if(condition.blank!==undefined)return condition.blank?'미입력만':'입력된 항목만';
  if(condition.contains!==undefined)return '내용 포함: '+condition.contains.slice(0,30)+(condition.contains.length>30?'…':'');
  if(condition.from||condition.to){
    if(condition.from===condition.to)return condition.from;
    if(!condition.from)return condition.to+'까지';if(!condition.to)return condition.from+'부터';
    return `${condition.from} ~ ${condition.to}`;
  }
  const values=condition.values??condition;
  const label=value=>value==null||value===''||(field==='contract_status'&&value==='UNKNOWN')?'미입력':display(field,value);
  const caption=values.length<=2?values.map(label).join(', '):`${values.length}개 선택`;
  return (condition.exclude?'제외: ':'포함: ')+(caption||'선택 없음');
}

export function renderFilterChips(area,filters,labels,display,remove){
  const entries=Object.entries(filters);area.replaceChildren();
  if(!entries.length)return;
  area.append(node('span',`적용 중 ${entries.length}개`,'filter-active-label'));
  for(const [field,condition] of entries){
    const caption=labels[field]+': '+filterDescription(field,condition,display),button=node('button',undefined,'filter-chip');button.type='button';
    button.setAttribute('aria-label',caption+' 필터 해제');button.append(node('span',caption));const close=node('span','×');close.setAttribute('aria-hidden','true');button.append(close);button.onclick=()=>remove(field);area.append(button);
  }
}

function modeControl(area,current,changed){
  const group=node('fieldset',undefined,'filter-mode');group.id='filter-mode';group.append(node('legend','조회 조건'));
  let value=current?.blank!==undefined?(current.blank?'EMPTY':'FILLED'):'MATCH';
  for(const [code,title] of [['ALL','전체 보기'],['MATCH','조건 지정'],['EMPTY','미입력만'],['FILLED','입력된 항목만']]){
    const label=node('label'),input=node('input');input.type='radio';input.name='filter-mode';input.value=code;input.checked=value===code;
    input.onchange=()=>{value=code;changed();};label.append(input,node('span',title));group.append(label);
  }
  area.append(group);return {get value(){return value;}};
}

export async function openGridFilter({field,label,schema,current,request,params,display,apply}){
  const $=id=>document.getElementById(id),dialog=$('filter-dialog'),area=$('filter-content'),error=$('filter-error');
  const applyButton=$('filter-apply'),reset=$('filter-reset'),cancel=dialog.querySelector('[data-close]');
  const token=++session;let applying=false,read=()=>undefined,hasValue=()=>false,mode,panel;
  const alive=()=>session===token&&dialog.open;
  const condition=()=>mode.value==='ALL'?undefined:mode.value==='EMPTY'?{blank:true}:mode.value==='FILLED'?{blank:false}:read();
  const refresh=()=>{
    if(!alive()||!mode)return;
    panel.hidden=mode.value!=='MATCH';
    applyButton.disabled=applying||(mode.value==='MATCH'&&!hasValue());
    try{$('filter-summary').textContent=filterDescription(field,condition(),display);}catch(problem){$('filter-summary').textContent=problem.message;}
  };
  const changed=()=>{error.textContent='';refresh();};
  const safeRequest=async url=>{
    let timer;
    try{return await Promise.race([request(url),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('값 목록을 불러오는 데 시간이 걸립니다.')),10000);})]);}
    finally{clearTimeout(timer);}
  };
  const submit=async value=>{
    if(applying||!alive())return;
    try{
      const selected=typeof value==='function'?value():value;
      if(selected?.values?.length>1000)throw new Error('한 필터에서 최대 1,000개 값을 선택할 수 있습니다.');
      applying=true;applyButton.disabled=reset.disabled=cancel.disabled=true;error.textContent='';
      area.inert=true;
      await apply(selected);if(alive())dialog.close();
    }catch(problem){if(alive())error.textContent=problem.message;}
    finally{
      applying=false;if(alive()){area.inert=false;reset.disabled=cancel.disabled=false;refresh();}
    }
  };
  $('filter-title').textContent=label+' 필터';$('filter-help').textContent='여러 필터를 적용하면 모든 조건에 맞는 고객만 표시합니다.';
  error.textContent='';$('filter-summary').textContent='';area.replaceChildren();area.inert=false;applyButton.disabled=true;reset.disabled=cancel.disabled=false;
  reset.onclick=()=>submit(undefined);applyButton.onclick=()=>submit(condition);
  dialog.oncancel=event=>{if(applying)event.preventDefault();};
  dialog.onclose=()=>{if(!dialog.open&&session===token)session++;};
  dialog.onkeydown=event=>{if(event.key==='Enter'&&event.target.matches('#filter-contains,#filter-from,#filter-to')){event.preventDefault();submit(condition);}};
  dialog.showModal();
  mode=modeControl(area,current,changed);panel=node('section',undefined,'filter-condition');area.append(panel);
  if(dates.has(field)){
    const quick=node('div',undefined,'filter-quick-dates'),fields={},group=node('div',undefined,'filter-date-range');
    for(const [key,title] of [['from','시작일'],['to','종료일']]){
      const label=node('label',title,'filter-input-label'),input=setupDateInput(node('input'));input.id='filter-'+key;input.className='form-control';input.value=current?.[key]||'';input.oninput=changed;label.htmlFor=input.id;label.append(input);group.append(label);fields[key]=input;
    }
    for(const [code,title] of [['today','오늘'],['week','최근 7일'],['month','이번 달']]){
      const button=node('button',title,'filter-quick-button');button.type='button';
      button.onclick=()=>{
        const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),end=new Date(day+'T00:00:00Z'),start=new Date(end);
        if(code==='week')start.setUTCDate(start.getUTCDate()-6);if(code==='month'){start.setUTCDate(1);end.setUTCMonth(end.getUTCMonth()+1,0);}
        fields.from.value=start.toISOString().slice(0,10);fields.to.value=end.toISOString().slice(0,10);changed();
      };quick.append(button);
    }
    panel.append(node('h3','기간 선택'),quick,group,node('p','날짜 숫자 8자리 → YYYY-MM-dd · 종료일까지 포함합니다. 한쪽만 입력해도 됩니다.','filter-input-help'));
    hasValue=()=>!!(fields.from.value||fields.to.value);
    read=()=>{
      const from=readDateInput(fields.from.value),to=readDateInput(fields.to.value);
      if(!from&&!to)throw new Error('날짜를 입력하거나 빠른 기간을 선택해 주세요.');
      if(from&&to&&from>to)throw new Error('종료일은 시작일과 같거나 이후여야 합니다.');
      return {...(from?{from}:{}),...(to?{to}:{})};
    };
  }else if(textFields.has(field)){
    const label=node('label','포함할 내용','filter-input-label'),input=node('input');input.id='filter-contains';input.className='form-control';input.maxLength=10000;input.placeholder=label.textContent+'을 입력하세요';input.value=current?.contains||'';input.oninput=changed;label.htmlFor=input.id;label.append(input);panel.append(label,node('p','입력한 글자가 포함된 고객을 찾습니다.','filter-input-help'));
    hasValue=()=>!!input.value.trim();read=()=>{if(!hasValue())throw new Error('찾을 내용을 입력해 주세요.');return {contains:input.value};};
  }else{
    const choices=choiceFilter({area:panel,field,schema,current,request:safeRequest,params,display,onChange:changed,isCurrent:alive});
    read=choices.read;hasValue=choices.hasValue;
  }
  refresh();area.querySelector('input:checked')?.focus();
}
