import test from 'node:test';
import assert from 'node:assert/strict';
import {formatDateDigits,readDateInput,dateInputTimestamp} from '../static/date-input.js';

test('manual dates format digits and pasted dates, with time only when enabled',()=>{
  assert.equal(formatDateDigits('20261113'),'2026-11-13');
  assert.equal(formatDateDigits('2026-11-13'),'2026-11-13');
  assert.equal(formatDateDigits('202611131430'),'2026-11-13');
  assert.equal(formatDateDigits('202611131430',{allowTime:true}),'2026-11-13 14:30');
  assert.equal(formatDateDigits('2026-11-13T14:30',{allowTime:true}),'2026-11-13 14:30');
});

test('invalid and incomplete dates never roll over into another day',()=>{
  for(const value of ['2026-02-29','2026-04-31','0000-01-01','2026-00-10','2026-13-01','2026-11-00','2026-11-1','2026-11-13 14:30'])assert.throws(()=>readDateInput(value));
  for(const value of ['2026-11-13 24:00','2026-11-13 23:60','2026-11-13 1','2026-11-13 14:3'])assert.throws(()=>readDateInput(value,{allowTime:true}));
  for(const value of ['0001-01-01','0099-02-28','2000-02-29','2024-02-29','9999-12-31'])assert.equal(readDateInput(value),value);
  assert.throws(()=>readDateInput('1900-02-29'));
});

test('optional visit time and date-only callbacks serialize as KST, and clearing cancels',()=>{
  assert.equal(dateInputTimestamp(''),null);
  assert.equal(dateInputTimestamp('2026-11-13'),'2026-11-13T00:00:00+09:00');
  assert.equal(dateInputTimestamp('2026-11-13',{allowTime:true}),'2026-11-13T00:00:00+09:00');
  assert.equal(new Date(dateInputTimestamp('2026-11-13 14:30',{allowTime:true})).toISOString(),'2026-11-13T05:30:00.000Z');
});
