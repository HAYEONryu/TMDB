// Account metadata only. No passwords, cookies, queue contents or encryption keys.
if('BroadcastChannel' in window){
  const channel=new BroadcastChannel('tm-auth-context-v1');
  const identity=()=>({user:document.body.dataset.userId||'',role:document.body.dataset.role||'',initial:document.body.dataset.initial==='true'});
  channel.onmessage=event=>{
    if(event.data?.type==='query')channel.postMessage({type:'identity',...identity()});
    if(event.data?.type==='identity')window.dispatchEvent(new CustomEvent('tm-auth-context',{detail:event.data}));
  };
  channel.postMessage({type:'identity',...identity()});
  window.addEventListener('pageshow',()=>channel.postMessage({type:'identity',...identity()}));
}
