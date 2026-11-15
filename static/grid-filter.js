import {choiceFilter} from './choice-filter.js';
import {setupDateInput,readDateInput} from './date-input.js';

const dates=new Set(['visit_at','callback_due_at','assigned_at']);
const textFields=new Set(['notes','memo','admin_notes','residence']);
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
const empty=(field,value)=>value==null||value===''||(field==='contract_status'&&value==='UNKNOWN');
let session=0;

export function filterDescription(field,condition,display){
  if(condition===undefined)return '전체';
  if(condition.preset)return condition.preset==='today'?'오늘':'기한 지남';
  if(condition.blank!==undefined)return condition.blank?'미입력':'입력된 항목';
  if(condition.contains!==undefined)return '내용 포함: '+condition.contains.slice(0,30)+(condition.contains.length>30?'…':'');
  if(condition.from||condition.to){
    if(condition.from===condition.to)return condition.from;
    return !condition.from?condition.to+'까지':!condition.to?condition.from+'부터':`${condition.from} ~ ${condition.to}`;
  }
  if(dates.has(field))return '기간 지정 필요';
  const values=condition.values??condition;
  const caption=values.length<=2?values.map(value=>empty(field,value)?'미입력':display(field,value)).join(', '):`${values.length}개 선택`;
  return (condition.exclude?'제외: ':'정확 일치: ')+(caption||'값 선택 필요');
}

export function renderFilterChips(area,filters,labels,display,remove,{q='',assignee='',category=''}={}){
  area.replaceChildren();
  const categories={held:'현재 담당',new_today:'오늘 배정 유지',overdue:'기한 지난 재콜',callbacks_remaining:'오늘 남은 재콜',callbacks_today:'오늘 예정 재콜',visits:'오늘 방문예약',unprogressed:'미진행',contracted:'내 담당 계약'};
  const entries=[...(q?[['_search',{caption:'검색 · '+q}]]:[]),...Object.entries(filters),...(assignee?[['_assignee',{caption:'담당직원 유입 조건'}]]:[]),...(category?[['_category',{caption:'대시보드 · '+(categories[category]||category)}]]:[])];
  if(entries.length)area.append(node('span','적용 중','filter-active-label'));
  for(const [field,condition] of entries){
    const caption=condition.caption??labels[field]+' · '+filterDescription(field,condition,display),button=node('button',undefined,'filter-chip');button.type='button';
    button.setAttribute('aria-label',caption+' 조건 제거');button.append(node('span',caption));const close=node('span','×');close.setAttribute('aria-hidden','true');button.append(close);button.onclick=()=>remove(field);area.append(button);
  }
}

function modeTitle(condition){
  return condition===undefined?'전체':condition.preset?'빠른 기간':condition.blank!==undefined?(condition.blank?'미입력':'입력된 항목'):condition.exclude?'선택한 값 제외':condition.values||Array.isArray(condition)?'정확 일치':condition.contains!==undefined?'내용 포함':'기간 지정';
}

