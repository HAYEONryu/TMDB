const encode=new TextEncoder(),decode=new TextDecoder();
function bytes(value){return Uint8Array.from(atob(value),c=>c.charCodeAt(0));}
function b64(value){let text="";for(const n of new Uint8Array(value))text+=String.fromCharCode(n);return btoa(text);}
const aad=record=>encode.encode(JSON.stringify([record.key,record.user_id,record.site_id,record.customer_id,record.assignment_id]));
export class QueueStore {
  constructor(userId,key){this.userId=userId;this.key=key;this.db=null;}
  async open(){
    this.cryptoKey=await crypto.subtle.importKey("raw",bytes(this.key),{name:"AES-GCM"},false,["encrypt","decrypt"]);this.key=null;
    this.db=await new Promise((resolve,reject)=>{const request=indexedDB.open("tm-employee-queue-v1",1);request.onupgradeneeded=()=>{const store=request.result.createObjectStore("entries",{keyPath:"key"});store.createIndex("user_id","user_id");};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
    this.db.onversionchange=()=>this.db.close();return this;
  }
  transaction(mode,action){
    return new Promise((resolve,reject)=>{const tx=this.db.transaction("entries",mode,mode==="readwrite"?{durability:"strict"}:undefined);let result;tx.oncomplete=()=>resolve(result);tx.onerror=tx.onabort=()=>reject(tx.error||new Error("로컬 보관 실패"));try{const request=action(tx.objectStore("entries"));if(request)request.onsuccess=()=>{result=request.result;};}catch(error){tx.abort();reject(error);}});
  }
  list(){return this.transaction("readonly",store=>store.index("user_id").getAll(this.userId));}
  async read(record){
    if(record.user_id!==this.userId)throw new Error("대기열 계정 불일치");
    const data=await crypto.subtle.decrypt({name:"AES-GCM",iv:bytes(record.iv),additionalData:aad(record)},this.cryptoKey,bytes(record.cipher));
    return {...JSON.parse(decode.decode(data)),key:record.key,user_id:record.user_id,site_id:record.site_id,customer_id:record.customer_id,assignment_id:record.assignment_id};
  }
  async put(entry){
    const record={key:entry.key,user_id:this.userId,site_id:entry.site_id,customer_id:entry.customer_id,assignment_id:entry.assignment_id};
    const payload={version:entry.version,pending:entry.pending,inflight:entry.inflight,first_dirty_at:entry.first_dirty_at,pending_since:entry.pending_since,created_at:entry.created_at,state:entry.state,error:entry.error,retry_at:entry.retry_at,attempt:entry.attempt,ai_source_id:entry.ai_source_id,ai_fields:entry.ai_fields};
    const iv=crypto.getRandomValues(new Uint8Array(12));
    record.cipher=b64(await crypto.subtle.encrypt({name:"AES-GCM",iv,additionalData:aad(record)},this.cryptoKey,encode.encode(JSON.stringify(payload))));record.iv=b64(iv);
    await this.transaction("readwrite",store=>store.put(record));
  }
  remove(key){return this.transaction("readwrite",store=>store.delete(key));}
  close(){this.db?.close();this.cryptoKey=null;}
}
