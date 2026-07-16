from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.providers.models import Provider


class ProviderVerificationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.provider_user = CustomUser.objects.create_user(
            username='provider_verify',
            email='provider_verify@test.com',
            password='testpass123',
            role='provider',
        )
        self.admin = CustomUser.objects.create_user(
            username='provider_admin',
            email='provider_admin@test.com',
            password='testpass123',
            role='admin',
        )

    def test_provider_initial_submission_sets_pending_review(self):
        self.client.force_authenticate(user=self.provider_user)
        response = self.client.post('/api/providers/', {
            'service_area': 'Lagos',
            'vehicle_type': 'Truck',
            'license_number': 'LIC-100',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        provider = Provider.objects.get(user=self.provider_user)
        self.assertEqual(provider.verification_status, 'pending_review')
        self.assertIsNotNone(provider.verification_submitted_at)

    def test_provider_resubmit_reopens_rejected_verification(self):
        provider = Provider.objects.create(
            user=self.provider_user,
            service_area='Lagos',
            vehicle_type='Truck',
            license_number='LIC-100',
            verification_status='rejected',
            verification_notes='Document unclear',
        )

        self.client.force_authenticate(user=self.provider_user)
        response = self.client.post('/api/providers/resubmit/', {
            'license_number': 'LIC-200',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        provider.refresh_from_db()
        self.assertEqual(provider.verification_status, 'pending_review')
        self.assertEqual(provider.license_number, 'LIC-200')
        self.assertEqual(provider.verification_notes, '')

    def test_admin_can_approve_provider_verification(self):
        provider = Provider.objects.create(
            user=self.provider_user,
            service_area='Lagos',
            vehicle_type='Truck',
            license_number='LIC-100',
            verification_status='pending_review',
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/providers/{provider.id}/approve/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        provider.refresh_from_db()
        self.assertEqual(provider.verification_status, 'approved')
        self.assertTrue(ActivityLog.objects.filter(action='provider_verification_approved', target_id=str(provider.id)).exists())
