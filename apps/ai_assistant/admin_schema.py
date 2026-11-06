"""Closed report schema. Provider prose cannot supply numeric business totals."""
import re
import json
from collections import defaultdict
from django.conf import settings
from .inputs import sanitize
from .models import AINoteClassification, Feature
from .reports import SECTIONS, TITLES, GUIDE_DEFAULTS, GUIDE_CHOICES, LABELS, classification_key

VERSION='admin-v1'
BANNED=re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|https?://|www\.|<[^>]+>|\b01[016789][\s-]?\d{3,4}[\s-]?\d{4}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|성격|목소리|말투|순위|인과관계가|때문에.*향상',re.I)


def safe_text(value,limit=1200):
    return isinstance(value,str) and 0<len(value)<=limit and not BANNED.search(value) and not (settings.AI_CONFIG.api_key and settings.AI_CONFIG.api_key in value)


def validate(task,payload):
    if not isinstance(payload,dict):return None
    try:
        if len(json.dumps(payload,ensure_ascii=False).encode())>task.output_tokens_cap*4:return None
    except (TypeError,ValueError,RecursionError,UnicodeError):return None
    if set(payload)!={'feature','is_test','findings','classifications','actions','facts','guide_sections'}:return None
    if payload['feature']!=task.feature or payload['is_test'] is not task.is_test:return None
    if any(not isinstance(payload[k],list) or len(payload[k])>96 for k in ['findings','classifications','actions','facts']):return None
    records={r['source_id']:r for r in task.input_payload.get('records',[])}
    knowledge={r['source_id']:r for r in task.input_payload.get('knowledge',[])}
    prior={r['source_id']:r for r in task.input_payload.get('previous_coaching',[])+task.input_payload.get('older_actions',[])}
    evidence_text={sid:r['notes'] for sid,r in records.items()}
    evidence_text.update({sid:r['body'] for sid,r in knowledge.items()})
    evidence_text.update({sid:json.dumps(r,ensure_ascii=False) for sid,r in prior.items()})
    findings=[]; ignored=0
    for row in payload['findings']:
        if not isinstance(row,dict) or set(row)!={'section','text','source_ids','evidence'}:return None
        if row['section'] not in SECTIONS[task.feature] or not safe_text(row['text']) or re.search(r'\d',row['text']):return None
        if not isinstance(row['source_ids'],list) or not 1<=len(row['source_ids'])<=8 or not isinstance(row['evidence'],str) or not 1<=len(row['evidence'])<=500:return None
        if any(not isinstance(s,str) or s not in evidence_text for s in row['source_ids']):ignored+=1;continue
        if not any(row['evidence'] in evidence_text[s] for s in row['source_ids']):ignored+=1;continue
        # Staff guides use general questions and reviewed product facts only. Customer prose remains admin-only.
        if task.feature==Feature.TEAM_GUIDE:continue
        findings.append(row)
    classifications=[]
    for row in payload['classifications']:
        if not isinstance(row,dict) or set(row)!={'source_id','labels','evidence'}:return None
        sid=row['source_id']; labels=row['labels']; quote=row['evidence']
        if not isinstance(sid,str) or sid not in records or not isinstance(labels,list) or not 1<=len(labels)<=6 or any(not isinstance(x,str) or x not in LABELS for x in labels):ignored+=1;continue
        if not isinstance(quote,str) or not quote or len(quote)>500 or quote not in records[sid]['notes']:ignored+=1;continue
        accepted=[label for label in set(labels) if label in {'OTHER','UNSPECIFIED'} or any(word in quote for word in LABELS[label])]
        if len(accepted)!=len(set(labels)):ignored+=1
        if accepted:classifications.append({'source_id':sid,'labels':sorted(accepted),'evidence':quote})
    actions=[]
    for row in payload['actions']:
        if not isinstance(row,dict) or set(row)!={'text','source_ids','evidence','confirmed'} or type(row['confirmed']) is not bool:return None
        if not safe_text(row['text']) or re.search(r'\d',row['text']) or not isinstance(row['source_ids'],list) or not isinstance(row['evidence'],str):return None
        if not row['source_ids'] or any(not isinstance(s,str) or s not in evidence_text for s in row['source_ids']) or not row['evidence'] or not any(row['evidence'] in evidence_text[s] for s in row['source_ids']):ignored+=1;continue
        actions.append(row)
    guide_sections={}
    if not isinstance(payload['guide_sections'],dict) or set(payload['guide_sections'])-set(SECTIONS['TEAM_GUIDE']):return None
    for section,row in payload['guide_sections'].items():
        if not isinstance(row,dict) or set(row)!={'text','source_ids','evidence'}:return None
        if row['text'] not in GUIDE_CHOICES[section] or not isinstance(row['source_ids'],list) or not isinstance(row['evidence'],str):return None
        if row['source_ids'] and (any(not isinstance(s,str) or s not in records for s in row['source_ids']) or not row['evidence'] or not any(row['evidence'] in records[s]['notes'] for s in row['source_ids'])):ignored+=1;continue
        guide_sections[section]=row
    facts=[]
    for row in payload['facts']:
        if not isinstance(row,dict) or set(row)!={'source_id','quote'}:return None
        if not isinstance(row['source_id'],str) or row['source_id'] not in knowledge or not safe_text(row['quote'],2000) or row['quote'] not in knowledge[row['source_id']]['body']:ignored+=1;continue
        facts.append(row)
    return {'feature':task.feature,'is_test':task.is_test,'findings':findings,'classifications':classifications,'actions':actions,'facts':facts,'guide_sections':guide_sections,
            'limitations':(['테스트 전용 가짜 응답입니다. 운영 분석이 아닙니다.'] if task.is_test else ['AI 초안입니다. 근거와 현장 사실은 관리자가 확인해야 합니다.'])+['수치는 서버 전체 집계이며 고객 반응 분류는 분석 범위 내 중복 제거 고객 수입니다.'], 'unverified_items':ignored}


