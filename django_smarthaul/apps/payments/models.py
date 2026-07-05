"""Payments models."""
from django.db import models
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
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Payment {self.id} - {self.booking.id} - {self.status}"
