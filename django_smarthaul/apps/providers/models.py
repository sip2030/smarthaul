"""Providers models."""
from django.db import models
from apps.auth.models import CustomUser


class Provider(models.Model):
    """Provider model."""

    VERIFICATION_STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('needs_more_info', 'Needs More Info'),
    ]
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='provider_profile')
    service_area = models.CharField(max_length=255)
    vehicle_type = models.CharField(max_length=100, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    is_available = models.BooleanField(default=True)

    verification_status = models.CharField(
        max_length=20,
        choices=VERIFICATION_STATUS_CHOICES,
        default='pending_review'
    )
    verification_notes = models.TextField(blank=True)
    verification_submitted_at = models.DateTimeField(null=True, blank=True)
    verification_reviewed_at = models.DateTimeField(null=True, blank=True)
    
    # Stats
    rating = models.FloatField(default=0)
    total_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_bookings = models.IntegerField(default=0)
    completed_bookings = models.IntegerField(default=0)
    cancelled_bookings = models.IntegerField(default=0)
    
    # Status
    permanently_banned = models.BooleanField(default=False)
    ban_reason = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Provider'
        verbose_name_plural = 'Providers'
        indexes = [
            models.Index(fields=['verification_status']),
            models.Index(fields=['service_area']),
            models.Index(fields=['is_available']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.service_area}"
