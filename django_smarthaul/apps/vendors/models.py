"""Vendors models."""
from django.db import models
from apps.auth.models import CustomUser


class Vendor(models.Model):
    """Vendor model."""
    
    ONBOARDING_STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('needs_more_info', 'Needs More Info'),
    ]
    
    DOCUMENT_STATUS_CHOICES = [
        ('missing', 'Missing'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='vendor_profile')
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=100)
    location = models.CharField(max_length=255)
    rating = models.FloatField(default=0)
    
    # Contact
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    
    # Onboarding
    onboarding_status = models.CharField(
        max_length=20, 
        choices=ONBOARDING_STATUS_CHOICES,
        default='pending_review'
    )
    document_status = models.CharField(
        max_length=20,
        choices=DOCUMENT_STATUS_CHOICES,
        default='missing'
    )
    onboarding_notes = models.TextField(blank=True)
    
    # Banking
    bank_account_number = models.CharField(max_length=50, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_holder_name = models.CharField(max_length=255, blank=True)
    
    # Stats
    total_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_orders = models.IntegerField(default=0)
    total_completed_orders = models.IntegerField(default=0)
    
    # Status
    permanently_banned = models.BooleanField(default=False)
    ban_reason = models.TextField(blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'Vendor'
        verbose_name_plural = 'Vendors'
        indexes = [
            models.Index(fields=['onboarding_status']),
            models.Index(fields=['category']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.category})"
