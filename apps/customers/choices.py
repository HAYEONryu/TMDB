"""Current editable choices; historical stored values remain readable."""
CALL_RESULTS = {'INTERESTED':'가망고객', 'DELETE_REQUEST':'삭제 요망', 'REJECTED':'거절', 'NEXT_SITE':'다음현장 연락 요청', 'NO_ANSWER':'부재'}
CONTRACT_STATUSES = {'SUBSCRIBED':'청약', 'SUB_CANCELLED':'청약해지', 'CONTRACT_CANCELLED':'계약해지', 'CONTRACTED':'계약'}
ROUTES = {value:value for value in ['티엠','사이드','대표콜','개인관리','워킹','재방']}
HOUSING_STATUSES = {value:value for value in ['무주택','1주택','다주택','생애최초']}
CURRENT_CHOICES = {'call_result':CALL_RESULTS, 'contract_status':CONTRACT_STATUSES, 'route':ROUTES, 'housing_status':HOUSING_STATUSES}
FIELD_LABELS = {'call_result':'통화결과','contract_status':'계약여부','route':'루트','housing_status':'주택보유상황'}


def customer_schema():
    from .models import Customer
    return {**{field:{'UNKNOWN' if field=='contract_status' else '':'-',**choices}
               for field,choices in CURRENT_CHOICES.items()}, '_legacy': {
        'call_result':dict(Customer.CallResult.choices), 'contract_status':dict(Customer.ContractStatus.choices)}}


def invalid_import_choice(values):
    for field, choices in CURRENT_CHOICES.items():
        value = values.get(field)
        if value in (None, '') or (field == 'contract_status' and value == 'UNKNOWN'):
            continue
        if value not in choices:
            return f'{FIELD_LABELS[field]}은 지정된 선택값 중 하나를 입력해 주세요.'
    return None
