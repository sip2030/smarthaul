from decimal import Decimal

from django.test import TestCase
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient

from apps.analytics.models import ActivityLog
from apps.auth.models import CustomUser
from apps.vendors.models import Vendor, VendorListing, VendorOrder


class VendorResubmissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.vendor_user = CustomUser.objects.create_user(
            username='vendor_verify',
            email='vendor_verify@test.com',
            password='testpass123',
            role='vendor',
        )
        self.admin = CustomUser.objects.create_user(
            username='vendor_admin',
            email='vendor_admin@test.com',
            password='testpass123',
            role='admin',
        )

    def test_rejected_vendor_can_resubmit_profile(self):
        vendor = Vendor.objects.create(
            user=self.vendor_user,
            name='Vendor One',
            category='Logistics',
            location='Lagos',
            onboarding_status='rejected',
            document_status='rejected',
            onboarding_notes='Need clearer documents',
        )

        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post('/api/vendors/resubmit/', {
            'name': 'Vendor One Updated',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vendor.refresh_from_db()
        self.assertEqual(vendor.onboarding_status, 'pending_review')
        self.assertEqual(vendor.document_status, 'pending')
        self.assertEqual(vendor.name, 'Vendor One Updated')
        self.assertEqual(vendor.onboarding_notes, '')

    def test_admin_can_reject_vendor_and_note_reason(self):
        vendor = Vendor.objects.create(
            user=self.vendor_user,
            name='Vendor One',
            category='Logistics',
            location='Lagos',
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f'/api/vendors/{vendor.id}/reject/',
            {'reason': 'Documents unclear'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        vendor.refresh_from_db()
        self.assertEqual(vendor.onboarding_status, 'rejected')
        self.assertEqual(vendor.onboarding_notes, 'Documents unclear')
        self.assertTrue(ActivityLog.objects.filter(action='vendor_verification_rejected', target_id=str(vendor.id)).exists())


class VendorMarketplaceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.vendor_user = CustomUser.objects.create_user(
            username='market_vendor',
            email='market_vendor@test.com',
            password='testpass123',
            role='vendor',
        )
        self.customer = CustomUser.objects.create_user(
            username='market_customer',
            email='market_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.admin = CustomUser.objects.create_user(
            username='market_admin',
            email='market_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.vendor = Vendor.objects.create(
            user=self.vendor_user,
            name='Market Vendor',
            category='Logistics',
            location='Lagos',
            onboarding_status='approved',
            document_status='approved',
        )

    def test_vendor_can_create_listing(self):
        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post('/api/vendors/listings/', {
            'title': 'Express Delivery',
            'description': 'Same-day delivery service',
            'listing_type': 'service',
            'category': 'Logistics',
            'price': '5000.00',
            'unit_label': 'per job',
            'quantity_available': 10,
            'is_active': True,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VendorListing.objects.count(), 1)
        listing = VendorListing.objects.first()
        self.assertEqual(listing.vendor, self.vendor)
        self.assertEqual(listing.title, 'Express Delivery')

    def test_customer_only_sees_active_approved_listings(self):
        active_listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Active Service',
            description='Available to book',
            listing_type='service',
            category='Logistics',
            price=Decimal('2500.00'),
            quantity_available=5,
            is_active=True,
        )
        VendorListing.objects.create(
            vendor=self.vendor,
            title='Hidden Service',
            description='Not active',
            listing_type='service',
            category='Logistics',
            price=Decimal('3000.00'),
            quantity_available=2,
            is_active=False,
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/vendors/listings/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], active_listing.id)

    def test_vendor_can_unpublish_and_publish_listing(self):
        listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Toggle Service',
            description='Can be toggled',
            listing_type='service',
            category='Logistics',
            price=Decimal('3000.00'),
            quantity_available=3,
            is_active=True,
        )

        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post(f'/api/vendors/listings/{listing.id}/unpublish/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listing.refresh_from_db()
        self.assertFalse(listing.is_active)

        response = self.client.post(f'/api/vendors/listings/{listing.id}/publish/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listing.refresh_from_db()
        self.assertTrue(listing.is_active)

    def test_customer_cannot_edit_vendor_listing(self):
        listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Protected Listing',
            description='Only vendor can edit',
            listing_type='service',
            category='Logistics',
            price=Decimal('3000.00'),
            quantity_available=4,
            is_active=True,
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.patch(
            f'/api/vendors/listings/{listing.id}/',
            {'title': 'Hijacked Listing'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        listing.refresh_from_db()
        self.assertEqual(listing.title, 'Protected Listing')

    def test_admin_can_remove_listing(self):
        listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Flagged Listing',
            description='Needs moderation',
            listing_type='service',
            category='Logistics',
            price=Decimal('3000.00'),
            quantity_available=4,
            is_active=True,
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(
            f'/api/vendors/listings/{listing.id}/remove/',
            {'reason': 'Policy violation'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        listing.refresh_from_db()
        self.assertFalse(listing.is_active)


class VendorBrowsingTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='browse_customer',
            email='browse_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.vendor_one_user = CustomUser.objects.create_user(
            username='browse_vendor_one',
            email='browse_vendor_one@test.com',
            password='testpass123',
            role='vendor',
        )
        self.vendor_two_user = CustomUser.objects.create_user(
            username='browse_vendor_two',
            email='browse_vendor_two@test.com',
            password='testpass123',
            role='vendor',
        )
        self.vendor_one = Vendor.objects.create(
            user=self.vendor_one_user,
            name='Alpha Logistics',
            category='Logistics',
            location='Lagos Island',
            rating=4.9,
            onboarding_status='approved',
            document_status='approved',
        )
        self.vendor_two = Vendor.objects.create(
            user=self.vendor_two_user,
            name='Bravo Delivery',
            category='Delivery',
            location='Ikeja',
            rating=4.2,
            onboarding_status='approved',
            document_status='approved',
        )
        Vendor.objects.create(
            user=CustomUser.objects.create_user(
                username='unapproved_vendor',
                email='unapproved_vendor@test.com',
                password='testpass123',
                role='vendor',
            ),
            name='Hidden Vendor',
            category='Logistics',
            location='Lagos',
            rating=5.0,
            onboarding_status='pending_review',
            document_status='pending',
        )

    def test_customer_can_filter_vendors_by_category_location_and_rating(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/vendors/?category=Logistics&location=lagos&min_rating=4.5')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) else payload

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], self.vendor_one.id)

    def test_customer_only_sees_approved_vendors(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/vendors/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) else payload
        vendor_ids = {item['id'] for item in results}

        self.assertIn(self.vendor_one.id, vendor_ids)
        self.assertIn(self.vendor_two.id, vendor_ids)
        self.assertTrue(all(item['onboarding_status'] == 'approved' for item in results))


class VendorOrderTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='order_customer',
            email='order_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.vendor_user = CustomUser.objects.create_user(
            username='order_vendor',
            email='order_vendor@test.com',
            password='testpass123',
            role='vendor',
        )
        self.admin = CustomUser.objects.create_user(
            username='order_admin',
            email='order_admin@test.com',
            password='testpass123',
            role='admin',
        )
        self.vendor = Vendor.objects.create(
            user=self.vendor_user,
            name='Order Vendor',
            category='Delivery',
            location='Lagos',
            rating=4.6,
            onboarding_status='approved',
            document_status='approved',
        )
        self.listing = VendorListing.objects.create(
            vendor=self.vendor,
            title='Parcel Delivery',
            description='Fast parcel delivery',
            listing_type='service',
            category='Delivery',
            price=Decimal('3000.00'),
            quantity_available=25,
            is_active=True,
        )

    def test_customer_can_place_vendor_order(self):
        self.client.force_authenticate(user=self.customer)
        response = self.client.post('/api/vendors/orders/', {
            'listing': self.listing.id,
            'quantity': 2,
            'customer_notes': 'Deliver between 2pm and 4pm',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(VendorOrder.objects.count(), 1)
        order = VendorOrder.objects.first()
        self.assertEqual(order.customer, self.customer)
        self.assertEqual(order.vendor, self.vendor)
        self.assertEqual(order.total_amount, Decimal('6000.00'))

    def test_vendor_can_update_order_status(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='pending',
        )

        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post(f'/api/vendors/orders/{order.id}/update_status/', {
            'status': 'preparing',
            'vendor_notes': 'Packing order now',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, 'preparing')
        self.assertEqual(order.vendor_notes, 'Packing order now')

    def test_customer_only_sees_own_orders(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='pending',
        )
        other_customer = CustomUser.objects.create_user(
            username='other_order_customer',
            email='other_order_customer@test.com',
            password='testpass123',
            role='customer',
        )

        self.client.force_authenticate(user=other_customer)
        response = self.client.get('/api/vendors/orders/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) else payload
        self.assertEqual(results, [])

        self.client.force_authenticate(user=self.customer)
        response = self.client.get('/api/vendors/orders/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        results = payload['results'] if isinstance(payload, dict) else payload
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['id'], order.id)

    def test_completed_order_updates_vendor_totals(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='preparing',
        )

        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post(f'/api/vendors/orders/{order.id}/update_status/', {
            'status': 'completed',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.vendor.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(order.status, 'completed')
        self.assertIsNotNone(order.fulfilled_at)
        self.assertEqual(self.vendor.total_completed_orders, 1)
        self.assertEqual(self.vendor.total_earnings, Decimal('3000.00'))

    def test_customer_can_submit_feedback_for_completed_order(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='completed',
            fulfilled_at=now(),
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/vendors/orders/{order.id}/submit_feedback/', {
            'rating': 5,
            'feedback_comment': 'Excellent service and timely delivery.',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.vendor.refresh_from_db()
        self.assertEqual(order.rating, 5)
        self.assertEqual(order.feedback_comment, 'Excellent service and timely delivery.')
        self.assertIsNotNone(order.feedback_submitted_at)
        self.assertEqual(self.vendor.rating, 5.0)

    def test_customer_cannot_submit_feedback_before_completion(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='preparing',
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/vendors/orders/{order.id}/submit_feedback/', {
            'rating': 4,
            'feedback_comment': 'Too early to rate.',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        order.refresh_from_db()
        self.assertIsNone(order.rating)

    def test_customer_can_cancel_vendor_order(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='accepted',
        )

        self.client.force_authenticate(user=self.customer)
        response = self.client.post(f'/api/vendors/orders/{order.id}/cancel_order/', {
            'reason': 'Changed my mind',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(order.cancelled_by, 'customer')
        self.assertEqual(order.cancellation_reason, 'Changed my mind')
        self.assertIsNotNone(order.cancelled_at)
        self.assertEqual(order.refund_status, 'pending_review')
        self.assertEqual(order.refund_amount, Decimal('3000.00'))
        self.assertEqual(order.refund_requested_by, 'customer')
        self.assertIsNotNone(order.refund_requested_at)

    def test_vendor_can_cancel_vendor_order(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='accepted',
        )

        self.client.force_authenticate(user=self.vendor_user)
        response = self.client.post(f'/api/vendors/orders/{order.id}/cancel_order/', {
            'reason': 'Service unavailable',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.status, 'cancelled')
        self.assertEqual(order.cancelled_by, 'vendor')
        self.assertEqual(order.cancellation_reason, 'Service unavailable')
        self.assertEqual(order.refund_status, 'pending_review')
        self.assertEqual(order.refund_amount, Decimal('3000.00'))
        self.assertEqual(order.refund_requested_by, 'vendor')
        self.assertIsNotNone(order.refund_requested_at)

    def test_admin_can_review_cancelled_order_refund(self):
        order = VendorOrder.objects.create(
            customer=self.customer,
            vendor=self.vendor,
            listing=self.listing,
            quantity=1,
            unit_price=Decimal('3000.00'),
            total_amount=Decimal('3000.00'),
            status='cancelled',
            cancelled_by='vendor',
            cancellation_reason='Service unavailable',
            refund_status='pending_review',
            refund_amount=Decimal('3000.00'),
            refund_requested_by='vendor',
            refund_requested_at=now(),
        )

        self.client.force_authenticate(user=self.admin)
        response = self.client.post(f'/api/vendors/orders/{order.id}/review_refund/', {
            'refund_status': 'processed',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        order.refresh_from_db()
        self.assertEqual(order.refund_status, 'processed')
        self.assertIsNotNone(order.refund_reviewed_at)
        self.assertTrue(ActivityLog.objects.filter(action='vendor_order_refund_reviewed', target_id=str(order.id)).exists())
        self.assertTrue(
            order.customer.notifications.filter(category='payment', title='Vendor order refund processed').exists()
        )
