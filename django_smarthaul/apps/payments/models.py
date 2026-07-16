"""Payments models."""
from datetime import timedelta

from django.db import models
from django.utils.timezone import now
from apps.bookings.models import Booking


class Payment(models.Model):
    """Payment model."""
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
        ('refunded', 'Refunded'),
    ]
    
    GATEWAY_CHOICES = [
        ('flutterwave', 'Flutterwave'),
        ('stripe', 'Stripe'),
        ('paypal', 'PayPal'),
    ]
    
    INTEGRATION_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('initiated', 'Initiated'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]
    
    ESCROW_STATUS_CHOICES = [
        ('held', 'Held'),
        ('released', 'Released'),
        ('refunded', 'Refunded'),
    ]
    
    PAYOUT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('released', 'Released'),
        ('failed', 'Failed'),
    ]
    
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Gateway
    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES, default='flutterwave')
    external_reference = models.CharField(max_length=255, blank=True, db_index=True)
    transaction_id = models.CharField(max_length=255, blank=True)
    
    # Integration
    integration_status = models.CharField(
        max_length=20,
        choices=INTEGRATION_STATUS_CHOICES,
        default='pending'
    )
    
    # Escrow
    escrow_status = models.CharField(
        max_length=20,
        choices=ESCROW_STATUS_CHOICES,
        default='held'
    )
    
    # Payout
    payout_status = models.CharField(
        max_length=20,
        choices=PAYOUT_STATUS_CHOICES,
        default='pending'
    )
    payout_release_at = models.DateTimeField(null=True, blank=True)
    payout_released_at = models.DateTimeField(null=True, blank=True)
    dispute_window_hours = models.IntegerField(default=24)
    
    # Commission
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    commission_rate = models.FloatField(default=0.1)  # 10% default commission
    
    # Tracking
    attempted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['external_reference']),
            models.Index(fields=['payout_status']),
            models.Index(fields=['payout_release_at']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Payment {self.id} - {self.booking.id} - {self.status}"

    def schedule_payout_release(self, completed_at=None):
        """Set the earliest time the payout can be released."""
        completed_at = completed_at or now()
        self.payout_release_at = completed_at + timedelta(hours=self.dispute_window_hours)
        self.save(update_fields=['payout_release_at', 'updated_at'])

    def can_release_payout(self, current_time=None):
        """Return True when payout is due and the booking is not in dispute."""
        current_time = current_time or now()
        booking_disputed = self.booking.has_active_dispute or self.booking.status == 'disputed'
        if booking_disputed:
            return False
        if self.status != 'completed':
            return False
        if self.escrow_status != 'held' or self.payout_status == 'released':
            return False
        if self.payout_release_at is None:
            return False
        return current_time >= self.payout_release_at
