import {api,option} from './api.js';
import {renderDashboard} from './dashboard.js';
const select=document.querySelector('#employee-dashboard-site');
try{const data=await api('/api/sites');select.replaceChildren(...data.items.map(site=>option(site.id,site.name)));select.value=data.default_site_id||'';select.onchange=()=>renderDashboard(select.value);document.querySelector('#dashboard-refresh').onclick=()=>renderDashboard(select.value);await renderDashboard(select.value);}catch(error){document.querySelector('#dashboard-message').textContent=error.message;}
