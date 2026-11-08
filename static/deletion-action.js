import {newRequestId} from './request-id.js';
import {PendingOperation} from './pending-operation.js';
export class DeletionAction {
  constructor({userId,request,flush,getRow,refresh,notice,changed}){
    Object.assign(this,{flush,getRow,refresh,notice,changed});this.busy=false;this.confirmed=new Map();
    this.pending=new PendingOperation('deletion-request',userId,/^\/api\/customers\/[0-9a-f-]+\/deletion-request$/,request);
    document.querySelector('#deletion-retry').onclick=()=>this.run();
    document.querySelector('#deletion-discard').onclick=()=>{if(confirm('삭제 요청의 대기 정보만 폐기하시겠습니까? 이미 접수된 요청은 취소되지 않습니다.')){this.clear();this.refresh().catch(error=>this.notice(error.message));}};
  }
  isConfirmed(row){return this.confirmed.get(row.id)===row.assignment_id;}
  update(){document.querySelector('#deletion-pending').hidden=!this.pending.value;for(const id of ['deletion-retry','deletion-discard'])document.querySelector('#'+id).disabled=this.busy;this.changed();}
  async run(id){
    if(this.busy)return false;this.busy=true;this.busyId=id;this.update();
    try{
      let value;
      if(id){
        if(this.pending.value)throw new Error('먼저 이전 삭제 요청의 접수 결과를 확인해 주세요.');
        if(!await this.flush(id))throw new Error('해당 행을 저장하지 못했습니다. 삭제 요청을 제출하지 않았습니다.');
        const row=this.getRow(id);if(!row)throw new Error('현재 고객정보를 다시 조회해 주세요.');
        if(!confirm('이 고객정보의 삭제를 요청하시겠습니까? 관리자 승인 후 휴지통으로 이동합니다.'))return false;
        value={endpoint:`/api/customers/${id}/deletion-request`,body:{assignment_id:row.assignment_id,expected_version:row.version,idempotency_key:newRequestId()}};
      }
      const sent=value||this.pending.value;const result=await this.pending.execute(value);
      this.confirmed.set(result.customer_id,sent.body.assignment_id);await this.refresh();this.notice('삭제 요청을 접수했습니다. 관리자 승인 전까지 상담정보를 수정할 수 있습니다.');return true;
    }catch(error){if(['CUSTOMER_DELETED','SITE_DELETED','ASSIGNMENT_CHANGED'].includes(error.code))await this.refresh().catch(()=>{});this.notice(error.message);return false;}
    finally{this.busy=false;this.busyId=null;this.update();}
  }
  clear(){this.pending.clear();this.update();}
}
