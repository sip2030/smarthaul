"""Bookings models."""
from datetime import timedelta

from django.db import models
from django.utils.timezone import now
from apps.auth.models import CustomUser


class Booking(models.Model):
    """Booking model."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('disputed', 'Disputed'),
        ('admin_review', 'Admin Review'),
    ]

    CANCELLED_BY_CHOICES = [
        ('customer', 'Customer'),
        ('provider', 'Provider'),
        ('system', 'System'),
        ('admin', 'Admin'),
    ]
    
    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='bookings_as_customer')
    provider = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True, 
                                  related_name='bookings_as_provider')
    vendor = models.ForeignKey('vendors.Vendor', on_delete=models.SET_NULL, null=True, blank=True)
    
    service_type = models.CharField(max_length=100)
    pickup = models.CharField(max_length=255)
    destination = models.CharField(max_length=255)
    
    price = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    pending_timeout_minutes = models.IntegerField(default=10)
    pending_expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Cancellation policy
    cancellation_window_minutes = models.IntegerField(default=15)
    cancellation_fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=10)
    cancellation_fee_paid_by = models.CharField(max_length=20, blank=True)

    # Rescheduling
    scheduled_for_at = models.DateTimeField(null=True, blank=True)
    reschedule_status = models.CharField(max_length=20, default='none')
    reschedule_requested_by = models.CharField(max_length=20, blank=True)
    reschedule_requested_at = models.DateTimeField(null=True, blank=True)
    reschedule_proposed_for_at = models.DateTimeField(null=True, blank=True)
    reschedule_reason = models.TextField(blank=True)
    reschedule_response_at = models.DateTimeField(null=True, blank=True)
    
    # Location tracking
    current_latitude = models.FloatField(null=True, blank=True)
    current_longitude = models.FloatField(null=True, blank=True)
    eta_minutes = models.IntegerField(null=True, blank=True)
    
    # Cancellation tracking
    cancelled_by = models.CharField(
        max_length=20, choices=CANCELLED_BY_CHOICES, null=True, blank=True
    )
    cancellation_fee_owed = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    cancellation_fee_logged_at = models.DateTimeField(null=True, blank=True)

    # Provider responsiveness
    provider_last_ping_at = models.DateTimeField(null=True, blank=True)

    # Dispute and safety report tracking for call logging
    has_active_dispute = models.BooleanField(default=False, db_index=True)
    dispute_started_at = models.DateTimeField(null=True, blank=True)
    safety_report_filed_at = models.DateTimeField(null=True, blank=True)
    # Window for call logging after booking completes/disputes (default 24 hours)
    call_logging_window_hours = models.IntegerField(default=24)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Rating & feedback
    rating = models.IntegerField(null=True, blank=True)
    feedback_comment = models.TextField(blank=True)
    feedback_submitted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = 'Booking'
        verbose_name_plural = 'Bookings'
        indexes = [
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['provider', 'status']),
            models.Index(fields=['status']),
            models.Index(fields=['pending_expires_at']),
            models.Index(fields=['accepted_at']),
            models.Index(fields=['reschedule_status']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Booking #{self.id} - {self.service_type}"

    def save(self, *args, **kwargs):
        if self.status == 'pending' and self.pending_expires_at is None:
            self.pending_expires_at = now() + timedelta(minutes=self.pending_timeout_minutes)
        super().save(*args, **kwargs)

    def cancellation_fee_window_expires_at(self):
        """Return when the penalty-free cancellation window ends."""
        acceptance_time = self.accepted_at or self.updated_at or self.created_at
        if acceptance_time is None:
            return None
        return acceptance_time + timedelta(minutes=self.cancellation_window_minutes)

    def is_within_cancellation_window(self, current_time=None):
        current_time = current_time or now()
        window_expires_at = self.cancellation_fee_window_expires_at()
        if window_expires_at is None:
            return True
        return current_time <= window_expires_at
    
    def complete_booking(self):
        """Mark booking as completed."""
        self.status = 'completed'
        self.completed_at = now()
        self.save()


class BookingTracking(models.Model):
    """Booking location tracking."""
    
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='tracking_events')
    latitude = models.FloatField()
    longitude = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = 'Booking Tracking'
        verbose_name_plural = 'Booking Tracking Events'
        indexes = [
            models.Index(fields=['booking', 'created_at']),
        ]
    
    def __str__(self):
        return f"Tracking for Booking #{self.booking.id}"


class CallLog(models.Model):
    """Call logging model - logs calls only when dispute or safety report exists for a booking."""

    CALL_TYPE_CHOICES = [
        ('inbound', 'Inbound'),
        ('outbound', 'Outbound'),
    ]

    CALL_MEDIUM_CHOICES = [
        ('audio', 'Audio'),
        ('video', 'Video'),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='call_logs')
    caller = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='calls_made')
    recipient = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='calls_received')

    call_type = models.CharField(max_length=20, choices=CALL_TYPE_CHOICES)
    call_medium = models.CharField(max_length=20, choices=CALL_MEDIUM_CHOICES, default='audio')
    duration_seconds = models.IntegerField(null=True, blank=True)
    recording_url = models.URLField(blank=True)
    recording_enabled = models.BooleanField(default=False)
    consent_acknowledged = models.BooleanField(default=False)
    
    # Call logging decision
    call_should_be_logged = models.BooleanField(
        default=False,
        help_text='True if booking had active dispute or safety report at call time'
    )
    reason_for_logging = models.CharField(
        max_length=255,
        blank=True,
        help_text='Why this call was logged: dispute_active, safety_report_filed, etc.'
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Call Log'
        verbose_name_plural = 'Call Logs'
        indexes = [
            models.Index(fields=['booking', 'created_at']),
            models.Index(fields=['call_should_be_logged']),
            models.Index(fields=['booking', 'call_should_be_logged']),
        ]

    def __str__(self):
        return f"Call {self.id} - Booking #{self.booking.id} - Logged: {self.call_should_be_logged}"

    @classmethod
    def should_log_call(cls, booking):
        """
        Determine if a call linked to a booking should be logged.
        Per 10.4 PRD: Log only if booking has active dispute or safety report on file.
        """
        if booking.has_active_dispute:
            return True, 'dispute_active'
        if booking.safety_report_filed_at:
            return True, 'safety_report_filed'
        return False, None
