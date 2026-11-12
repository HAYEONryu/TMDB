import {choiceFilter} from './choice-filter.js';
import {setupDateInput,readDateInput} from './date-input.js';

const dates=new Set(['visit_at','callback_due_at','assigned_at']);
const textFields=new Set(['notes','memo','admin_notes','residence']);
const node=(tag,text)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;return n;};
let session=0;

export function markFilterHeaders(filters){
  for(const button of document.querySelectorAll('[data-filter-field]'))button.setAttribute('aria-pressed',String(Object.hasOwn(filters,button.dataset.filterField)));
}

export function filterDescription(field,condition,display){
  if(condition===undefined)return '전체';
  if(condition.blank!==undefined)return condition.blank?'- 값이 없는 항목':'값이 있는 항목';
  if(condition.contains!==undefined)return '포함: '+condition.contains.slice(0,30)+(condition.contains.length>30?'…':'');
  if(condition.from||condition.to)return `${condition.from||'시작 제한 없음'} ~ ${condition.to||'종료 제한 없음'}`;
  const values=condition.values??condition;
  return `${condition.exclude?'제외: ':''}${values.length===1?display(field,values[0]):values.length+'개 값'+(!values.length&&!condition.exclude?' · 결과 없음':'')}`;
}

function modeControl(area,current,matchLabel='조건 검색'){
  const label=node('label','조회 조건'),select=node('select');label.htmlFor='filter-mode';select.id='filter-mode';select.className='form-select';
  for(const [code,title] of [['MATCH',matchLabel],['ALL','전체'],['EMPTY','- 값이 없는 항목'],['FILLED','값이 있는 항목']])select.add(new Option(title,code));
  select.value=current?.blank!==undefined?(current.blank?'EMPTY':'FILLED'):'MATCH';area.append(label,select);return select;
}

