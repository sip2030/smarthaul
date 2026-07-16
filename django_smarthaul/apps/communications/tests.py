from decimal import Decimal

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.bookings.models import Booking
from apps.communications.models import Notification, SafetyReport, SupportCase


class CommunicationsApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='comm_customer',
            email='comm_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.admin = CustomUser.objects.create_user(
            username='comm_admin',
            email='comm_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='A',
            destination='B',
            price=Decimal('50.00'),
            status='pending',
        )

    def test_ai_assistant_creates_escalated_support_case_for_complex_issue(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/support-cases/assistant/', {'question': 'My driver is missing and I need urgent help', 'booking_id': self.booking.id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()['needs_human_support'])
        self.assertTrue(SupportCase.objects.filter(user=self.customer).exists())
        self.assertTrue(Notification.objects.filter(user=self.customer, category='support').exists())

    def test_customer_can_open_support_case_for_own_booking(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/support-cases/', {
            'booking': self.booking.id,
            'subject': 'Refund question',
            'description': 'I want to understand the refund timeline.',
            'priority': 'normal',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SupportCase.objects.count(), 1)

    def test_unread_notifications_can_be_counted_and_marked_read(self):
        notification = Notification.objects.create(
            user=self.customer,
            category='booking',
            title='Booking update',
            body='Your booking is pending.',
            booking_id=self.booking.id,
        )
        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/notifications/unread_count/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['count'], 1)

        response = self.client.post(f'/api/notifications/{notification.id}/mark_read/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.read_at)

    def test_customer_can_file_safety_report_and_admin_can_resolve_with_restriction(self):
        self.client.force_authenticate(user=self.customer)
        report = self.client.post('/api/safety-reports/', {
            'booking': self.booking.id,
            'target_user': self.customer.id,
            'report_type': 'harassment',
            'target_type': 'booking',
            'target_name': 'Booking incident',
            'description': 'Unsafe behavior during the booking.',
            'evidence_url': 'https://example.com/evidence.jpg',
        }, format='json')

        self.assertEqual(report.status_code, status.HTTP_201_CREATED)
        self.assertEqual(SafetyReport.objects.count(), 1)

        safety_report = SafetyReport.objects.first()
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/safety-reports/{safety_report.id}/mark_under_review/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        response = self.client.post(f'/api/safety-reports/{safety_report.id}/resolve/', {
            'moderation_action': 'restrict_account',
            'moderator_notes': 'Temporary restriction pending additional review.',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.customer.refresh_from_db()
        self.assertEqual(self.customer.account_status, 'restricted')
        self.assertTrue(Notification.objects.filter(user=self.admin, category='moderation').exists())
        self.assertTrue(ActivityLog.objects.filter(action='safety_report_under_review', target_id=str(safety_report.id)).exists())
        self.assertTrue(ActivityLog.objects.filter(action='safety_report_resolved', target_id=str(safety_report.id)).exists())

    def test_report_can_store_unavailable_entity_reference_without_foreign_keys(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/safety-reports/', {
            'report_type': 'fraud',
            'target_type': 'vendor',
            'target_name': 'Vendor that no longer exists',
            'target_reference': 'vendor-legacy-42',
            'linked_entity_available': False,
            'linked_entity_note': 'Vendor profile was removed before report submission.',
            'description': 'The vendor profile was unavailable when I tried to report it.',
            'evidence_url': 'https://example.com/screenshot.png',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        report = response.json()
        self.assertFalse(report['linked_entity_available'])
        self.assertEqual(report['target_reference'], 'vendor-legacy-42')

        saved_report = SafetyReport.objects.get(id=report['id'])
        self.assertFalse(saved_report.linked_entity_available)
        self.assertEqual(saved_report.linked_entity_note, 'Vendor profile was removed before report submission.')