def finalize(task,result,payload):
    snapshot=task.report_snapshot.data
    payload.update({k:snapshot[k] for k in ['statistics','sampling','comparison','record_checks']})
    if task.feature==Feature.EMPLOYEE_COACHING and snapshot['comparison']['status']=='판단 불가':
        payload['findings']=[f for f in payload['findings'] if f['section']!='CHANGES']
        payload['limitations'].append('이전 코칭 이후 변화: 판단 불가. '+snapshot['comparison']['reason'])
    rows={r['source_id']:r for r in task.input_payload['records']}
    labels=defaultdict(set); analyzed=set();classified=set()
    for row in snapshot['cached_classifications']:
        classified.add(row['source_id']);analyzed.add(row['customer_id'])
        for label in row['labels']:labels[label].add(row['customer_id'])
    for row in payload['classifications']:
        classified.add(row['source_id']);record=rows[row['source_id']]; analyzed.add(record['customer_id'])
        for label in row['labels']:labels[label].add(record['customer_id'])
        AINoteClassification.objects.update_or_create(revision_id=row['source_id'],fingerprint=classification_key(row['source_id'],record['version']),defaults={'labels':row['labels'],'evidence':row['evidence']})
    payload['reaction_statistics']={'analyzed_customers':len(analyzed),'classified_groups':len(classified),'unclassified_groups':snapshot['sampling']['total_note_groups']-len(classified),'labels':{label:len(labels[label]) for label in LABELS},'overlapping_labels':True}
    if task.feature==Feature.TEAM_GUIDE:
        result.guide_body='\n\n'.join(TITLES[section]+'\n'+payload['guide_sections'].get(section,{}).get('text',text) for section,text in zip(SECTIONS[task.feature],GUIDE_DEFAULTS))
        if payload['facts']:result.guide_body+='\n\n검토된 현장 안내자료\n'+'\n'.join(f['quote'] for f in payload['facts'])
        else:result.guide_body+='\n\n상품 사실: 현장 담당자 확인 필요.'
    return payload


def fake(task):
    records=task.input_payload.get('records',[])
    findings=[]; classifications=[];actions=[]
    for r in records[:6]:
        quote=r['notes'][:80]
        labels=[label for label,words in LABELS.items() if words and any(w in quote for w in words)] or ['UNSPECIFIED']
        classifications.append({'source_id':r['source_id'],'labels':labels,'evidence':quote})
    if records and task.feature!=Feature.TEAM_GUIDE:
        r=records[0];quote=r['notes'][:80]
        for section in SECTIONS[task.feature]:
            findings.append({'section':section,'text':'기록을 바탕으로 고객에게 다시 확인할 사항을 검토하세요.','source_ids':[r['source_id']],'evidence':quote})
        if task.feature==Feature.EMPLOYEE_COACHING:actions=[{'text':'다음 상담에서 확인한 내용과 미확인 사항을 구분해 기록하세요.','source_ids':[r['source_id']],'evidence':quote,'confirmed':False}]
    guide_sections={}
    if task.feature==Feature.TEAM_GUIDE:
        guide_sections={section:{'text':GUIDE_CHOICES[section][0],'source_ids':[],'evidence':''} for section in SECTIONS[task.feature]}
        price=next((r for r in records if any(w in r['notes'] for w in LABELS['PRICE'])),None)
        if price:
            guide_sections['FAQ']={'text':GUIDE_CHOICES['FAQ'][1],'source_ids':[price['source_id']],'evidence':price['notes'][:80]}
            guide_sections['OBJECTIONS']={'text':GUIDE_CHOICES['OBJECTIONS'][1],'source_ids':[price['source_id']],'evidence':price['notes'][:80]}
    return {'feature':task.feature,'is_test':True,'findings':findings,'classifications':classifications,'actions':actions,'guide_sections':guide_sections,
            'facts':[{'source_id':r['source_id'],'quote':r['body'][:100]} for r in task.input_payload.get('knowledge',[])[:2]]}
