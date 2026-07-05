"""Providers serializers."""
from rest_framework import serializers
from .models import Provider


class ProviderSerializer(serializers.ModelSerializer):
    """Provider serializer."""
    
    class Meta:
        model = Provider
        fields = [
            'id', 'user', 'service_area', 'vehicle_type', 'license_number', 
            'is_available', 'rating', 'total_earnings', 'total_bookings', 
            'completed_bookings', 'cancelled_bookings', 'permanently_banned', 
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'total_earnings', 'total_bookings', 'completed_bookings', 'cancelled_bookings', 'created_at', 'updated_at']
