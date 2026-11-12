// Fixed business options plus authorized historical values returned by the API.
export async function choiceFilter({area,field,schema,current,request,params,display}){
  const label=document.createElement('label'),select=document.createElement('select');
  label.textContent='필터 값';label.htmlFor='filter-choice';select.id='filter-choice';select.className='form-select mt-2';select.setAttribute('aria-label','필터 값');
  select.append(new Option('전체','ALL'),new Option('(빈 값)','EMPTY'));
  for(const [value,title] of Object.entries(schema[field]))select.add(new Option(title,JSON.stringify(value)));
  const legacy=document.createElement('optgroup');legacy.label='이전값';select.append(legacy);
  const values=current?.values??(Array.isArray(current)?current:[]);
  const empty=value=>value==null||value===''||(field==='contract_status'&&value==='UNKNOWN');
  const selected=values.length&&values.every(empty)?'EMPTY':values.length?JSON.stringify(values[0]):'ALL';
  const seen=new Set(Object.keys(schema[field]));
  function add(value){
    if(empty(value)||seen.has(value))return;
    seen.add(value);legacy.append(new Option(display(field,value),JSON.stringify(value)));
  }
  for(const value of values)add(value);
  select.value=selected;area.append(label,select);
  let page=1;
  const more=document.createElement('button');more.type='button';more.className='btn btn-sm btn-outline-secondary mt-2';more.textContent='이전값 더 보기';area.append(more);
  async function load(){
    more.disabled=true;
    try{
      const query=params();query.set('field',field);query.set('option_page',page);
      const data=await request('/api/customers/filter-options?'+query);
      data.values.forEach(add);more.hidden=!data.has_next;page++;
    }catch(error){document.querySelector('#filter-error').textContent=error.message;more.hidden=false;more.textContent='후보값 다시 확인';}
    finally{more.disabled=false;}
  }
  more.onclick=load;await load();
  return ()=>select.value==='ALL'?undefined:{values:select.value==='EMPTY'?(field==='contract_status'?['UNKNOWN','']:[null]):[JSON.parse(select.value)],exclude:false};
}
