"""Payments serializers."""
from rest_framework import serializers
from .models import Payment


class PaymentSerializer(serializers.ModelSerializer):
    """Payment serializer."""
    
    class Meta:
        model = Payment
        fields = [
            'id', 'booking', 'amount', 'status', 'gateway', 'external_reference',
            'transaction_id', 'integration_status', 'escrow_status', 'payout_status',
            'payout_release_at', 'payout_released_at', 'commission_amount',
            'commission_rate', 'attempted_at', 'completed_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'booking', 'external_reference', 'transaction_id', 'created_at', 'updated_at']
