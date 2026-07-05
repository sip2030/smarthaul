"""Vendors serializers."""
from rest_framework import serializers
from .models import Vendor


class VendorSerializer(serializers.ModelSerializer):
    """Vendor serializer."""
    
    class Meta:
        model = Vendor
        fields = [
            'id', 'user', 'name', 'category', 'location', 'rating', 'contact_email',
            'contact_phone', 'website', 'onboarding_status', 'document_status',
            'total_earnings', 'total_orders', 'total_completed_orders',
            'permanently_banned', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'total_earnings', 'total_orders', 'total_completed_orders', 'created_at', 'updated_at']
