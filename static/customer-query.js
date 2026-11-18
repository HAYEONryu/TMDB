import {renderFilterChips} from './grid-filter.js';

// Keep a search submitted during a preceding query (for example, Reset then
// Search) until that query and its save guard finish. A rejected query must not
// prevent the next one from running.
export function createQueryScheduler(guard){
  let previous=Promise.resolve();
  return action=>{
    const current=previous.then(()=>guard(action));
    previous=current.catch(()=>{});
    return current;
  };
}

// Query state belongs to the grids so their save/leave guards remain authoritative.
export function createQueryUI({getState,labels,display,change,view,grid}){
  const $=id=>document.getElementById(id),hasConditions=state=>!!(state.q||state.assignee||state.category||Object.keys(state.filters).length);
  let succeeded=false,lastTotal=0,searchRevision=0;
  $('search').addEventListener('input',()=>searchRevision++);
  const clearSearch=revision=>{if(revision===searchRevision){$('search').value='';searchRevision++;}};
  const remove=key=>{
    const revision=searchRevision;
    return change(state=>{if(key==='_search'){state.q='';clearSearch(revision);}else if(key==='_assignee')state.assignee='';else if(key==='_category')state.category='';else delete state.filters[key];state.page=1;});
  };
  const render=({search=false}={})=>{const state=getState();renderFilterChips($('active-filters'),state.filters,labels,display,remove,state);const count=Object.keys(state.filters).length;
    $('open-filters').textContent=`상세 필터 (${count})`;$('open-filters').classList.toggle('has-filters',count>0);
    $('clear-filters').disabled=!hasConditions(state);if(search){$('search').value=state.q;searchRevision++;}$('site').value=state.site;
    if(!Array.from($('sort').options).some(o=>o.value===state.sort)){const option=document.createElement('option');option.value=state.sort;option.textContent=(labels[state.sort.replace(/^-/,'')]||'선택 열')+(state.sort.startsWith('-')?' 내림차순':' 오름차순');$('sort').append(option);}
    $('sort').value=state.sort;$('page-size').value=String(state.size);
  };
  const reset=()=>{
    const revision=searchRevision;
    return change(state=>{state.q='';clearSearch(revision);state.filters={};if('assignee' in state)state.assignee='';if('category' in state)state.category='';state.page=1;});
  };
  $('clear-filters').onclick=reset;$('empty-reset').onclick=reset;
  const stateMessage=(message,{error=false,reset=false,retry=false}={})=>{$('list-state').hidden=!message;$('list-state').classList.toggle('query-error',error);$('list-state-message').textContent=message;$('empty-reset').hidden=!reset;$('list-retry').hidden=!retry;};
  return {render,reset,
    start(){grid.setAttribute('aria-busy','true');$('result-count').textContent='조회 중…';stateMessage('고객 목록을 불러오고 있습니다…');},
    success(data){succeeded=true;lastTotal=data.total;grid.setAttribute('aria-busy','false');render();$('result-count').textContent=`검색 결과 ${data.total.toLocaleString()}명`;
      const url=new URL(location.href);if(!getState().category)url.searchParams.delete('dashboard_category');if(url.searchParams.has('q')){if(getState().q)url.searchParams.set('q',getState().q);else url.searchParams.delete('q');}if(url.searchParams.has('sort'))url.searchParams.set('sort',getState().sort);history.replaceState(null,'',url);
      if(getState().category&&data.as_of)$('result-count').textContent+=' · '+new Intl.DateTimeFormat('ko-KR',{timeZone:'Asia/Seoul',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date(data.as_of))+' 조회';
      const state=getState(),filtered=hasConditions(state);
      stateMessage(data.total?'':filtered?'조건에 맞는 고객이 없습니다.':view==='today'?'오늘의 TM 고객이 없습니다.':view==='mine'?'담당 고객이 없습니다.':view==='trash'?'휴지통이 비어 있습니다.':'등록된 고객이 없습니다.',{reset:!data.total&&filtered});
    },
    failure(problem){grid.setAttribute('aria-busy','false');render({search:true});$('result-count').textContent=succeeded?`검색 결과 ${lastTotal.toLocaleString()}명 · 마지막 결과`:'조회 실패';stateMessage(`고객 목록을 불러오지 못했습니다. ${succeeded?'마지막으로 확인한 조건과 목록을 표시합니다. ':''}${problem.message}`,{error:true,retry:true});},
  };
}