export async function openGridFilter({field,label,schema,current,request,params,display,apply}){
  const dialog=document.querySelector('#filter-dialog'),area=document.querySelector('#filter-content'),error=document.querySelector('#filter-error');
  const applyButton=document.querySelector('#filter-apply'),reset=document.querySelector('#filter-reset'),cancel=dialog.querySelector('[data-close]');
  const token=++session;let getCondition=()=>current,applying=false,ready=true;
  const alive=()=>session===token&&dialog.open;
  const refresh=()=>{if(alive()){try{document.querySelector('#filter-summary').textContent=filterDescription(field,getCondition(),display);}catch{document.querySelector('#filter-summary').textContent='조건을 확인해 주세요.';}}};
  const safeRequest=async url=>{
    let timer;
    try{return await Promise.race([request(url),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('후보값 조회가 지연됩니다. 다시 확인해 주세요.')),10000);})]);}
    finally{clearTimeout(timer);}
  };
  document.querySelector('#filter-title').textContent=label+' 필터';error.textContent='';area.replaceChildren(node('p','필터를 준비하고 있습니다…'));
  document.querySelector('#filter-help').textContent=dates.has(field)?'날짜는 숫자 8자리로 입력하세요. (예: 20261113 → 2026-11-13) 한국 시간 기준이며 종료일까지 포함합니다.':'다른 열의 조건과 함께 적용됩니다. -는 값이 없는 항목입니다.';
  document.querySelector('#filter-summary').textContent='';applyButton.disabled=true;reset.disabled=false;cancel.disabled=false;
  const submit=async value=>{
    if(applying||!alive())return;
    try{
      const condition=typeof value==='function'?value():value;
      if(condition?.values?.length>1000)throw new Error('한 열은 최대 1,000개 값을 선택하거나 제외할 수 있습니다.');
      applying=true;applyButton.disabled=reset.disabled=cancel.disabled=true;error.textContent='';
      await apply(condition);if(alive())dialog.close();
    }catch(problem){if(alive())error.textContent=problem.message;}
    finally{applying=false;if(alive()){applyButton.disabled=reset.disabled=cancel.disabled=false;}}
  };
  reset.onclick=()=>submit(undefined);applyButton.onclick=()=>submit(getCondition);
  dialog.oncancel=event=>{if(applying)event.preventDefault();};
  dialog.onclose=()=>{if(!dialog.open&&session===token)session++;};
  dialog.onkeydown=event=>{if(event.key==='Enter'&&event.target.matches('#filter-contains,#filter-from,#filter-to')){event.preventDefault();submit(getCondition);}};
  dialog.showModal();area.replaceChildren();
  try{
    if(schema[field])getCondition=await choiceFilter({area,field,schema,current,request:safeRequest,params,display,onChange:refresh,isCurrent:alive});
    else if(dates.has(field)){
      const mode=modeControl(area,current,'날짜 범위'),group=node('div');group.className='filter-date-range';
      const fields={};
      for(const [key,title] of [['from','시작일'],['to','종료일']]){
        const lab=node('label',title),input=setupDateInput(node('input'));input.id='filter-'+key;input.className='form-control';input.value=current?.[key]||'';lab.htmlFor=input.id;lab.append(input);group.append(lab);fields[key]=input;input.oninput=()=>{error.textContent='';refresh();};
      }
      const quick=node('div');quick.className='filter-quick-dates';
      for(const [code,title] of [['today','오늘'],['week','최근 7일'],['month','이번 달']]){
        const button=node('button',title);button.type='button';button.className='btn btn-sm btn-outline-secondary';
        button.onclick=()=>{const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()),end=new Date(day+'T00:00:00Z'),start=new Date(end);if(code==='week')start.setUTCDate(start.getUTCDate()-6);if(code==='month'){start.setUTCDate(1);end.setUTCMonth(end.getUTCMonth()+1,0);}fields.from.value=start.toISOString().slice(0,10);fields.to.value=end.toISOString().slice(0,10);mode.value='MATCH';mode.onchange();};quick.append(button);
      }
      area.append(group,quick);mode.onchange=()=>{for(const input of Object.values(fields))input.disabled=mode.value!=='MATCH';quick.hidden=mode.value!=='MATCH';refresh();};
      getCondition=()=>{
        if(mode.value==='ALL')return undefined;if(mode.value!=='MATCH')return {blank:mode.value==='EMPTY'};
        const from=readDateInput(fields.from.value),to=readDateInput(fields.to.value);
        if(from&&to&&from>to)throw new Error('종료일은 시작일과 같거나 이후여야 합니다.');
        const value={};if(from)value.from=from;if(to)value.to=to;return Object.keys(value).length?value:undefined;
      };mode.onchange();
    }else if(textFields.has(field)){
      const mode=modeControl(area,current,'내용 포함'),lab=node('label','포함할 내용'),input=node('input');input.id='filter-contains';input.className='form-control';input.maxLength=10000;input.placeholder='찾을 내용을 입력하세요';input.value=current?.contains||'';lab.htmlFor=input.id;lab.append(input);area.append(lab);
      getCondition=()=>mode.value==='ALL'?undefined:mode.value==='MATCH'?(input.value?{contains:input.value}:undefined):{blank:mode.value==='EMPTY'};
      mode.onchange=()=>{input.disabled=mode.value!=='MATCH';refresh();};input.oninput=refresh;mode.onchange();
    }else{
      const lab=node('label','값 선택 방식'),mode=node('select');lab.htmlFor='filter-list-mode';mode.id='filter-list-mode';mode.className='form-select';
      for(const [code,title] of [['ALL','전체'],['INCLUDE','선택한 값만'],['EXCLUDE','선택한 값 제외'],['EMPTY','- 값이 없는 항목'],['FILLED','값이 있는 항목']])mode.add(new Option(title,code));
      mode.value=current?.blank!==undefined?(current.blank?'EMPTY':'FILLED'):current?(current.exclude?'EXCLUDE':'INCLUDE'):'ALL';
      const selected=new Set((current?.values??(Array.isArray(current)?current:[])).map(value=>value??''));
      const panel=node('div'),searchLabel=node('label','후보값 검색'),search=node('input'),searchButton=node('button','후보 검색'),list=node('div'),info=node('p'),nav=node('div');
      search.id='filter-option-search';search.type='search';search.maxLength=200;search.className='form-control';searchLabel.htmlFor=search.id;searchLabel.append(search);list.id='filter-options';list.setAttribute('aria-label','필터 후보값');info.setAttribute('role','status');nav.className='filter-candidate-nav';
      const selectPage=node('button','이 페이지 선택'),clearPage=node('button','이 페이지 해제'),previous=node('button','이전 후보'),next=node('button','다음 후보');
      for(const button of [searchButton,selectPage,clearPage,previous,next]){button.type='button';button.className='btn btn-sm btn-outline-secondary';}
      const pageActions=node('div');pageActions.className='filter-page-actions';pageActions.append(selectPage,clearPage);nav.append(previous,next);panel.append(searchLabel,searchButton,pageActions,list,info,nav);area.append(lab,mode,panel);
      let page=1,term='',generation=0,visible=[],loading=false;
      const update=()=>{panel.hidden=['EMPTY','FILLED'].includes(mode.value);list.querySelectorAll('input').forEach(input=>{input.checked=selected.has(input.value);});refresh();};
      mode.onchange=()=>{if(mode.value==='ALL')selected.clear();update();};
      getCondition=()=>mode.value==='ALL'?undefined:['EMPTY','FILLED'].includes(mode.value)?{blank:mode.value==='EMPTY'}:{values:[...selected],exclude:mode.value==='EXCLUDE'};
      const choose=()=>{if(mode.value==='ALL')mode.value='INCLUDE';};
      selectPage.onclick=()=>{choose();visible.forEach(value=>selected.add(value));update();};clearPage.onclick=()=>{choose();visible.forEach(value=>selected.delete(value));update();};
      const draw=async()=>{
        const sequence=++generation;loading=true;searchButton.disabled=previous.disabled=next.disabled=selectPage.disabled=clearPage.disabled=true;applyButton.disabled=true;info.textContent='후보값 조회 중…';error.textContent='';
        try{
          const query=params();query.set('field',field);query.set('option_q',term);query.set('option_page',page);
          const data=await safeRequest('/api/customers/filter-options?'+query);if(!alive()||sequence!==generation)return;
          visible=data.values.map(value=>value??'');list.replaceChildren(...visible.map(value=>{const label=node('label'),check=node('input');check.type='checkbox';check.value=value;check.checked=selected.has(value);check.onchange=()=>{choose();if(check.checked)selected.add(value);else selected.delete(value);update();};label.append(check,node('span',display(field,value)));return label;}));
          if(!visible.length)list.append(node('p','일치하는 후보값이 없습니다. 검색어나 다른 열의 조건을 확인하세요.'));
          info.textContent=`후보 ${data.total}개 · ${page} / ${Math.max(1,Math.ceil(data.total/100))}페이지 · 선택은 페이지를 이동해도 유지됩니다.`;
          previous.disabled=page<=1;next.disabled=!data.has_next;ready=true;applyButton.disabled=false;
        }catch(problem){if(alive()&&sequence===generation){ready=false;error.textContent=problem.message;info.textContent='후보값을 불러오지 못했습니다. 후보 검색으로 다시 확인하세요.';}}
        finally{if(alive()&&sequence===generation){loading=false;searchButton.disabled=selectPage.disabled=clearPage.disabled=false;}}
      };
      searchButton.onclick=()=>{if(loading)return;term=search.value;page=1;draw();};search.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();searchButton.click();}};previous.onclick=()=>{page--;draw();};next.onclick=()=>{page++;draw();};
      update();await draw();
    }
    if(alive()){applyButton.disabled=!ready;refresh();area.querySelector('select,input')?.focus();}
  }catch(problem){if(alive()){error.textContent=problem.message;area.append(node('p','이 열 해제로 조건을 제거하거나 취소 후 다시 열어 주세요.'));}}
}
