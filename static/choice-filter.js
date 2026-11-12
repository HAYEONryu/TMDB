// Fixed business options plus authorized historical values returned by the API.
export async function choiceFilter({area,field,schema,current,request,params,display,onChange=()=>{},isCurrent=()=>true}){
  const label=document.createElement('label'),select=document.createElement('select');
  label.textContent='필터 값';label.htmlFor='filter-choice';select.id='filter-choice';select.className='form-select mt-2';select.setAttribute('aria-label','필터 값');
  select.append(new Option('전체','ALL'),new Option('-','EMPTY'));
  const empty=value=>value==null||value===''||(field==='contract_status'&&value==='UNKNOWN');
  for(const [value,title] of Object.entries(schema[field]))if(!empty(value))select.add(new Option(title,JSON.stringify(value)));
  const legacy=document.createElement('optgroup');legacy.label='이전값';select.append(legacy);
  const values=current?.values??(Array.isArray(current)?current:[]);
  const selected=current?.blank!==undefined?'EMPTY':values.length&&values.every(empty)?'EMPTY':values.length?JSON.stringify(values[0]):'ALL';
  const seen=new Set(Object.keys(schema[field]));
  function add(value){
    if(empty(value)||seen.has(value))return;
    seen.add(value);legacy.append(new Option(display(field,value),JSON.stringify(value)));
  }
  for(const value of values)add(value);
  const modeLabel=document.createElement('label'),mode=document.createElement('select');modeLabel.textContent='조건';modeLabel.htmlFor='filter-choice-mode';mode.id='filter-choice-mode';mode.className='form-select mt-2';mode.append(new Option('일치하는 값만','include'),new Option('선택한 값 제외','exclude'));
  mode.value=current?.blank===false||current?.exclude?'exclude':'include';mode.disabled=selected==='ALL';
  let changed=false;
  select.onchange=mode.onchange=()=>{changed=true;mode.disabled=select.value==='ALL';onChange();};
  select.value=selected;area.append(modeLabel,mode,label,select);
  if(values.length>1||current?.contains!==undefined){const info=document.createElement('p');info.className='filter-help';info.textContent='기존 조건을 유지합니다. 값을 변경하면 선택한 한 값의 조건으로 바뀝니다.';area.append(info);}
  let page=1;
  const more=document.createElement('button');more.type='button';more.className='btn btn-sm btn-outline-secondary mt-2';more.textContent='이전값 더 보기';area.append(more);
  async function load(){
    more.disabled=true;
    try{
      const query=params();query.set('field',field);query.set('option_page',page);
      const data=await request('/api/customers/filter-options?'+query);
      if(!isCurrent())return;
      data.values.forEach(add);more.hidden=!data.has_next;page++;
    }catch(error){if(isCurrent()){document.querySelector('#filter-error').textContent=error.message;more.hidden=false;more.textContent='후보값 다시 확인';}}
    finally{more.disabled=false;}
  }
  more.onclick=load;await load();
  return ()=>!changed&&(values.length>1||current?.contains!==undefined)?current:select.value==='ALL'?undefined:select.value==='EMPTY'?{blank:mode.value==='include'}:{values:[JSON.parse(select.value)],exclude:mode.value==='exclude'};
}
