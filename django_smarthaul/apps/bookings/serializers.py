"""Bookings serializers."""
from rest_framework import serializers
from .models import Booking, BookingTracking, CallLog


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
            'accepted_at', 'scheduled_for_at', 'reschedule_status', 'reschedule_requested_by',
            'reschedule_requested_at', 'reschedule_proposed_for_at', 'reschedule_reason',
            'reschedule_response_at',
            'created_at', 'updated_at', 'completed_at', 'rating', 'feedback_comment',
            'feedback_submitted_at', 'tracking_events',
            'cancelled_by', 'cancellation_fee_owed', 'cancellation_fee_paid_by', 'cancellation_fee_logged_at',
            'provider_last_ping_at',
            'has_active_dispute', 'dispute_started_at', 'safety_report_filed_at',
            'call_logging_window_hours',
        ]
        read_only_fields = [
            'id', 'created_at', 'updated_at', 'completed_at', 'tracking_events',
            'cancelled_by', 'cancellation_fee_owed', 'cancellation_fee_logged_at',
            'provider_last_ping_at',
            'has_active_dispute', 'dispute_started_at', 'safety_report_filed_at',
            'accepted_at', 'scheduled_for_at', 'reschedule_status', 'reschedule_requested_by',
            'reschedule_requested_at', 'reschedule_proposed_for_at', 'reschedule_reason',
            'reschedule_response_at',
            'cancellation_fee_paid_by',
        ]


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


class CallLogSerializer(serializers.ModelSerializer):
    """Call log serializer."""
    caller_name = serializers.CharField(source='caller.get_full_name', read_only=True)
    recipient_name = serializers.CharField(source='recipient.get_full_name', read_only=True)

    class Meta:
        model = CallLog
        fields = [
            'id', 'booking', 'caller', 'caller_name', 'recipient', 'recipient_name',
            'call_type', 'call_medium', 'consent_acknowledged', 'duration_seconds', 'recording_url', 'recording_enabled',
            'call_should_be_logged', 'reason_for_logging',
            'created_at', 'started_at', 'ended_at'
        ]
        read_only_fields = [
            'id', 'created_at', 'call_should_be_logged', 'reason_for_logging',
            'caller_name', 'recipient_name'
        ]
