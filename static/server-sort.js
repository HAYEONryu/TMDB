// Header sorting always issues a server query; never sorts only loaded rows.
export function sortTitle(field,label,getState,change){
  return ()=>{const button=document.createElement('button');button.type='button';button.className='grid-sort-button';button.dataset.sortField=field;button.dataset.sortLabel=label;
    button.onclick=event=>{event.stopPropagation();change(getState().sort===field?'-'+field:field);};
    button.textContent=label;return button;};
}
export function syncSortHeaders(table,sort){
  for(const column of table.getColumns()){
    const element=column.getElement(),button=element.querySelector('[data-sort-field]');if(!button)continue;
    const active=sort.replace(/^-/,'')===button.dataset.sortField,descending=sort.startsWith('-');
    element.setAttribute('aria-sort',active?(descending?'descending':'ascending'):'none');
    button.textContent=button.dataset.sortLabel+(active?(descending?' ↓':' ↑'):' ↕');
    button.setAttribute('aria-label',button.dataset.sortLabel+' · '+(active?(descending?'내림차순 · 오름차순으로 변경':'오름차순 · 내림차순으로 변경'):'정렬 안 됨 · 오름차순 정렬'));
  }
}
