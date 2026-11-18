import {api,option} from './api.js';
import {listenAdminUpdates} from './admin-updates.js';
import {renderDashboard,showDashboardSetupError} from './dashboard.js';
import {StaffPerformance} from './staff-performance.js';
const $=id=>document.getElementById(id),select=$('default-site'),button=$('set-default'),message=$('site-message'),dialog=$('default-site-dialog'),service=$('service-default-site');
const staff=new StaffPerformance();let version,defaultSite='',saving=false;
function syncURL(){const url=new URL(location.href);if(select.value)url.searchParams.set('site_id',select.value);else url.searchParams.delete('site_id');history.replaceState(null,'',url);}
async function refresh(){syncURL();return Promise.all([renderDashboard(select.value),staff.load(select.value)]);}
async function settings(){const data=await api('/api/sites');defaultSite=data.default_site_id||'';version=data.settings_version;return data;}
async function load(){const selected=select.value||new URL(location.href).searchParams.get('site_id'),data=await settings();select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));select.value=selected||defaultSite;button.disabled=!data.items.length;if(!data.items.length)message.textContent='등록된 현장이 없습니다. DB 관리에서 현장을 생성해 주세요.';await refresh();}
select.onchange=refresh;$('dashboard-refresh').onclick=refresh;
button.onclick=async()=>{button.disabled=true;try{const data=await settings();service.replaceChildren(...data.items.map(site=>option(site.id,site.name)));service.value=defaultSite;$('default-site-error').textContent='';dialog.showModal();}catch(error){message.textContent=error.message;}finally{button.disabled=!select.options.length;}};
$('default-site-cancel').onclick=()=>{if(!saving)dialog.close();};dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault();});
$('default-site-form').onsubmit=async event=>{event.preventDefault();if(saving)return;saving=true;$('default-site-save').disabled=true;service.disabled=true;
  try{const data=await api('/api/settings/default-site',{site_id:service.value,expected_version:version},'PATCH');version=data.settings_version;defaultSite=data.default_site_id;message.textContent='기본 현장을 저장했습니다. 다음에 여는 업무 화면부터 적용됩니다. 현재 조회 현장은 유지합니다.';dialog.close();}
  catch(error){$('default-site-error').textContent=error.message;if(error.code==='VERSION_CONFLICT'){const data=await settings();service.replaceChildren(...data.items.map(site=>option(site.id,site.name)));service.value=defaultSite;$('default-site-error').textContent+=' 최신 설정을 확인하고 다시 저장하세요.';}}
  finally{saving=false;$('default-site-save').disabled=false;service.disabled=false;}
};
load().catch(error=>{showDashboardSetupError(error);button.disabled=true;});listenAdminUpdates(refresh);
