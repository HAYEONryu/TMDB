// One searchable multi-select for both business choices and customer values.
const node=(tag,text,cls)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(cls)el.className=cls;return el;};
export function choiceFilter({area,field,schema,current,request,params,display,onChange,isCurrent}){
  const empty=value=>value==null||value===''||(field==='contract_status'&&value==='UNKNOWN');
  const key=value=>empty(value)?'':String(value),title=value=>empty(value)?'미입력':display(field,value);
  const selected=new Set((current?.values??(Array.isArray(current)?current:[])).map(key));
  let exclude=!!current?.exclude,term='',page=1,hasNext=false,total=0,loading=false,generation=0,failed=false,changed=false;
  const base=new Map(),loaded=new Map();
  if(schema[field]){
    base.set('','미입력');
    for(const [value,label] of Object.entries(schema[field]))if(!empty(value))base.set(key(value),label);
  }
  const operator=node('fieldset',undefined,'filter-operator');operator.append(node('legend','선택한 값 처리','visually-hidden'));
  for(const [value,label] of [['include','선택한 값만 보기'],['exclude','선택한 값 제외']]){
    const wrap=node('label'),radio=node('input');radio.type='radio';radio.name='filter-operator';radio.value=value;radio.checked=exclude===(value==='exclude');
    radio.onchange=()=>{exclude=value==='exclude';changed=true;onChange();};wrap.append(radio,node('span',label));operator.append(wrap);
  }
  const searchLabel=node('label','값 검색','visually-hidden'),searchGroup=node('div',undefined,'filter-search'),search=node('input'),searchButton=node('button','검색','btn btn-outline-secondary');
  search.id='filter-option-search';search.type='search';search.maxLength=200;search.className='form-control';search.placeholder=field==='phone_normalized'?'연락처 입력':'찾을 값을 입력하세요';searchLabel.htmlFor=search.id;
  searchButton.type='button';searchGroup.append(search,searchButton);
  const selection=node('div',undefined,'filter-selection'),count=node('strong'),clear=node('button','선택 해제','filter-text-button'),selectedNames=node('p');
  clear.type='button';selection.append(count,clear,selectedNames);
  const toolbar=node('div',undefined,'filter-options-toolbar'),selectVisible=node('button','보이는 값 모두 선택','filter-text-button'),info=node('span');
  selectVisible.type='button';toolbar.append(selectVisible,info);
  const list=node('div');list.id='filter-options';list.setAttribute('role','group');list.setAttribute('aria-label','선택할 값');
  const error=node('p',undefined,'field-error');error.id='filter-options-error';error.setAttribute('role','alert');
  const more=node('button','더 불러오기','btn btn-sm btn-outline-secondary filter-load-more');more.type='button';more.hidden=true;
  area.append(operator,searchLabel,searchGroup,selection,toolbar,list,error,more);
  const records=()=>new Map([...base].filter(([value,label])=>!term||label.toLocaleLowerCase().includes(term.toLocaleLowerCase())||value.toLocaleLowerCase().includes(term.toLocaleLowerCase())).concat([...loaded]));
  const updateSelection=()=>{
    selection.hidden=!selected.size;count.textContent=`선택 ${selected.size.toLocaleString()}개`;clear.disabled=!selected.size;
    const names=[...selected].slice(0,3).map(value=>base.get(value)||loaded.get(value)||title(value));
    selectedNames.textContent=names.join(', ')+(selected.size>3?` 외 ${selected.size-3}개`:'');selectedNames.hidden=!selected.size;
    for(const input of list.querySelectorAll('input'))input.checked=selected.has(input.value);
    onChange();
  };
  const draw=()=>{
    const values=records();list.replaceChildren(...[...values].map(([value,label])=>{
      const wrap=node('label'),check=node('input');check.type='checkbox';check.value=value;check.checked=selected.has(value);
      check.onchange=()=>{changed=true;if(check.checked)selected.add(value);else selected.delete(value);updateSelection();};
      wrap.append(check,node('span',label));return wrap;
    }));
    if(!values.size)list.append(node('p',loading?'값을 불러오고 있습니다…':'검색 결과가 없습니다. 검색어를 바꿔 보세요.','filter-options-empty'));
    list.setAttribute('aria-busy',String(loading));selectVisible.disabled=!values.size;
    info.textContent=loading?'불러오는 중…':schema[field]?'여러 개 선택 가능':`전체 ${total.toLocaleString()}개 · 표시 ${values.size.toLocaleString()}개`;
    more.hidden=!hasNext&&!failed;more.disabled=loading;more.textContent=failed?'다시 불러오기':'더 불러오기';
    updateSelection();
  };
  const load=async(reset=false)=>{
    const sequence=++generation;
    if(reset){page=1;loaded.clear();hasNext=false;}
    loading=true;failed=false;error.textContent='';draw();
    try{
      const query=params();query.set('field',field);query.set('option_q',term);query.set('option_page',page);
      const data=await request('/api/customers/filter-options?'+query);
      if(!isCurrent()||sequence!==generation)return;
      for(const value of data.values){const code=key(value);if(!base.has(code))loaded.set(code,title(value));}
      total=data.total;hasNext=data.has_next;page++;
    }catch(problem){if(isCurrent()&&sequence===generation){failed=true;error.textContent=problem.message+' 다시 불러오기를 눌러 주세요.';}}
    finally{if(isCurrent()&&sequence===generation){loading=false;draw();}}
  };
  clear.onclick=()=>{selected.clear();changed=true;updateSelection();};
  selectVisible.onclick=()=>{for(const value of records().keys())selected.add(value);changed=true;updateSelection();};
  const searchValues=()=>{term=search.value.trim();void load(true);};
  searchButton.onclick=searchValues;search.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();event.stopPropagation();searchValues();}};
  search.addEventListener('search',searchValues);more.onclick=()=>load();
  draw();void load(true);
  return {
    hasValue:()=>!!selected.size||(!changed&&current?.contains!==undefined),
    read:()=>{
      if(!changed&&current?.contains!==undefined)return current;
      if(!selected.size)throw new Error('값을 1개 이상 선택해 주세요.');
      if(selected.size===1&&selected.has(''))return {blank:!exclude};
      return {values:[...selected].map(value=>field==='contract_status'&&value===''?'UNKNOWN':value),exclude};
    }
  };
}
