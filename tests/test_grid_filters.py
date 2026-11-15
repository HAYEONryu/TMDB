import json
from datetime import datetime
from django.test import TestCase,override_settings
from apps.callbacks.models import Callback
from apps.customers.choices import customer_schema
from apps.customers.queries import KST
from apps.customers.services import update_row
from tests.helpers import TEST_HASHERS,login
from tests.test_p4 import Fixtures


@override_settings(PASSWORD_HASHERS=TEST_HASHERS)
class GridFilterTests(Fixtures,TestCase):
    def setUp(self):
        self.prepare();self.blank,self.filled=self.customers(2)
        self.blank.customer_name='';self.blank.save();self.assign(self.blank);self.assign(self.filled)
        self.filled.notes='핵심 상담';self.filled.memo='일반 비고';self.filled.admin_notes='SYNTHETIC_PRIVATE';self.filled.residence='서울'
        self.filled.route='티엠';self.filled.housing_status='무주택';self.filled.contract_status='CONTRACTED';self.filled.call_result='INTERESTED'
        self.filled.visit_at=datetime(2026,11,13,23,59,59,tzinfo=KST);self.filled.save()
        Callback.objects.create(customer=self.filled,due_at=self.filled.visit_at,created_by=self.employee,updated_by=self.employee)
        self.client=login(self.employee)

    def rows(self,filters,client=None,**extra):
        response=(client or self.client).get('/api/customers',{'site_id':str(self.site.pk),'filters':json.dumps(filters),**extra})
        self.assertEqual(response.status_code,200)
        return {row['id'] for row in response.json()['data']}

    def test_blank_and_filled_for_choice_text_and_dates_and_combination(self):
        for field in ['customer_name','contract_status','call_result','housing_status','route','notes','memo','residence','visit_at','callback_due_at']:
            self.assertEqual(self.rows({field:{'blank':True}}),{str(self.blank.pk)},field)
            self.assertEqual(self.rows({field:{'blank':False}}),{str(self.filled.pk)},field)
        self.assertEqual(self.rows({'notes':{'blank':True},'route':{'values':['티엠'],'exclude':False}}),set())
        self.assertEqual(self.rows({'visit_at':{'from':'2026-11-13','to':'2026-11-13'}}),{str(self.filled.pk)})

    def test_private_field_and_invalid_blank_conditions_rejected_and_scope_preserved(self):
        self.assertEqual(self.client.get('/api/customers',{'filters':json.dumps({'admin_notes':{'blank':True}})}).status_code,422)
        admin=login(self.admin)
        self.assertEqual(self.rows({'admin_notes':{'blank':False}},admin),{str(self.filled.pk)})
        for value in [1,'true',None,[]]:
            self.assertEqual(self.client.get('/api/customers',{'filters':json.dumps({'notes':{'blank':value}})}).status_code,422)
        foreign=self.customers(offset=10)[0];self.assign(foreign,self.other)
        self.assertEqual(self.rows({'notes':{'blank':True}}),{str(self.blank.pk)})

    def test_all_fixed_choices_can_return_to_empty_without_storing_display_dash(self):
        values={'call_result':'INTERESTED','contract_status':'CONTRACTED','route':'티엠','housing_status':'무주택'}
        for actor in [self.admin,self.employee]:
            self.blank.refresh_from_db()
            self.assertTrue(update_row(actor,self.mutation(self.blank)|{'changes':values})['ok'])
            self.blank.refresh_from_db()
            result=update_row(actor,self.mutation(self.blank)|{'changes':{'call_result':'','contract_status':'UNKNOWN','route':'','housing_status':''}})
            self.assertTrue(result['ok']);self.assertEqual(result['row']['call_result'],None)
            self.assertEqual(result['row']['contract_status'],'UNKNOWN')
            self.assertEqual((result['row']['route'],result['row']['housing_status']),('',''))
        schema=customer_schema()
        for field in values:self.assertEqual(next(iter(schema[field].values())),'-')

    def test_phone_candidates_accept_display_format_and_stay_scoped(self):
        foreign=self.customers(offset=10)[0];self.assign(foreign,self.other)
        response=self.client.get('/api/customers/filter-options',{'site_id':str(self.site.pk),'field':'phone_normalized','option_q':'010-8000-0000'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['values'],[self.blank.phone_normalized])
        response=self.client.get('/api/customers/filter-options',{'site_id':str(self.site.pk),'field':'phone_normalized','option_q':foreign.phone_normalized})
        self.assertEqual(response.json()['total'],0)
        response=self.client.get('/api/customers/filter-options',{'site_id':str(self.site.pk),'field':'phone_normalized','option_q':'---'})
        self.assertEqual(response.json()['total'],0)

    def test_symbol_only_search_never_expands_to_every_phone(self):
        for actor in [self.admin,self.employee]:
            client=login(actor)
            for term in ['---','-',' - - ','...','()']:
                self.assertEqual(self.rows({},client,q=term),set())
            self.assertEqual(self.rows({},client,q='010-8000-0001'),{str(self.filled.pk)})
            self.assertEqual(len(self.rows({},client,q='   ')),2)
        self.blank.customer_name='---';self.blank.save(update_fields=['customer_name'])
        self.assertEqual(self.rows({},q='---'),{str(self.blank.pk)})

    def test_callback_server_presets_midnight_overdue_overlap_and_completed_exclusion(self):
        from datetime import timedelta
        from unittest.mock import patch
        now=datetime(2026,11,15,10,30,tzinfo=KST)
        start=now.replace(hour=0,minute=0)
        due=[start-timedelta(microseconds=1),start,now-timedelta(microseconds=1),now,
             start+timedelta(days=1)-timedelta(microseconds=1),start+timedelta(days=1)]
        callbacks=self.customers(len(due),offset=20)
        for row,at in zip(callbacks,due):
            self.assign(row,at=start-timedelta(days=2))
            Callback.objects.create(customer=row,due_at=at,created_by=self.employee,updated_by=self.employee)
        completed=self.customers(offset=40)[0];self.assign(completed,at=start-timedelta(days=2))
        Callback.objects.create(customer=completed,due_at=start,status='COMPLETED',completed_at=now,
            completed_by=self.employee,created_by=self.employee,updated_by=self.employee)
        # Existing fixture has a pending callback from two days earlier.
        with patch('apps.customers.queries.timezone.now',return_value=now):
            for actor in [self.admin,self.employee]:
                client=login(actor)
                today=self.rows({'callback_due_at':{'preset':'today'}},client)
                self.assertEqual(today,{str(row.pk) for row in callbacks[1:5]})
                overdue=self.rows({'callback_due_at':{'preset':'overdue'}},client)
                self.assertEqual(overdue,{str(row.pk) for row in callbacks[:3]}|{str(self.filled.pk)})
                self.assertEqual(today&overdue,{str(row.pk) for row in callbacks[1:3]})
                self.assertEqual(self.rows({'callback_due_at':{'from':'2026-11-15','to':'2026-11-15'}},client),today)
            mine=self.rows({'callback_due_at':{'preset':'today'}},view='today')
            self.assertEqual(mine,{str(row.pk) for row in callbacks[1:5]})
        with patch('apps.customers.queries.timezone.now',return_value=start):
            self.assertIn(str(callbacks[1].pk),self.rows({'callback_due_at':{'preset':'today'}}))
            self.assertNotIn(str(callbacks[1].pk),self.rows({'callback_due_at':{'preset':'overdue'}}))
        with patch('apps.customers.queries.timezone.now',return_value=start+timedelta(days=1)):
            # Exercise the query directly so moving the clock to tomorrow does
            # not also expire the HTTP client's login session.
            from apps.customers.queries import customer_list
            result=customer_list(self.employee,{'site_id':str(self.site.pk),'filters':json.dumps({'callback_due_at':{'preset':'today'}})})
            self.assertEqual({row['id'] for row in result['data']},{str(callbacks[5].pk)})

    def test_preset_validation_and_staff_assignee_filters_and_candidates_rejected(self):
        for field,value in [('visit_at',{'preset':'today'}),('callback_due_at',{'preset':'week'}),
                            ('callback_due_at',{'preset':[]}),('callback_due_at',{'preset':'today','to':'2026-11-15'}),
                            ('assignee_name',{'blank':False})]:
            self.assertEqual(self.client.get('/api/customers',{'filters':json.dumps({field:value})}).status_code,422)
        self.assertEqual(self.client.get('/api/customers/filter-options',{'field':'assignee_name'}).status_code,422)
        self.assertEqual(self.rows({'assignee_name':{'values':[self.employee.name]}},login(self.admin)),{str(self.blank.pk),str(self.filled.pk)})

    def test_name_partial_phone_whitespace_and_cross_field_intersection_on_each_view(self):
        self.blank.customer_name='가나다 고객';self.blank.save()
        for actor,view in [(self.admin,'all'),(self.employee,'mine'),(self.employee,'today')]:
            client=login(actor)
            for term in ['010-8000-0001','010 8000 0001','010 - 8000 - 0001']:
                self.assertEqual(self.rows({},client,q=term,view=view),{str(self.filled.pk)})
            self.assertEqual(self.rows({},client,q='나다',view=view),{str(self.blank.pk)})
            self.assertEqual(self.rows({'call_result':{'values':['INTERESTED','NO_ANSWER']}},client,q='나다',view=view),set())
            self.assertEqual(self.rows({'call_result':{'values':['INTERESTED','NO_ANSWER']}},client,q='0001',view=view),{str(self.filled.pk)})
