import {newRequestId} from './request-id.js';
import {PendingOperation} from './pending-operation.js';
import {employeeSupportError} from './browser-environment.js';
import {withRequestTimeout} from './request-timeout.js';
import {confirmAction} from './shared-ui.js';

export class ActivityRecorder {
  constructor({userId,changed=()=>{}}){
    this.changed=changed;this.userId=userId;this.busy=false;this.row=null;this.sequence=0;
    this.$=id=>document.getElementById('activity-'+id);
    this.request=(url,body)=>withRequestTimeout(async signal=>{
      const csrf=document.cookie.split('; ').find(v=>v.startsWith('csrftoken='))?.split('=').slice(1).join('=');
      const response=await fetch(url,{method:body===undefined?'GET':'POST',credentials:'same-origin',signal,
        headers:{'X-TM-Actor':userId,...(body===undefined?{}:{'Content-Type':'application/json','X-CSRFToken':csrf||''})},...(body===undefined?{}:{body:JSON.stringify(body)})});
      const data=await response.json();if(!response.ok){const error=new Error(data.error?.message||'기록 요청을 확인해 주세요.');error.status=response.status;throw error;}return data;
    });
    this.pending=new PendingOperation('activity',userId,/^\/api\/customers\/[0-9a-f-]+\/activities$/,this.request);
    this.$('kind').onchange=()=>this.sync();
    this.$('form').onsubmit=event=>{event.preventDefault();void this.save();};
    this.$('close').onclick=()=>{if(!this.busy)this.$('dialog').close();};
    this.$('dialog').addEventListener('cancel',event=>{if(this.busy)event.preventDefault();});
    this.$('dialog').addEventListener('close',()=>{this.sequence++;});
    this.$('retry').onclick=()=>this.save(true);
    this.$('dismiss').onclick=async()=>{if(!this.busy&&await confirmAction('확인 알림만 닫습니다. 이미 저장된 기록은 유지됩니다. 같은 통화를 새로 기록하기 전에 최근 기록을 확인하세요.',{title:'기록 확인 알림 닫기',confirmText:'알림 닫기'})){this.pending.clear();this.sync();}};
    window.addEventListener('beforeunload',event=>{if(this.busy||this.pending.value){event.preventDefault();event.returnValue='';}});
    this.sync();
  }
  sync(){
    const call=this.$('kind').value==='CALL',blocked=this.busy||!!this.pending.value;
    this.$('call-fields').hidden=!call;this.$('visit-fields').hidden=call;
    this.$('at').required=call;this.$('at').disabled=!call||blocked;
    this.$('visit-date').required=!call;this.$('visit-date').disabled=call||blocked;
    for(const id of ['kind','connection'])this.$(id).disabled=blocked;
    this.$('submit').disabled=blocked;this.$('submit').textContent=call?'통화 기록':'실제 방문 기록';
    this.$('close').disabled=this.busy;this.$('pending').hidden=!this.pending.value;
    this.$('retry').disabled=this.$('dismiss').disabled=this.busy;
  }
  button(row){
    const button=document.createElement('button');button.type='button';button.className='btn btn-sm btn-outline-primary';button.textContent='통화·방문 기록';
    const reason=employeeSupportError();button.disabled=!!reason;button.title=reason||'통화 한 번 또는 실제 방문을 별도로 기록합니다.';
    button.onclick=()=>this.open(row);return button;
  }
  async open(row){
    if(this.busy)return;
    this.row=row;const sequence=++this.sequence;
    const now=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).format(new Date()).replace(' ','T');
    this.$('customer').textContent=row.customer_name||'이름 미입력';
    this.$('kind').value='CALL';this.$('connection').value='UNKNOWN';this.$('at').value=now;this.$('visit-date').value=now.slice(0,10);this.$('visit-date').max=now.slice(0,10);
    this.$('error').textContent='';this.$('result').textContent='';this.$('recent').textContent='최근 내 기록 조회 중…';this.sync();this.$('dialog').showModal();
    try{const data=await this.request(`/api/customers/${row.id}/activities`);if(sequence!==this.sequence)return;
      this.$('recent').textContent=data.items.length?'최근 내 기록: '+data.items.slice(0,5).map(r=>r.kind==='CALL'?`${new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Seoul',dateStyle:'short',timeStyle:'medium',hourCycle:'h23'}).format(new Date(r.occurred_at))} · ${({CONNECTED:'연결',NOT_CONNECTED:'미연결',UNKNOWN:'확인 불가'})[r.connection]}`:`${r.visited_on} 실제 방문`).join(' / '):'최근 내 기록이 없습니다.';
    }catch(error){if(sequence===this.sequence)this.$('recent').textContent='최근 기록 조회 실패. '+error.message;}
  }
  async save(retry=false){
    if(this.busy||employeeSupportError())return;
    if(!retry&&!this.$('form').reportValidity())return;
    let value;
    if(!retry){
      if(this.pending.value)return;
      const call=this.$('kind').value==='CALL';
      value={endpoint:`/api/customers/${this.row.id}/activities`,body:{site_id:this.row.site_id,assignment_id:this.row.assignment_id,kind:call?'CALL':'VISIT',idempotency_key:newRequestId(),...(call?{occurred_at:this.$('at').value+'+09:00',connection:this.$('connection').value}:{visited_on:this.$('visit-date').value})}};
    }
    this.busy=true;this.$('error').textContent='';this.sync();
    try{await this.pending.execute(value);this.$('result').textContent='기록했습니다. 같은 통화를 다시 입력하지 마세요.';this.$('notice').textContent=this.$('result').textContent;if(this.$('dialog').open)this.$('dialog').close();await this.changed();}
    catch(error){this.$('error').textContent=error.message;this.$('notice').textContent=error.message;}
    finally{this.busy=false;this.sync();}
  }
}
