import {api,option} from './api.js';
import {syncEmployeeSiteLinks} from './employee-navigation.js';
const site=document.querySelector('#published-site'),message=document.querySelector('#published-message'),body=document.querySelector('#published-body');let epoch=0;
let defaultSite='';
function syncSite(){
  syncEmployeeSiteLinks(site.value,defaultSite);
  const url=new URL(location.href);if(site.value)url.searchParams.set('site_id',site.value);else url.searchParams.delete('site_id');history.replaceState(null,'',url);
}
async function load(){const token=++epoch;body.textContent='';try{if(!site.value){message.textContent='현장이 없습니다.';return;}const data=await api(`/api/sites/${site.value}/published-guide`);if(token!==epoch)return;message.textContent=data.available?`${data.test_message||'검토·게시 완료'} · 버전 ${data.version} · ${new Date(data.published_at).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',hour12:false})} (한국 시각)`:data.message;body.textContent=data.body||'';}catch(error){if(token===epoch){message.textContent=error.message;body.textContent='';}}}
site.addEventListener('change',()=>{syncSite();void load();});document.querySelector('#published-refresh').addEventListener('click',load);
try{
  const data=await api('/api/sites'),selected=new URL(location.href).searchParams.get('site_id');defaultSite=data.default_site_id||'';
  data.items.forEach(row=>site.add(option(row.id,row.name)));
  if(selected&&!data.items.some(row=>row.id===selected)){site.value='';throw new Error('선택한 현장을 찾을 수 없습니다. 현장을 다시 선택해 주세요.');}
  if(selected||defaultSite)site.value=selected||defaultSite;syncSite();await load();
}catch(error){message.textContent=error.message;}
