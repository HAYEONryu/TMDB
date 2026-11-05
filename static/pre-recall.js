export function installPreRecall({serverTime,receivedAt,commit,flush,notice,now=()=>Date.now()}){
  const offset=new Date(serverTime).getTime()-(receivedAt??now());let attempted='';
  const check=(reconnected=false)=>{
    if(document.visibilityState!=='visible')return;
    const korean=new Date(now()+offset+9*3600000),day=korean.toISOString().slice(0,10),seconds=korean.getUTCHours()*3600+korean.getUTCMinutes()*60+korean.getUTCSeconds();
    if(seconds<22*3600+59*60+30||seconds>=23*3600||(!reconnected&&day===attempted))return;
    attempted=day;commit();flush().then(ok=>{if(!ok)notice('23시 회수 전 저장을 확인하지 못했습니다. 저장 상태를 확인해 주세요.');});
  };
  const timer=setInterval(check,1000);window.addEventListener('online',()=>check(true));document.addEventListener('visibilitychange',()=>check());check();return ()=>clearInterval(timer);
}
