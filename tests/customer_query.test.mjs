import test from 'node:test';
import assert from 'node:assert/strict';
import {createQueryScheduler} from '../static/customer-query.js';

const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
test('a search submitted while reset is loading runs after reset and keeps its submitted term',async()=>{
  const reset=deferred(),events=[],state={q:'previous'};
  const run=createQueryScheduler(async action=>{events.push('guard');await action();return true;});
  const first=run(async()=>{events.push('reset');state.q='';await reset.promise;});
  const submitted='new search';
  const second=run(async()=>{state.q=submitted;events.push('search');});
  await Promise.resolve();assert.deepEqual(events,['guard','reset']);
  reset.resolve();assert.equal(await first,true);assert.equal(await second,true);
  assert.deepEqual(events,['guard','reset','guard','search']);assert.equal(state.q,'new search');
});
test('a failed query or a cancelled save guard leaves the next query available',async()=>{
  let cancel=true;const run=createQueryScheduler(async action=>{if(cancel){cancel=false;return false;}return action();});
  assert.equal(await run(()=>assert.fail('cancelled action ran')),false);
  await assert.rejects(run(()=>{throw new Error('synthetic failure');}),/synthetic failure/);
  assert.equal(await run(()=>42),42);
});
