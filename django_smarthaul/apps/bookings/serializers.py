"""Bookings serializers."""
from rest_framework import serializers
from .models import Booking, BookingTracking


class BookingTrackingSerializer(serializers.ModelSerializer):
    """Booking tracking serializer."""
    
    class Meta:
        model = BookingTracking
        fields = ['id', 'latitude', 'longitude', 'created_at']
        read_only_fields = ['id', 'created_at']


class BookingSerializer(serializers.ModelSerializer):
    """Booking serializer."""
    
    tracking_events = BookingTrackingSerializer(many=True, read_only=True)
    
    class Meta:
        model = Booking
        fields = [
            'id', 'customer', 'provider', 'vendor', 'service_type', 'pickup', 'destination',
            'price', 'status', 'current_latitude', 'current_longitude', 'eta_minutes',
            'created_at', 'updated_at', 'completed_at', 'rating', 'feedback_comment',
            'feedback_submitted_at', 'tracking_events'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at', 'completed_at', 'tracking_events']


class BookingCreateSerializer(serializers.ModelSerializer):
    """Booking creation serializer."""
    
    class Meta:
        model = Booking
        fields = ['service_type', 'pickup', 'destination', 'price']


class BookingUpdateSerializer(serializers.ModelSerializer):
    """Booking update serializer."""
    
    class Meta:
        model = Booking
        fields = ['status', 'current_latitude', 'current_longitude', 'eta_minutes', 
                  'rating', 'feedback_comment']
