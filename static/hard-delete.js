import {confirmAction} from './shared-ui.js';
import {newRequestId} from './request-id.js';
import {PendingOperation} from './pending-operation.js';
const bulkEndpoint = '/api/customers/bulk-hard-delete';
export class HardDelete {
  constructor({userId,request,refresh,notice,changed}){
    Object.assign(this,{request,refresh,notice,changed});this.busy=false;
    this.pending=new PendingOperation('hard-delete',userId,/^\/api\/(?:(customers|sites)\/[0-9a-f-]+\/hard-delete|customers\/bulk-hard-delete)$/,request);
    document.querySelector('#hard-confirm').onclick=()=>this.confirm();document.querySelector('#hard-retry').onclick=()=>this.execute();
    document.querySelector('#hard-discard').onclick=async()=>{if(await confirmAction('영구 삭제 확인 알림을 닫습니다. 이미 삭제된 고객정보와 이력은 복구되지 않습니다.',{title:'확인 알림 닫기',confirmText:'알림 닫기'})){const site=this.pending.value?.endpoint.startsWith('/api/sites/');this.pending.clear();this.update();this.refresh(site).catch(error=>this.notice(error.message));}};
  }
  update(){document.querySelector('#hard-pending').hidden=!this.pending.value;for(const id of ['hard-retry','hard-discard','hard-confirm'])document.querySelector('#'+id).disabled=this.busy;this.changed();}
  openCustomer(row){this.target={kind:'customers',id:row.id,version:row.version};document.querySelector('#hard-title').textContent='고객정보 영구 삭제';document.querySelector('#hard-message').textContent=`${row.customer_name} · 고객정보와 상담·배정·재콜 이력이 삭제되며 되돌릴 수 없습니다`;document.querySelector('#hard-name-label').hidden=true;this.open();}
  openSite(site){this.target={kind:'sites',id:site.id};document.querySelector('#hard-title').textContent='현장 영구 삭제';document.querySelector('#hard-message').textContent=`현장과 관련 고객정보 및 상담·배정·재콜 이력이 영구 삭제됩니다. ${site.name} 현장을 삭제하시겠습니까?`;document.querySelector('#hard-name-label').hidden=false;this.open();}
  openBulk(rows, site){
    this.target = {kind: 'bulk', site, rows: rows.map(row => ({customer_id: row.id, expected_version: row.version}))};
    document.querySelector('#hard-title').textContent = '일괄 영구 삭제';
    document.querySelector('#hard-message').textContent = `현재 페이지에서 선택한 고객 ${rows.length}명의 고객정보와 상담·배정·재콜 이력을 삭제합니다. 되돌릴 수 없습니다.`;
    document.querySelector('#hard-name-label').hidden = true;
    const counts = new Map();
    for (const row of rows) counts.set(row.site_name, (counts.get(row.site_name) || 0) + 1);
    const items = [...counts].map(([name, count]) => {
      const item = document.createElement('li');
      item.textContent = `${name} · ${count}명`;
      return item;
    });
    document.querySelector('#hard-sites').replaceChildren(...items);
    this.open();
  }
  open(){
    const bulk = this.target.kind === 'bulk';
    document.querySelector('#hard-sites').hidden = !bulk;
    if (!bulk) document.querySelector('#hard-sites').replaceChildren();
    document.querySelector('#hard-confirm').textContent = bulk ? '선택 고객 영구 삭제' : '영구 삭제 확인';
    document.querySelector('#hard-error').textContent='';document.querySelector('#hard-name').value='';document.querySelector('#hard-dialog').showModal();
  }
  async confirm(){
    if(this.busy||this.pending.value)return;this.busy=true;this.update();
    try{
      const key=newRequestId(),target=this.target;let body;
      const endpoint = target.kind === 'bulk' ? bulkEndpoint : `/api/${target.kind}/${target.id}/hard-delete`;
      if(target.kind==='sites'){
        const proof=await this.request(`/api/sites/${target.id}/deletion-confirmation`,{confirm_name:document.querySelector('#hard-name').value,idempotency_key:key});
        body={confirmation:proof.confirmation,idempotency_key:key};document.querySelector('#hard-name').value='';
      }else if (target.kind === 'bulk') {
        body = {confirm: true, site_id: target.site, rows: target.rows, idempotency_key: key};
      }else body={confirm:true,expected_version:target.version,idempotency_key:key};
      document.querySelector('#hard-dialog').close();this.busy=false;await this.execute({endpoint,body});
    }catch(error){document.querySelector('#hard-error').textContent=error.message;}
    finally{this.busy=false;this.update();}
  }
  async execute(value){
    if(this.busy)return;this.busy=true;this.update();
    const endpoint = (value || this.pending.value)?.endpoint;
    try {
      const result = await this.pending.execute(value);
      const summary = `${result.affected_count}명의 고객정보를 영구 삭제했습니다.`;
      try {
        await this.refresh(endpoint?.startsWith('/api/sites/'));
        this.notice(summary);
      } catch {
        this.notice(`${summary} 목록을 불러오지 못했습니다. 다시 조회해 주세요.`);
      }
    } catch (error) {
      if (endpoint === bulkEndpoint && ['SITE_CHANGED', 'DELETE_SELECTION_CHANGED'].includes(error.code)) {
        try { await this.refresh(false); } catch { /* Keep the deletion rejection visible. */ }
      }
      this.notice(error.message);
    }
    finally{this.busy=false;this.update();}
  }
}
