"""Bookings models."""
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
    
    # Location tracking
    current_latitude = models.FloatField(null=True, blank=True)
    current_longitude = models.FloatField(null=True, blank=True)
    eta_minutes = models.IntegerField(null=True, blank=True)
    
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
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"Booking #{self.id} - {self.service_type}"
    
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
