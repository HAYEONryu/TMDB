import {api, option} from "./api.js";
import {renderDashboard} from './dashboard.js';
const select = document.querySelector("#default-site"), button = document.querySelector("#set-default"), message = document.querySelector("#site-message");
let version;
let countRequest=0;
async function counts() {
  const request=++countRequest;
  if(!select.value){document.querySelector("#site-counts").textContent="";return;}
  try {const data=await api(`/api/sites/${select.value}/counts`);if(request===countRequest)document.querySelector("#site-counts").textContent=`전체 DB ${data.total} · 미할당 DB ${data.unassigned} · 휴지통 DB ${data.trash}`;}
  catch(error){if(request===countRequest)document.querySelector("#site-counts").textContent=error.message;}
  await renderDashboard(select.value);
}
async function load() {
  const data = await api("/api/sites");
  select.replaceChildren(...data.items.map(site => option(site.id, site.name)));
  if (data.default_site_id) select.value = data.default_site_id;
  version = data.settings_version;
  button.disabled = !data.items.length;
  if (!data.items.length) message.textContent = "등록된 현장이 없습니다. DB 관리에서 현장을 생성해 주세요.";
  await counts();
}
select.addEventListener("change",counts);
document.querySelector('#dashboard-refresh').onclick=counts;
button.addEventListener("click", async () => {
  button.disabled = true;
  try { const data = await api("/api/settings/default-site", {site_id: select.value, expected_version: version}, "PATCH");
    version = data.settings_version; message.textContent = "기본 현장을 설정했습니다. 다음 화면부터 적용됩니다.";
  } catch (error) { message.textContent = error.message; if (error.code === "VERSION_CONFLICT") await load(); }
  finally { button.disabled = !select.options.length; }
});
load().catch(error => { message.textContent = error.message; button.disabled = true; });
