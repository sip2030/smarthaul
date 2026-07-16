from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.communications.models import Notification


class UserAccountControlTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = CustomUser.objects.create_user(
            username='auth_admin',
            email='auth_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.customer = CustomUser.objects.create_user(
            username='auth_customer',
            email='auth_customer@test.com',
            password='testpass123',
            role='customer',
        )

    def test_admin_can_warn_account_and_log_activity(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f'/api/auth/users/{self.customer.id}/warn_account/',
            {'reason': 'Repeated abusive language in chat'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(ActivityLog.objects.filter(action='account_warned', target_id=str(self.customer.id)).exists())
        self.assertTrue(Notification.objects.filter(user=self.customer, category='moderation', title='Account warning issued').exists())
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.account_status, 'active')

    def test_admin_can_ban_account_and_log_activity(self):
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f'/api/auth/users/{self.customer.id}/ban_account/',
            {'reason': 'Fraudulent activity'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.account_status, 'banned')
        self.assertEqual(self.customer.account_restricted_reason, 'Fraudulent activity')
        self.assertTrue(ActivityLog.objects.filter(action='account_banned', target_id=str(self.customer.id)).exists())
        self.assertTrue(Notification.objects.filter(user=self.customer, category='moderation', title='Account banned').exists())
