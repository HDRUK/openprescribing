from django.test import TestCase
from pipeline.models import TaskLog


class TestImportWarningMiddleware(TestCase):
    def test_when_import_in_progress(self):
        TaskLog.objects.create(year=2017, month=7, task_name="task1")
        response = self.client.get("/")
        self.assertContains(response, "We are currently importing")

    def test_when_import_not_in_progress(self):
        TaskLog.objects.create(year=2017, month=7, task_name="task1")
        TaskLog.objects.create(year=2017, month=7, task_name="fetch_and_import")
        response = self.client.get("/")
        self.assertContains(response, "We are currently importing")
