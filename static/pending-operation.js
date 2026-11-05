import {api} from "./api.js";
export class PendingOperation {
  constructor(scope,userId,allowed,request=api) {
    this.request=request;
    this.key=`tm:p4:${scope}:${userId}`;this.allowed=allowed;this.value=null;
    try{const value=JSON.parse(sessionStorage.getItem(this.key));if(value&&allowed.test(value.endpoint)&&value.body?.idempotency_key)this.value=value;}catch{}
  }
  set(value){this.value={...value,created_at:Date.now()};try{sessionStorage.setItem(this.key,JSON.stringify(this.value));}catch{}}
  clear(){this.value=null;try{sessionStorage.removeItem(this.key);}catch{}}
  async execute(value){
    if(value)this.set(value);
    if(!this.value)throw new Error("확인할 요청이 없습니다.");
    const elapsed=Date.now()-this.value.created_at;
    if(!Number.isFinite(elapsed)||elapsed<0||elapsed>=7*24*60*60*1000)throw new Error("요청 보관 기간이 지났거나 요청 시각을 확인할 수 없습니다. 현재 서버 상태를 확인하고 대기 정보를 폐기해 주세요.");
    try{const result=await this.request(this.value.endpoint,this.value.body);this.clear();return result;}
    catch(error){if(error.status>=400&&error.status<500&&![401,403,429].includes(error.status))this.clear();throw error;}
  }
}
