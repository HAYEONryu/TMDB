const channel=(()=>{try{return new BroadcastChannel('tm-admin-work');}catch{return null;}})();
export function announceAdminUpdate(site=null){
  window.dispatchEvent(new CustomEvent('tm-admin-data-changed',{detail:{site}}));
  try{channel?.postMessage({type:'work-changed',site});}catch{}
}
export function listenAdminUpdates(action){
  const update=()=>{if(document.visibilityState==='visible')void action();};
  window.addEventListener('tm-admin-data-changed',update);
  channel?.addEventListener('message',event=>{if(event.data?.type==='work-changed')update();});
  window.addEventListener('focus',update);
  document.addEventListener('visibilitychange',update);
}
