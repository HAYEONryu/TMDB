import {PendingOperation} from './pending-operation.js';
export class CallbackAction {
  constructor({userId,request,flush,getRow,refresh,notice,changed}){
    Object.assign(this,{flush,getRow,refresh,notice,changed});this.busy=false;
    this.pending=new PendingOperation('callback',userId,/^\/api\/customers\/[0-9a-f-]+\/callback-complete$/,request);
    document.querySelector('#callback-retry').onclick=()=>this.run();
    document.querySelector('#callback-discard').onclick=()=>{if(confirm('완료 요청의 대기 정보만 폐기하시겠습니까? 이미 서버에서 완료된 일정은 취소되지 않습니다.')){this.pending.clear();this.update();this.refresh().catch(error=>this.notice(error.message));}};
  }
  update(){document.querySelector('#callback-pending').hidden=!this.pending.value;for(const id of ['callback-retry','callback-discard'])document.querySelector('#'+id).disabled=this.busy;this.changed();}
  async run(id){
    if(this.busy)return false;this.busy=true;this.update();
    try{
      let value;
      if(id){
        if(this.pending.value)throw new Error('먼저 이전 재콜 완료 결과를 확인해 주세요.');
        if(!await this.flush(id))throw new Error('해당 행을 저장하지 못했습니다. 재콜은 완료하지 않았습니다.');
        const row=this.getRow(id);if(!row?.callback_id)throw new Error('현재 미완료 일정이 없습니다. 다시 조회해 주세요.');
        value={endpoint:`/api/customers/${id}/callback-complete`,body:{callback_id:row.callback_id,callback_version:row.callback_version,assignment_id:row.assignment_id,expected_version:row.version,idempotency_key:crypto.randomUUID()}};
      }
      const result=await this.pending.execute(value);await this.refresh(result.row);this.notice('재콜을 완료했습니다.');return true;
    }catch(error){this.notice(error.message);return false;}
    finally{this.busy=false;this.update();}
  }
  clear(){this.pending.clear();this.update();}
}
