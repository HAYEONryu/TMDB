"""Signed continuations; never silently offset through a changed result set.

No customer data is stored in the browser or a new persistence layer. Each read
revalidates the ordered IDs in the same database snapshot as the returned rows.
"""
import hashlib
import json
from django.core import signing
from apps.accounts.access import AccessError

SALT='tm.customer-continuation.v1'


def continuation_page(actor,params,ordered,size,now):
    query={k:params[k] for k in sorted(params) if k not in {'cursor','page'}}
    binding=hashlib.sha256(json.dumps([str(actor.pk),actor.role,query],sort_keys=True).encode()).hexdigest()
    digest=hashlib.sha256()
    total=0
    for pk in ordered.values_list('pk',flat=True).iterator(chunk_size=2000):
        digest.update(pk.bytes);total+=1
    from apps.customers.queries import KST
    proof={'binding':binding,'digest':digest.hexdigest(),'day':now.astimezone(KST).date().isoformat()}
    page=1
    if params.get('cursor'):
        try:
            previous=signing.loads(params['cursor'],salt=SALT,max_age=1200)
            page=previous['page']
            if type(page) is not int or page<2 or any(previous.get(k)!=v for k,v in proof.items()):raise ValueError()
        except (signing.BadSignature,ValueError,KeyError,TypeError):
            raise AccessError('LIST_CHANGED','고객 목록 또는 순서가 변경되었거나 조회가 만료되었습니다. 목록 새로고침으로 처음부터 다시 조회해 주세요.',409)
    elif params.get('page','1')!='1':
        raise AccessError('VALIDATION_ERROR','이어 읽기는 서버의 다음 조회 정보를 사용해 주세요.',422)
    next_cursor=signing.dumps({**proof,'page':page+1},salt=SALT) if page*size<total else None
    return page,{'next_cursor':next_cursor,'has_more':next_cursor is not None}
