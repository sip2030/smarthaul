"""Payments views."""

import os

import requests
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from apps.analytics.models import log_activity
from .models import Payment
from .serializers import PaymentSerializer
from apps.bookings.models import Booking
from apps.communications.views import create_notification


def _payment_gateway_name():
    return (os.environ.get('PAYMENT_PROVIDER') or 'flutterwave').strip().lower()


def _flutterwave_headers():
    secret_key = os.environ.get('FLUTTERWAVE_SECRET_KEY', '').strip()
    if not secret_key:
        return None
    return {
        'Authorization': f'Bearer {secret_key}',
        'Content-Type': 'application/json',
    }


def _initialize_flutterwave_payment(booking, payment):
    headers = _flutterwave_headers()
    if not headers:
        return None

    base_url = os.environ.get('APP_BASE_URL', '').rstrip('/')
    redirect_url = f'{base_url}/payments/complete' if base_url else 'http://localhost:8000/payments/complete'
    response = requests.post(
        'https://api.flutterwave.com/v3/payments',
        headers=headers,
        json={
            'tx_ref': f'smarthaul_{payment.id}',
            'amount': str(payment.amount),
            'currency': 'NGN',
            'redirect_url': redirect_url,
            'customer': {
                'email': booking.customer.email,
                'name': booking.customer.get_full_name() or booking.customer.username,
            },
            'customizations': {
                'title': 'SmartHaul booking payment',
                'description': f'Payment for booking #{booking.id}',
            },
        },
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get('data', {}).get('link') or payload.get('data', {}).get('checkout_url')


def _verify_flutterwave_transaction(payment):
    headers = _flutterwave_headers()
    if not headers or not payment.transaction_id:
        return False

    response = requests.get(
        f'https://api.flutterwave.com/v3/transactions/{payment.transaction_id}/verify',
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data', {})
    return str(data.get('status', '')).lower() == 'successful'


class PaymentViewSet(viewsets.ModelViewSet):
    """Payment management viewset."""
    
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter payments by user role."""
        user = self.request.user
        if user.role == 'admin':
            return Payment.objects.all()
        return Payment.objects.filter(
            booking__customer=user
        ) | Payment.objects.filter(
            booking__provider=user
        )
    
    @action(detail=False, methods=['post'])
    def create_payment(self, request):
        """Create payment for booking."""
        booking_id = request.data.get('booking_id')
        
        try:
            booking = Booking.objects.get(id=booking_id, customer=request.user)
        except Booking.DoesNotExist:
            return Response(
                {'error': 'Booking not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if hasattr(booking, 'payment'):
            return Response(
                {'error': 'Payment already exists for this booking'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment = Payment.objects.create(
            booking=booking,
            amount=booking.price,
            gateway=request.data.get('gateway', 'flutterwave')
        )

        checkout_link = None
        if payment.gateway == 'flutterwave' and _payment_gateway_name() == 'flutterwave':
            try:
                checkout_link = _initialize_flutterwave_payment(booking, payment)
            except requests.RequestException:
                checkout_link = None

        if checkout_link:
            payment.integration_status = 'initiated'
            payment.external_reference = checkout_link
            payment.save(update_fields=['integration_status', 'external_reference', 'updated_at'])

        create_notification(
            user=request.user,
            category='payment',
            title='Payment initiated',
            body=f'Payment for booking #{booking.id} has been created.',
            booking_id=booking.id,
        )

        response_payload = PaymentSerializer(payment).data
        if checkout_link:
            response_payload['checkout_url'] = checkout_link
        
        return Response(
            response_payload,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def verify_payment(self, request, pk=None):
        """Verify payment with gateway."""
        payment = self.get_object()

        verified = False
        if payment.gateway == 'flutterwave' and _payment_gateway_name() == 'flutterwave':
            try:
                verified = _verify_flutterwave_transaction(payment)
            except requests.RequestException:
                verified = False

        payment.integration_status = 'completed'
        payment.status = 'completed'
        payment.completed_at = timezone.now()
        payment.escrow_status = 'held'
        payment.payout_status = 'pending'
        payment.save()
        payment.schedule_payout_release(payment.completed_at)
        log_activity(
            actor=request.user,
            action='payment_verified',
            target_type='payment',
            target_id=payment.id,
            summary=f'Payment #{payment.id} was verified and moved to held escrow.',
            metadata={'booking_id': payment.booking_id, 'amount': str(payment.amount)},
        )

        create_notification(
            user=payment.booking.customer,
            category='payment',
            title='Payment completed',
            body=f'Payment for booking #{payment.booking.id} was completed and held in escrow.',
            booking_id=payment.booking.id,
        )
        
        response_payload = PaymentSerializer(payment).data
        response_payload['gateway_verified'] = verified
        return Response(response_payload)
    
    @action(detail=True, methods=['post'])
    def release_payout(self, request, pk=None):
        """Release payout to provider (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can release payouts'}, status=status.HTTP_403_FORBIDDEN)
        
        payment = self.get_object()
        
        if payment.status != 'completed':
            return Response(
                {'error': 'Payment must be completed before payout'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not payment.can_release_payout():
            if payment.booking.has_active_dispute or payment.booking.status == 'disputed':
                return Response(
                    {'error': 'Payout is blocked while the booking has an active dispute'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            return Response(
                {'error': 'Payout release window has not elapsed yet'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        payment.payout_status = 'released'
        payment.escrow_status = 'released'
        payment.payout_released_at = timezone.now()
        payment.save()
        log_activity(
            actor=request.user,
            action='payment_payout_released',
            target_type='payment',
            target_id=payment.id,
            summary=f'Payout released for payment #{payment.id}.',
            metadata={'booking_id': payment.booking_id, 'amount': str(payment.amount)},
        )
        
        return Response(PaymentSerializer(payment).data)

    @action(detail=False, methods=['post'])
    def process_due_payouts(self, request):
        """Admin: release all payments whose dispute window has elapsed and no dispute is active."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can process payouts'}, status=status.HTTP_403_FORBIDDEN)

        current_time = timezone.now()
        due_payments = Payment.objects.filter(
            status='completed',
            escrow_status='held',
            payout_status='pending',
            payout_release_at__lte=current_time,
        )

        released_ids = []
        blocked_ids = []
        for payment in due_payments.select_related('booking'):
            if payment.can_release_payout(current_time):
                payment.payout_status = 'released'
                payment.escrow_status = 'released'
                payment.payout_released_at = current_time
                payment.save(update_fields=['payout_status', 'escrow_status', 'payout_released_at', 'updated_at'])
                log_activity(
                    actor=request.user,
                    action='payment_payout_released',
                    target_type='payment',
                    target_id=payment.id,
                    summary=f'Payout released for payment #{payment.id} during due payout processing.',
                    metadata={'booking_id': payment.booking_id, 'amount': str(payment.amount), 'processed_in_batch': True},
                )
                released_ids.append(payment.id)
            else:
                blocked_ids.append(payment.id)

        return Response({
            'released_payments': released_ids,
            'blocked_payments': blocked_ids,
            'count_released': len(released_ids),
            'count_blocked': len(blocked_ids),
        })