// All controls edit one draft. Only the final Apply callback changes the list.
export function openGridFilter({fields,labels,schema,current,request,params,display,apply}){
  const $=id=>document.getElementById(id),dialog=$('filter-dialog'),area=$('filter-content'),error=$('filter-error'),trigger=$('open-filters');
  const token=++session,draft=structuredClone(current),basics=new Map();let applying=false,advancedField='',refreshAdvanced=()=>{},advancedOpen=false;
  const alive=()=>session===token&&dialog.open;
  const describe=field=>filterDescription(field,draft[field],display);
  const summary=()=>{
    $('filter-summary').textContent=`적용할 상세 조건 ${Object.keys(draft).length}개`+Object.entries(draft).map(([field,c])=>` · ${labels[field]}: ${filterDescription(field,c,display)}`).join('');
    if(!applying)$('filter-apply').disabled=Object.values(draft).some(c=>c.values&&(!c.values.length||c.values.length>1000));
  };
  const set=(field,value,{advanced=false}={})=>{
    if(value===undefined)delete draft[field];else draft[field]=value;
    error.textContent='';basics.get(field)?.();summary();
    if(!advanced&&advancedOpen&&advancedField===field)refreshAdvanced();
  };
  const option=(value,label)=>new Option(label,value);
  const section=field=>{const wrap=node('section',undefined,'filter-primary-section');wrap.dataset.field=field;const heading=node('div',undefined,'filter-field-heading'),badge=node('span',undefined,'filter-mode-badge');
    heading.append(node('h3',labels[field]),badge);wrap.append(heading);area.append(wrap);return {wrap,badge};};
  const range=(field,wrap)=>{
    const group=node('div',undefined,'filter-date-range'),inputs={};
    for(const [key,title] of [['from','시작일'],['to','종료일']]){const label=node('label',`${labels[field]} ${title}`,'filter-input-label'),input=setupDateInput(node('input'));input.id=`basic-${field}-${key}`;input.className='form-control';label.htmlFor=input.id;label.append(input);group.append(label);inputs[key]=input;
      input.oninput=()=>set(field,{...(draft[field]?.from!==undefined?{from:draft[field].from}:{}),...(draft[field]?.to!==undefined?{to:draft[field].to}:{}),[key]:input.value});}
    wrap.append(group);return ()=>{const c=draft[field],visible=c!==undefined&&c.blank===undefined&&!c.preset;group.hidden=!visible;for(const key of ['from','to'])if(document.activeElement!==inputs[key])inputs[key].value=c?.[key]||'';};
  };
  area.replaceChildren();error.textContent='';area.inert=false;
  $('filter-apply').disabled=$('filter-reset').disabled=$('filter-close').disabled=false;
  dialog.querySelector('[data-close]').disabled=false;

  const call=section('call_result'),buttons=new Map(),choices=Object.entries(schema.call_result).map(([value,label])=>[empty('call_result',value)?'':value,empty('call_result',value)?'미입력':label]);
  const main=node('div',undefined,'filter-toggle-list'),more=node('details'),moreList=node('div',undefined,'filter-toggle-list');more.append(node('summary','다른 통화결과 보기'),moreList);call.wrap.append(main,more,node('p','통화결과는 여러 개를 선택할 수 있습니다.','filter-input-help'));
  const priority=value=>{const index=['NO_ANSWER','INTERESTED',''].indexOf(value);return index<0?3:index;};
  choices.sort(([a],[b])=>priority(a)-priority(b));
  for(const [value,label] of choices){const button=node('button',label,'filter-toggle');button.type='button';button.dataset.value=value;
    button.onclick=()=>{const c=draft.call_result,values=new Set(c?.blank===true?['']:(c?.values??(Array.isArray(c)?c:[])));values.has(value)?values.delete(value):values.add(value);set('call_result',values.size?{values:[...values],exclude:!!c?.exclude}:undefined);};
    buttons.set(value,button);(['NO_ANSWER','INTERESTED',''].includes(value)?main:moreList).append(button);}
  basics.set('call_result',()=>{const c=draft.call_result,values=c?.blank===true?['']:(c?.values??(Array.isArray(c)?c:[]));call.badge.textContent=modeTitle(c);for(const [value,button] of buttons)button.setAttribute('aria-pressed',String(values.includes(value)));});

  for(const field of ['callback_due_at','visit_at']){
    const {wrap,badge}=section(field),select=node('select',undefined,'form-select');select.id='basic-'+field;select.setAttribute('aria-label',labels[field]+' 빠른 조건');
    select.append(...[['all','전체'],['today','오늘'],...(field==='callback_due_at'?[['overdue','기한 지남']]:[]),['range','기간 지정'],['empty','미입력'],['filled','입력된 항목']].map(([v,t])=>option(v,t)));
    const custom=option('custom','추가 조건에서 지정');custom.disabled=true;select.append(custom);wrap.append(select);const syncRange=range(field,wrap);
    select.onchange=()=>{const v=select.value,day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
      set(field,v==='all'?undefined:v==='empty'?{blank:true}:v==='filled'?{blank:false}:v==='range'?{from:'',to:''}:field==='callback_due_at'?{preset:v}:{from:day,to:day});};
    basics.set(field,()=>{const c=draft[field];badge.textContent=modeTitle(c);select.value=c===undefined?'all':c.blank!==undefined?(c.blank?'empty':'filled'):c.preset||'range';syncRange();});
    if(field==='callback_due_at')wrap.append(node('p','오늘과 기한 지남은 미완료 재콜을 서버의 현재 시각으로 계산하며, 서로 겹칠 수 있습니다.','filter-input-help'));
  }
  const contract=section('contract_status'),contractSelect=node('select',undefined,'form-select');contractSelect.id='basic-contract_status';contractSelect.setAttribute('aria-label','계약여부 빠른 조건');
  contractSelect.append(option('all','전체'),...Object.entries(schema.contract_status).map(([v,t])=>option(v,empty('contract_status',v)?'미입력':t)),option('filled','입력된 항목'));
  const custom=option('custom','추가 조건에서 지정');custom.disabled=true;contractSelect.append(custom);contract.wrap.append(contractSelect);
  contractSelect.onchange=()=>{const v=contractSelect.value;set('contract_status',v==='all'?undefined:v==='UNKNOWN'?{blank:true}:v==='filled'?{blank:false}:{values:[v],exclude:false});};
  basics.set('contract_status',()=>{const c=draft.contract_status;contract.badge.textContent=modeTitle(c);contractSelect.value=c===undefined?'all':c.blank!==undefined?(c.blank?'UNKNOWN':'filled'):!c.exclude&&c.values?.length===1?c.values[0]:'custom';});

  const extra=node('details',undefined,'filter-extra');extra.id='filter-extra';extra.append(node('summary','추가 조건'));
  const selectLabel=node('label','조건 항목','filter-input-label'),fieldSelect=node('select',undefined,'form-select');fieldSelect.id='filter-field';selectLabel.htmlFor=fieldSelect.id;fieldSelect.append(option('','편집할 조건을 선택하세요'),...fields.map(f=>option(f,labels[f])));selectLabel.append(fieldSelect);
  const currentMode=node('p',undefined,'filter-input-help'),editor=node('div');editor.id='filter-editor';extra.append(node('p','정확 일치·제외·미입력과 나머지 조건을 편집합니다. 위의 빠른 조건과 같은 값을 사용합니다.','filter-input-help'),selectLabel,currentMode,editor);area.append(extra);
  if(fields.includes('assignee_name')){const staff=section('assignee_name'),button=node('button',undefined,'btn btn-outline-secondary');button.type='button';staff.wrap.append(button);extra.before(staff.wrap);
    button.onclick=()=>{extra.open=true;advancedField='assignee_name';fieldSelect.value=advancedField;refreshAdvanced();fieldSelect.focus();};
    basics.set('assignee_name',()=>{staff.badge.textContent=modeTitle(draft.assignee_name);button.textContent=describe('assignee_name')+' · 담당직원 선택';});}
  const safeRequest=async url=>{let timer;try{return await Promise.race([request(url),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('값 목록을 불러오는 데 시간이 걸립니다.')),10000);})]);}finally{clearTimeout(timer);}};
  let editorGeneration=0;
  refreshAdvanced=()=>{
    const generation=++editorGeneration,field=advancedField,c=draft[field];let ready=false,choice,read;
    editor.dataset.field=field;if(!field){editor.replaceChildren();currentMode.textContent='';return;}
    editor.replaceChildren();currentMode.textContent=`${labels[field]} · 현재 모드: ${modeTitle(c)}`;
    const mode=node('fieldset',undefined,'filter-mode');mode.id='filter-mode';mode.append(node('legend','조회 조건'));let selected=c===undefined?'ALL':c.blank!==undefined?(c.blank?'EMPTY':'FILLED'):'MATCH';
    const panel=node('section',undefined,'filter-condition');
    const changed=()=>{if(!ready)return;const value=selected==='ALL'?undefined:selected==='EMPTY'?{blank:true}:selected==='FILLED'?{blank:false}:read();set(field,value,{advanced:true});currentMode.textContent=`${labels[field]} · 현재 모드: ${modeTitle(value)}`;panel.hidden=selected!=='MATCH';};
    for(const [code,title] of [['ALL','전체 보기'],['MATCH','조건 지정'],['EMPTY','미입력만'],['FILLED','입력된 항목만']]){const label=node('label'),input=node('input');input.type='radio';input.name='filter-mode';input.value=code;input.checked=selected===code;input.onchange=()=>{selected=code;changed();};label.append(input,node('span',title));mode.append(label);}
    editor.append(mode,panel);panel.hidden=selected!=='MATCH';
    if(dates.has(field)){
      const group=node('div',undefined,'filter-date-range'),inputs={};
      for(const [key,title] of [['from','시작일'],['to','종료일']]){const label=node('label',title,'filter-input-label'),input=setupDateInput(node('input'));input.id='filter-'+key;input.className='form-control';input.value=c?.[key]||'';input.oninput=changed;label.htmlFor=input.id;label.append(input);group.append(label);inputs[key]=input;}
      const quick=node('div',undefined,'filter-quick-dates');
      for(const [code,title] of [['today','오늘'],['week','최근 7일'],['month','이번 달']]){const button=node('button',title,'filter-quick-button');button.type='button';button.onclick=()=>{
        if(field==='callback_due_at'&&code==='today'){set(field,{preset:'today'},{advanced:true});refreshAdvanced();return;}
        const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),end=new Date(day+'T00:00:00Z'),start=new Date(end);
        if(code==='week')start.setUTCDate(start.getUTCDate()-6);if(code==='month'){start.setUTCDate(1);end.setUTCMonth(end.getUTCMonth()+1,0);}
        inputs.from.value=start.toISOString().slice(0,10);inputs.to.value=end.toISOString().slice(0,10);changed();
      };quick.append(button);}
      panel.append(quick,group);read=()=>({...(inputs.from.value?{from:inputs.from.value}:{}),...(inputs.to.value?{to:inputs.to.value}:{})});
      if(c?.preset){const note=node('p',`빠른 조건: ${describe(field)}. 날짜를 입력하면 기간 지정으로 바뀝니다.`,'filter-input-help');panel.prepend(note);}
    }else if(textFields.has(field)){
      const label=node('label','포함할 내용','filter-input-label'),input=node('input');input.id='filter-contains';input.className='form-control';input.maxLength=10000;input.value=c?.contains||'';input.oninput=changed;label.htmlFor=input.id;label.append(input);panel.append(label);read=()=>({contains:input.value});
    }else{
      choice=choiceFilter({area:panel,field,schema,current:c,request:safeRequest,params,display,onChange:changed,isCurrent:()=>alive()&&generation===editorGeneration});
      read=()=>choice.read({allowEmpty:true});
    }
    ready=true;
  };
  fieldSelect.onchange=()=>{advancedField=fieldSelect.value;refreshAdvanced();};
  extra.ontoggle=()=>{advancedOpen=extra.open;if(advancedOpen){if(editor.dataset.field!==advancedField)refreshAdvanced();}else{editorGeneration++;editor.dataset.field='';}};
  const close=()=>{if(!applying)dialog.close();};$('filter-close').onclick=close;dialog.querySelector('[data-close]').onclick=close;
  $('filter-reset').onclick=()=>{for(const key of Object.keys(draft))delete draft[key];for(const sync of basics.values())sync();if(extra.open)refreshAdvanced();summary();error.textContent='';};
  $('filter-apply').onclick=async()=>{
    if(applying)return;
    try{
      const validated=structuredClone(draft);
      for(const [field,c] of Object.entries(validated)){
        if(c.values&&(!c.values.length||c.values.length>1000))throw new Error(labels[field]+': 값을 1개 이상, 최대 1,000개 선택해 주세요.');
        if(c.contains!==undefined&&!c.contains.trim())throw new Error(labels[field]+': 찾을 내용을 입력해 주세요.');
        if(dates.has(field)&&c.blank===undefined&&!c.preset){const from=readDateInput(c.from||''),to=readDateInput(c.to||'');if(!from&&!to)throw new Error(labels[field]+': 날짜를 입력해 주세요.');if(from&&to&&from>to)throw new Error('종료일은 시작일과 같거나 이후여야 합니다.');validated[field]={...(from?{from}:{}),...(to?{to}:{})};}
      }
      applying=true;area.inert=true;for(const id of ['filter-apply','filter-reset','filter-close'])$(id).disabled=true;dialog.querySelector('[data-close]').disabled=true;error.textContent='';
      const applied=await apply(validated);if(alive()){if(applied!==false)dialog.close();else error.textContent='필터 적용을 취소했습니다. 조건을 계속 편집할 수 있습니다.';}
    }catch(problem){if(alive())error.textContent=problem.message;}
    finally{applying=false;if(alive()){area.inert=false;for(const id of ['filter-apply','filter-reset','filter-close'])$(id).disabled=false;dialog.querySelector('[data-close]').disabled=false;}}
  };
  dialog.oncancel=event=>{if(applying)event.preventDefault();};
  dialog.onclose=()=>{if(session===token){session++;editorGeneration++;trigger.focus();}};
  dialog.onkeydown=null;
  for(const sync of basics.values())sync();summary();dialog.showModal();$('filter-close').focus();
}
