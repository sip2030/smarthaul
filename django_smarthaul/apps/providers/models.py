"""Providers models."""
from django.db import models
from apps.auth.models import CustomUser


class Provider(models.Model):
    """Provider model."""
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='provider_profile')
    service_area = models.CharField(max_length=255)
    vehicle_type = models.CharField(max_length=100, blank=True)
    license_number = models.CharField(max_length=100, blank=True)
    is_available = models.BooleanField(default=True)
    
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
            models.Index(fields=['service_area']),
            models.Index(fields=['is_available']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.service_area}"
