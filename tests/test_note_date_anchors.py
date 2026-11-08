from datetime import datetime, timezone
from django.test import SimpleTestCase
from apps.ai_assistant.inputs import note_date_anchors


class NoteDateAnchorTests(SimpleTestCase):
    def test_anchors_follow_korean_source_date_and_month_boundary(self):
        saved=datetime(2026,10,31,14,30,tzinfo=timezone.utc)
        self.assertEqual(note_date_anchors(saved),{'어제':'2026-10-30','오늘':'2026-10-31','내일':'2026-11-01','모레':'2026-11-02'})

    def test_korean_midnight_and_missing_source_time(self):
        saved=datetime(2026,10,31,15,tzinfo=timezone.utc)
        self.assertEqual(note_date_anchors(saved)['오늘'],'2026-11-01')
        self.assertEqual(note_date_anchors(None),{})
