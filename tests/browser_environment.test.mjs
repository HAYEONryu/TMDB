import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import {employeeSupportError, storageSupportError, lockSupportError} from '../static/browser-environment.js';
import {withRequestTimeout} from '../static/request-timeout.js';
import {QueueStore} from '../static/employee-store.js';
import {EmployeeQueue} from '../static/employee-queue.js';

const environment = () => ({isSecureContext: true, crypto: webcrypto, TextEncoder, TextDecoder,
  indexedDB: {open() {}}, navigator: {locks: {request() {}}}});
async function withGlobals(properties, action) {
  const descriptors = Object.fromEntries(Object.keys(properties).map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  for (const [key, value] of Object.entries(properties)) Object.defineProperty(globalThis, key, {value, configurable: true});
  try { return await action(); }
  finally { for (const [key, descriptor] of Object.entries(descriptors)) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
  }}
}

test('secure context with encryption, storage and locks supports editing', () => {
  assert.equal(employeeSupportError(environment()), null);
});
test('HTTP explains HTTPS requirement before checking unavailable APIs', () => {
  assert.equal(employeeSupportError({isSecureContext: false}).code, 'HTTPS_REQUIRED');
});
test('missing encryption or encoding support produces an actionable error', () => {
  for (const changes of [{crypto: {}}, {crypto: {subtle: webcrypto.subtle}}, {TextEncoder: undefined}]) {
    assert.equal(storageSupportError({...environment(), ...changes}).code, 'SECURE_STORAGE_UNSUPPORTED');
  }
});
test('missing or blocked IndexedDB never enables an unencrypted substitute', () => {
  assert.equal(storageSupportError({...environment(), indexedDB: undefined}).code, 'STORAGE_UNAVAILABLE');
  const env = environment();
  Object.defineProperty(env, 'indexedDB', {get() { throw new Error('blocked'); }});
  assert.equal(storageSupportError(env).code, 'STORAGE_UNAVAILABLE');
});
test('missing Web Locks is distinguished from an HTTP connection', () => {
  assert.equal(lockSupportError({...environment(), navigator: {}}).code, 'SAVE_LOCK_UNSUPPORTED');
  assert.equal(lockSupportError({isSecureContext: false}).code, 'HTTPS_REQUIRED');
});
test('HTTP queue startup never opens storage or sends a request and clears the supplied key', async () => {
  await withGlobals({isSecureContext: false}, async () => {
    let opens = 0, requests = 0;
    const queue = new EmployeeQueue('synthetic-user', async () => requests++, {store: {open: async () => opens++}});
    const context = {key: 'synthetic-not-a-real-key', target_ms: 90000};
    assert.equal(await queue.start(context), false);
    assert.equal(context.key, null);
    assert.equal(queue.paused, true);
    assert.equal(queue.canEdit({id: 'customer'}), false);
    assert.equal(opens + requests, 0);
    await assert.rejects(new QueueStore('synthetic-user', 'synthetic').open(), {code: 'HTTPS_REQUIRED'});
  });
});
test('loss of locks pauses sending while retaining pending values', async () => {
  await withGlobals({navigator: {onLine: true}, isSecureContext: true}, async () => {
    let requests = 0;
    const queue = new EmployeeQueue('synthetic-user', async () => requests++);
    const entry = {key: 'synthetic-entry', customer_id: 'customer', pending: {notes: 'synthetic pending'}, state: 'dirty'};
    queue.entries.set(entry.key, entry);
    assert.equal(await queue.flush(true), false);
    assert.equal(queue.paused, true);
    assert.equal(queue.entries.get(entry.key), entry);
    assert.equal(entry.pending.notes, 'synthetic pending');
    assert.equal(requests, 0);
  });
});
test('storage opening denial pauses editing and clears the supplied key', async () => {
  await withGlobals(environment(), async () => {
    let closed = false, requests = 0;
    const store = {open: async () => { throw new DOMException('blocked', 'SecurityError'); }, close() { closed = true; }};
    const queue = new EmployeeQueue('synthetic-user', async () => requests++, {store});
    const context = {key: 'synthetic-not-a-real-key', target_ms: 90000};
    assert.equal(await queue.start(context), false);
    assert.equal(context.key, null);
    assert.equal(queue.paused, true);
    assert.equal(closed, true);
    assert.equal(requests, 0);
  });
});
test('timeout wrapper does not depend on AbortSignal.timeout', async () => {
  const descriptor = Object.getOwnPropertyDescriptor(AbortSignal, 'timeout');
  Object.defineProperty(AbortSignal, 'timeout', {value: undefined, configurable: true});
  try { assert.equal(await withRequestTimeout(async signal => { assert.equal(signal.aborted, false); return 7; }), 7); }
  finally { Object.defineProperty(AbortSignal, 'timeout', descriptor); }
});
test('timeout stays active while parsing a response body', async () => {
  let receivedHeaders = false;
  await assert.rejects(withRequestTimeout(async signal => {
    receivedHeaders = true;
    return await new Promise((resolve, reject) => signal.addEventListener('abort', () => reject(new Error('aborted')), {once: true}));
  }, 5), {code: 'REQUEST_TIMEOUT'});
  assert.equal(receivedHeaders, true);
});
test('swallowing an aborted response body cannot turn a timeout into success', async () => {
  await assert.rejects(withRequestTimeout(signal => new Promise(resolve => {
    signal.addEventListener('abort', () => resolve({}), {once: true});
  }), 5), {code: 'REQUEST_TIMEOUT'});
});
test('completed and failed actions clear the timer and preserve ordinary errors', async () => {
  let signal;
  await withRequestTimeout(async value => { signal = value; }, 5);
  await new Promise(resolve => setTimeout(resolve, 15));
  assert.equal(signal.aborted, false);
  const error = new Error('ordinary failure');
  await assert.rejects(withRequestTimeout(async () => { throw error; }), value => value === error);
});
test('missing AbortController fails clearly before running the request', async () => {
  await withGlobals({AbortController: undefined}, async () => {
    let called = false;
    await assert.rejects(withRequestTimeout(async () => { called = true; }), /최신 브라우저/);
    assert.equal(called, false);
  });
});

const authScript = readFileSync(new URL('../static/auth-context.js', import.meta.url), 'utf8');
test('optional BroadcastChannel absence or constructor denial does not crash the page', () => {
  for (const BroadcastChannel of [undefined, class { constructor() { throw new Error('blocked'); }}]) {
    assert.doesNotThrow(() => vm.runInNewContext(authScript, {BroadcastChannel}));
  }
});
test('BroadcastChannel post failures are contained', () => {
  let closed = 0, pageshow;
  class BroadcastChannel { postMessage() { throw new Error('closed'); } close() { closed++; } }
  vm.runInNewContext(authScript, {BroadcastChannel, document: {body: {dataset: {userId: 'synthetic'}}},
    window: {addEventListener(_name, callback) { pageshow = callback; }}});
  assert.doesNotThrow(() => pageshow());
  assert.equal(closed, 2);
});
test('authentication channel only sends identity metadata', () => {
  const messages = [];
  class BroadcastChannel { postMessage(value) { messages.push(value); } }
  vm.runInNewContext(authScript, {BroadcastChannel, document: {body: {dataset: {userId: 'synthetic', role: 'EMPLOYEE', initial: 'false'}}},
    window: {addEventListener() {}}});
  assert.equal(JSON.stringify(messages), JSON.stringify([{type: 'identity', user: 'synthetic', role: 'EMPLOYEE', initial: false}]));
});
