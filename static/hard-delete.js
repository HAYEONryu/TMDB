import {newRequestId} from './request-id.js';
import {PendingOperation} from './pending-operation.js';
export class HardDelete {
  constructor({userId,request,refresh,notice,changed}){
    Object.assign(this,{request,refresh,notice,changed});this.busy=false;
    this.pending=new PendingOperation('hard-delete',userId,/^\/api\/(customers|sites)\/[0-9a-f-]+\/hard-delete$/,request);
    document.querySelector('#hard-confirm').onclick=()=>this.confirm();document.querySelector('#hard-retry').onclick=()=>this.execute();
    document.querySelector('#hard-discard').onclick=()=>{if(confirm('영구 삭제 요청의 대기 정보만 폐기하시겠습니까? 이미 삭제된 정보는 복구되지 않습니다.')){const site=this.pending.value?.endpoint.startsWith('/api/sites/');this.pending.clear();this.update();this.refresh(site).catch(error=>this.notice(error.message));}};
  }
  update(){document.querySelector('#hard-pending').hidden=!this.pending.value;for(const id of ['hard-retry','hard-discard','hard-confirm'])document.querySelector('#'+id).disabled=this.busy;this.changed();}
  openCustomer(row){this.target={kind:'customers',id:row.id,version:row.version};document.querySelector('#hard-title').textContent='고객정보 영구 삭제';document.querySelector('#hard-message').textContent=`${row.customer_name} · 고객정보와 상담·할당·재콜 이력이 삭제되며 되돌릴 수 없습니다`;document.querySelector('#hard-name-label').hidden=true;this.open();}
  openSite(site){this.target={kind:'sites',id:site.id};document.querySelector('#hard-title').textContent='현장 영구 삭제';document.querySelector('#hard-message').textContent=`현장과 관련 고객정보 및 상담·할당·재콜 이력이 영구 삭제됩니다. ${site.name} 현장을 삭제하시겠습니까?`;document.querySelector('#hard-name-label').hidden=false;this.open();}
  open(){document.querySelector('#hard-error').textContent='';document.querySelector('#hard-name').value='';document.querySelector('#hard-dialog').showModal();}
  async confirm(){
    if(this.busy||this.pending.value)return;this.busy=true;this.update();
    try{
      const key=newRequestId(),target=this.target;let body;
      if(target.kind==='sites'){
        const proof=await this.request(`/api/sites/${target.id}/deletion-confirmation`,{confirm_name:document.querySelector('#hard-name').value,idempotency_key:key});
        body={confirmation:proof.confirmation,idempotency_key:key};document.querySelector('#hard-name').value='';
      }else body={confirm:true,expected_version:target.version,idempotency_key:key};
      document.querySelector('#hard-dialog').close();this.busy=false;await this.execute({endpoint:`/api/${target.kind}/${target.id}/hard-delete`,body});
    }catch(error){document.querySelector('#hard-error').textContent=error.message;}
    finally{this.busy=false;this.update();}
  }
  async execute(value){
    if(this.busy)return;this.busy=true;this.update();
    try{const endpoint=(value||this.pending.value)?.endpoint;const result=await this.pending.execute(value);await this.refresh(endpoint?.startsWith('/api/sites/'));this.notice(`${result.affected_count}건의 고객정보를 영구 삭제했습니다.`);}
    catch(error){this.notice(error.message);}
    finally{this.busy=false;this.update();}
  }
}
