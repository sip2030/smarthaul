from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.auth.models import CustomUser
from apps.bookings.models import Booking


class RoutingEndpointsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.customer = CustomUser.objects.create_user(
            username='route_customer',
            email='route_customer@test.com',
            password='testpass123',
            role='customer',
        )
        self.booking = Booking.objects.create(
            customer=self.customer,
            service_type='transport',
            pickup='Yaba',
            destination='Lekki',
            price=Decimal('5000.00'),
            status='accepted',
            eta_minutes=18,
        )

    def test_route_estimate_returns_eta_and_polyline(self):
        response = self.client.get('/route/estimate?pickup=Yaba&destination=Lekki')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('eta_minutes', data)
        self.assertIn('polyline', data)
        self.assertEqual(data['route_status'], 'estimated')

    def test_location_search_returns_matching_locations(self):
        response = self.client.get('/route/search?query=lek')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(any(item['name'] == 'Lekki' for item in data['results']))

    def test_live_tracking_returns_booking_route(self):
        response = self.client.get(f'/tracking/{self.booking.id}/live')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['booking_id'], self.booking.id)
        self.assertEqual(data['route']['pickup'], 'Yaba')
        self.assertEqual(data['route']['destination'], 'Lekki')
        self.assertIn('timeline', data)
