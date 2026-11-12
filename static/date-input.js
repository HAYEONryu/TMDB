// Manual KST dates shared by grid editors and date-range filters.
export function formatDateDigits(value,{allowTime=false}={}){
  const digits=String(value).replace(/\D/g,'').slice(0,allowTime?12:8);
  let result=digits.slice(0,4);
  if(digits.length>4)result+='-'+digits.slice(4,6);
  if(digits.length>6)result+='-'+digits.slice(6,8);
  if(digits.length>8)result+=' '+digits.slice(8,10);
  if(digits.length>10)result+=':'+digits.slice(10,12);
  return result;
}

export function readDateInput(value,{allowTime=false}={}){
  if(!value)return null;
  const match=(allowTime?/^(\d{4})-(\d{2})-(\d{2})(?: (\d{2}):(\d{2}))?$/:/^(\d{4})-(\d{2})-(\d{2})$/).exec(value);
  if(!match)throw new Error(allowTime?'날짜 8자리와 필요한 경우 시간 4자리를 입력해 주세요. (YYYY-MM-dd HH:mm)':'날짜를 숫자 8자리로 입력해 주세요. (YYYY-MM-dd)');
  const [,year,month,day,hour='00',minute='00']=match;
  const date=new Date(0);date.setUTCFullYear(+year,+month-1,+day);
  if(+year<1||date.getUTCFullYear()!==+year||date.getUTCMonth()!==+month-1||date.getUTCDate()!==+day)throw new Error('존재하는 날짜를 입력해 주세요.');
  if(+hour>23||+minute>59)throw new Error('시간은 00:00부터 23:59까지 입력해 주세요.');
  return value;
}

export function dateInputTimestamp(value,options){
  const date=readDateInput(value,options);
  return date?date.slice(0,10)+'T'+(date.slice(11)||'00:00')+':00+09:00':null;
}

export function setupDateInput(input,{allowTime=false}={}){
  input.type='text';input.inputMode='numeric';input.autocomplete='off';
  input.placeholder=allowTime?'YYYY-MM-dd HH:mm':'YYYY-MM-dd';
  input.title=allowTime?'날짜 숫자 8자리 · 시간 숫자 4자리(선택) · 한국 시각':'날짜 숫자 8자리 (예: 20261113)';
  // Deleting an automatic separator also deletes the adjacent digit, so the
  // caret never gets stuck on a hyphen, space or colon as it is reinserted.
  input.addEventListener('beforeinput',event=>{
    const start=input.selectionStart,end=input.selectionEnd;
    if(start!==end)return;
    if(event.inputType==='deleteContentBackward'&&start>0&&/\D/.test(input.value[start-1]))input.setSelectionRange(Math.max(0,start-2),end);
    if(event.inputType==='deleteContentForward'&&start<input.value.length&&/\D/.test(input.value[start]))input.setSelectionRange(start,Math.min(input.value.length,start+2));
  });
  input.addEventListener('input',()=>{
    const position=input.selectionStart??input.value.length;
    const count=input.value.slice(0,position).replace(/\D/g,'').length;
    const formatted=formatDateDigits(input.value,{allowTime});
    if(input.value!==formatted){
      input.value=formatted;
      let caret=0,seen=0;
      while(caret<formatted.length&&seen<count){if(/\d/.test(formatted[caret]))seen++;caret++;}
      input.setSelectionRange(caret,caret);
    }
    input.setCustomValidity('');
  });
  return input;
}
