// Shared navigation, dialog focus and overflow hints; business handlers own writes.
const toggle=document.getElementById('menu-toggle'),menu=document.getElementById('workspace-menu');
const narrow=matchMedia('(max-width: 1199px)');
function closeMenu(focus=false){menu?.classList.remove('is-open');toggle?.setAttribute('aria-expanded','false');if(focus)toggle?.focus();}
toggle?.addEventListener('click',()=>{const open=toggle.getAttribute('aria-expanded')!=='true';menu.classList.toggle('is-open',open);toggle.setAttribute('aria-expanded',String(open));});
menu?.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();closeMenu(true);}});
toggle?.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenu(true);if(event.key==='ArrowDown'){event.preventDefault();menu.classList.add('is-open');toggle.setAttribute('aria-expanded','true');menu.querySelector('a')?.focus();}});
narrow.addEventListener('change',()=>{if(!narrow.matches)closeMenu();});
document.addEventListener('click',event=>{if(narrow.matches&&!menu?.contains(event.target)&&event.target!==toggle)closeMenu();});

let lastOutside=document.activeElement;
document.addEventListener('focusin',event=>{if(!event.target.closest('dialog'))lastOutside=event.target;},true);
const installed=new WeakSet(),openers=new WeakMap();
function prepareDialogs(){
  for(const dialog of document.querySelectorAll('dialog')){
    if(installed.has(dialog))continue;installed.add(dialog);
    const heading=dialog.querySelector('h2');if(heading&&!dialog.hasAttribute('aria-labelledby')){heading.id ||= dialog.id+'-title';dialog.setAttribute('aria-labelledby',heading.id);}
    dialog.addEventListener('beforetoggle',event=>{if(event.newState==='open'){const active=document.activeElement;openers.set(dialog,active&&!dialog.contains(active)&&active!==document.body?active:lastOutside);}});
    dialog.addEventListener('close',()=>{const opener=openers.get(dialog)||lastOutside;requestAnimationFrame(()=>{if(opener?.isConnected&&!opener.disabled&&!opener.closest('[hidden]'))opener.focus({preventScroll:true});else if(!document.querySelector('dialog[open]'))document.getElementById('main-content')?.focus({preventScroll:true});});});
  }
}
const observed=new WeakSet();let scheduled=false;
const resize=new ResizeObserver(()=>scheduleHints());
function updateHints(){
  scheduled=false;prepareDialogs();
  for(const hint of document.querySelectorAll('.table-scroll-hint')){
    const grid=hint.nextElementSibling,holder=grid?.querySelector('.tabulator-tableholder')||grid;
    if(!holder)continue;if(!observed.has(holder)){observed.add(holder);resize.observe(holder);}
    const hidden=holder.scrollWidth<=holder.clientWidth+1;if(hint.hidden!==hidden)hint.hidden=hidden;
  }
}
function scheduleHints(){if(!scheduled){scheduled=true;requestAnimationFrame(updateHints);}}
new MutationObserver(scheduleHints).observe(document.body,{childList:true,subtree:true});
window.addEventListener('resize',scheduleHints);prepareDialogs();scheduleHints();

// Native <dialog> supplies focus trapping and Escape, shared with existing dialogs.
export function confirmAction(message,{title='변경 확인',confirmText='변경 적용',danger=false,notice=false}={}){
  return new Promise(resolve=>{
    const opener=document.activeElement,dialog=document.createElement('dialog');dialog.id='action-confirm-dialog';
    const heading=document.createElement('h2');heading.textContent=title;
    const body=document.createElement('p');body.textContent=message;body.style.whiteSpace='pre-wrap';
    const actions=document.createElement('div');actions.className='dialog-actions';
    const cancel=document.createElement('button'),confirm=document.createElement('button');
    cancel.type=confirm.type='button';cancel.className='btn btn-outline-secondary';cancel.textContent=notice?'닫기':'취소';cancel.autofocus=true;
    confirm.className='btn '+(danger?'btn-danger':'btn-primary');confirm.textContent=confirmText;confirm.id='action-confirm-accept';cancel.id='action-confirm-cancel';
    actions.append(cancel);if(!notice)actions.append(confirm);dialog.append(heading,body,actions);document.body.append(dialog);prepareDialogs();openers.set(dialog,opener);
    let accepted=false;cancel.onclick=()=>dialog.close();confirm.onclick=()=>{accepted=true;dialog.close();};
    dialog.addEventListener('close',()=>{dialog.remove();resolve(accepted);},{once:true});dialog.showModal();
  });
}

export const showNotice=(message,title='안내')=>confirmAction(message,{title,notice:true});
