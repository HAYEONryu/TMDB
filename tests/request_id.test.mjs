import test from 'node:test';
import assert from 'node:assert/strict';
import {webcrypto} from 'node:crypto';
import {newRequestId} from '../static/request-id.js';

const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
function withCrypto(provider, action) {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto');
  Object.defineProperty(globalThis, 'crypto', {value: provider, configurable: true});
  try { action(); }
  finally {
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor);
    else delete globalThis.crypto;
  }
}

test('uses native UUID when available and keeps its receiver', () => {
  const provider = {
    randomUUID() { assert.equal(this, provider); return '01234567-89ab-4def-8123-456789abcdef'; },
    getRandomValues() { throw new Error('native UUID should be used'); },
  };
  withCrypto(provider, () => assert.equal(newRequestId(), '01234567-89ab-4def-8123-456789abcdef'));
});

test('fallback sets UUID version and variant bits and preserves leading zeroes', () => {
  const provider = {getRandomValues(bytes) {
    assert.equal(this, provider);
    assert.ok(bytes instanceof Uint8Array);
    assert.equal(bytes.length, 16);
    return bytes.fill(0);
  }};
  withCrypto(provider, () => assert.equal(newRequestId(), '00000000-0000-4000-8000-000000000000'));
});

test('fallback masks version and variant bits from high random bytes', () => {
  withCrypto({getRandomValues: bytes => bytes.fill(255)}, () => {
    assert.equal(newRequestId(), 'ffffffff-ffff-4fff-bfff-ffffffffffff');
  });
});

test('fallback uses a real cryptographic RNG without randomUUID', () => {
  withCrypto({getRandomValues: webcrypto.getRandomValues.bind(webcrypto)}, () => {
    const ids = Array.from({length: 512}, () => newRequestId());
    for (const id of ids) assert.match(id, uuidV4);
    assert.equal(new Set(ids).size, ids.length);
  });
});

test('unavailable cryptography fails clearly instead of using weak randomness', () => {
  for (const provider of [undefined, {}, {randomUUID: undefined, getRandomValues: undefined}]) {
    withCrypto(provider, () => assert.throws(() => newRequestId(), /HTTPS/));
  }
});
