"""Payments views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from .models import Payment
from .serializers import PaymentSerializer
from apps.bookings.models import Booking


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
        
        return Response(
            PaymentSerializer(payment).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def verify_payment(self, request, pk=None):
        """Verify payment with gateway."""
        payment = self.get_object()
        
        # Placeholder for Flutterwave/Stripe verification
        # In production, call the payment gateway API
        payment.integration_status = 'completed'
        payment.status = 'completed'
        payment.completed_at = timezone.now()
        payment.save()
        
        return Response(PaymentSerializer(payment).data)
    
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
        
        payment.payout_status = 'released'
        payment.escrow_status = 'released'
        payment.save()
        
        return Response(PaymentSerializer(payment).data)
