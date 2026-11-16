import test from 'node:test';
import assert from 'node:assert/strict';
import {mutationMessage,uncertainResult} from '../static/ui-messages.js';

test('lost, server-error, timeout and throttled responses keep write outcome open',()=>{
  for(const status of [undefined,500,503,408,429]){
    const error=Object.assign(new Error('가상 응답 오류'),{status});
    assert.equal(uncertainResult(error),true);
    assert.match(mutationMessage(error,'저장'),/^저장 결과를 확인하지 못했습니다\./);
    assert.match(mutationMessage(error,'저장'),/같은 요청/);
  }
});
test('definitive validation and conflict errors say the operation did not complete',()=>{
  for(const status of [400,401,403,409,422]){
    const error=Object.assign(new Error('입력값을 확인하세요.'),{status});
    assert.equal(uncertainResult(error),false);
    assert.match(mutationMessage(error,'저장'),/^저장하지 못했습니다\./);
    assert.equal(error.message,'입력값을 확인하세요.');
  }
});
