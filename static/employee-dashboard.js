import {api,option} from './api.js';
import {renderDashboard} from './dashboard.js';
import {syncEmployeeSiteLinks} from './employee-navigation.js';
const select=document.querySelector('#employee-dashboard-site');
try{
  const data=await api('/api/sites');select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));
  const selected=new URL(location.href).searchParams.get('site_id')||data.default_site_id||'';
  select.value=selected;
  const refresh=()=>{syncEmployeeSiteLinks(select.value,data.default_site_id);return renderDashboard(select.value);};
  select.onchange=refresh;document.querySelector('#dashboard-refresh').onclick=refresh;
  syncEmployeeSiteLinks(selected,data.default_site_id);await renderDashboard(selected);
}catch(error){document.querySelector('#dashboard-message').textContent=error.message;}
