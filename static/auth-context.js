// Optional account metadata only. Server permission checks remain authoritative.
(() => {
  if (typeof globalThis.BroadcastChannel !== 'function') return;
  let channel;
  try { channel = new BroadcastChannel('tm-auth-context-v1'); }
  catch { return; } // Storage policies may expose the API but reject its use.
  const identity = () => ({user: document.body.dataset.userId || '', role: document.body.dataset.role || '', initial: document.body.dataset.initial === 'true'});
  const send = () => {
    try { channel.postMessage({type: 'identity', ...identity()}); }
    catch { try { channel.close(); } catch {} }
  };
  channel.onmessage = event => {
    if (event.data?.type === 'query') send();
    if (event.data?.type === 'identity') window.dispatchEvent(new CustomEvent('tm-auth-context', {detail: event.data}));
  };
  send();
  window.addEventListener('pageshow', send);
})();
