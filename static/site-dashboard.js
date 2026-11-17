import {api,option} from './api.js';
import {listenAdminUpdates} from './admin-updates.js';
import {renderDashboard,showDashboardSetupError} from './dashboard.js';
const select=document.querySelector('#default-site'),button=document.querySelector('#set-default'),message=document.querySelector('#site-message');
let version,defaultSite='';
function syncLinks(){
  const paths=new Set(['/app/admin','/app/admin/customers','/app/admin/assignments','/app/admin/imports','/app/admin/users']);
  for(const link of document.querySelectorAll('a[href]')){const url=new URL(link.href,location.href);if(url.origin!==location.origin||!paths.has(url.pathname))continue;if(select.value)url.searchParams.set('site_id',select.value);else url.searchParams.delete('site_id');link.href=url.pathname+url.search+url.hash;}
  const url=new URL(location.href);if(select.value&&select.value!==defaultSite)url.searchParams.set('site_id',select.value);else url.searchParams.delete('site_id');history.replaceState(null,'',url);
}
async function refresh(){document.querySelector('#dashboard-refresh').onclick=refresh;syncLinks();return renderDashboard(select.value);}
async function load(){
  const selected=select.value||new URL(location.href).searchParams.get('site_id'),data=await api('/api/sites');
  defaultSite=data.default_site_id||'';select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));select.value=selected||data.default_site_id||'';version=data.settings_version;button.disabled=!data.items.length;
  if(!data.items.length)message.textContent='등록된 현장이 없습니다. DB 관리에서 현장을 생성해 주세요.';
  await refresh();
}
select.onchange=refresh;document.querySelector('#dashboard-refresh').onclick=refresh;
button.onclick=async()=>{button.disabled=true;const site=select.value;try{const data=await api('/api/settings/default-site',{site_id:site,expected_version:version},'PATCH');version=data.settings_version;message.textContent='기본 현장을 설정했습니다. 다음 화면부터 적용됩니다.';}catch(error){message.textContent=error.message;if(error.code==='VERSION_CONFLICT')await load();}finally{button.disabled=!select.options.length;}};
load().catch(error=>{showDashboardSetupError(error);button.disabled=true;});

listenAdminUpdates(refresh);
