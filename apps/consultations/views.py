from django.http import JsonResponse
from django.views.decorators.http import require_GET
from apps.accounts.access import AccessError,require_role,actor_identity
from apps.accounts.models import User
from apps.common.http import api_errors,identifier
from apps.customers.access import current_access
from apps.customers.employee import optional_queue_identity
from apps.customers.models import Customer
from apps.customers.queries import visible_values
from apps.common.query_expressions import JSONSubset


@require_GET
@require_role()
@api_errors
def history(request,customer_id):
    optional_queue_identity(request)
    actor_identity(request)
    if set(request.GET)-{'assignment_id','kind','page'}:raise AccessError('VALIDATION_ERROR','이력 조회 조건을 확인해 주세요.',422)
    kind=request.GET.get('kind','callbacks')
    try:page=int(request.GET.get('page','1'))
    except ValueError:page=0
    if kind not in {'callbacks','consultations'} or not 1<=page<=1000000000:raise AccessError('VALIDATION_ERROR','이력 종류·페이지를 확인해 주세요.',422)
    aid=identifier(request.GET.get('assignment_id'),nullable=request.user.role==User.Role.ADMIN)
    customer=Customer.objects.select_related('current_assignment').filter(pk=customer_id).first()
    if not customer:raise AccessError('CUSTOMER_DELETED' if request.user.role==User.Role.ADMIN else 'FORBIDDEN','고객정보를 사용할 수 없습니다.',409 if request.user.role==User.Role.ADMIN else 403)
    current_access(request.user,customer,aid,allow_trash=True)
    if kind=='callbacks':
        query=customer.callbacks.select_related('created_by','updated_by','completed_by').order_by('-created_at','-pk')
        serialize=lambda row:{'id':str(row.pk),'due_at':row.due_at.isoformat(),'status':row.status,'version':row.version,
            'created_at':row.created_at.isoformat(),'created_by':row.created_by.name,'updated_at':row.updated_at.isoformat(),'updated_by':row.updated_by.name,
            'completed_at':row.completed_at.isoformat() if row.completed_at else None,'completed_by':row.completed_by.name if row.completed_by_id else None,'cancelled_at':row.cancelled_at.isoformat() if row.cancelled_at else None}
    else:
        query=customer.consultation_revisions.order_by('-saved_at','-pk')
        if request.user.role != User.Role.ADMIN:
            query=query.exclude(changed_fields=['admin_notes'])
        query=query.annotate(history_before=JSONSubset('before_values','changed_fields',empty_means_all=True),
                             history_after=JSONSubset('after_values','changed_fields',empty_means_all=True)).values(
            'pk','saved_at','actor__name','source','customer_version','assignment_id','changed_fields','history_before','history_after')
        def serialize(row):
            return {'id':str(row['pk']),'saved_at':row['saved_at'].isoformat(),'actor':row['actor__name'],'source':row['source'],
                'customer_version':row['customer_version'],'assignment_id':str(row['assignment_id']) if row['assignment_id'] else None,'changed_fields':row['changed_fields'],
                'before_values':row['history_before'],'after_values':row['history_after']}
    total=query.count()
    return JsonResponse({'kind':kind,'page':page,'page_size':50,'total':total,'has_next':page*50<total,'data':[visible_values(serialize(row), admin=request.user.role==User.Role.ADMIN) for row in query[(page-1)*50:page*50]]})
