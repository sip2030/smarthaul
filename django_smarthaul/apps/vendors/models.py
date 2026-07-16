"""Vendors models."""
from django.db import models
from django.db.models import Avg
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
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    
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
            models.Index(fields=['document_status']),
            models.Index(fields=['category']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.category})"


class VendorListing(models.Model):
    """Vendor-owned service or product listing."""

    LISTING_TYPE_CHOICES = [
        ('service', 'Service'),
        ('product', 'Product'),
    ]

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='listings')
    title = models.CharField(max_length=255)
    description = models.TextField()
    listing_type = models.CharField(max_length=20, choices=LISTING_TYPE_CHOICES, default='service')
    category = models.CharField(max_length=100)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    unit_label = models.CharField(max_length=50, blank=True)
    quantity_available = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Vendor Listing'
        verbose_name_plural = 'Vendor Listings'
        indexes = [
            models.Index(fields=['vendor']),
            models.Index(fields=['category']),
            models.Index(fields=['is_active']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.vendor.name}"


class VendorOrder(models.Model):
    """Customer order for a vendor listing."""

    ORDER_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('accepted', 'Accepted'),
        ('preparing', 'Preparing'),
        ('ready_for_pickup', 'Ready For Pickup'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    REFUND_STATUS_CHOICES = [
        ('not_required', 'Not Required'),
        ('pending_review', 'Pending Review'),
        ('approved', 'Approved'),
        ('processed', 'Processed'),
        ('rejected', 'Rejected'),
    ]

    customer = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='vendor_orders')
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name='orders')
    listing = models.ForeignKey(VendorListing, on_delete=models.CASCADE, related_name='orders')
    quantity = models.IntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=ORDER_STATUS_CHOICES, default='pending')
    customer_notes = models.TextField(blank=True)
    vendor_notes = models.TextField(blank=True)
    cancelled_by = models.CharField(max_length=20, blank=True)
    cancellation_reason = models.TextField(blank=True)
    refund_status = models.CharField(max_length=20, choices=REFUND_STATUS_CHOICES, default='not_required')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refund_requested_by = models.CharField(max_length=20, blank=True, default='')
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refund_reviewed_at = models.DateTimeField(null=True, blank=True)
    rating = models.IntegerField(null=True, blank=True)
    feedback_comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    status_updated_at = models.DateTimeField(auto_now=True)
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    feedback_submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Vendor Order'
        verbose_name_plural = 'Vendor Orders'
        indexes = [
            models.Index(fields=['vendor', 'status']),
            models.Index(fields=['customer', 'status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"Order #{self.id} - {self.listing.title} - {self.status}"

    def refresh_vendor_rating(self):
        average_rating = self.vendor.orders.filter(rating__isnull=False).aggregate(avg=Avg('rating'))['avg']
        self.vendor.rating = round(float(average_rating), 2) if average_rating is not None else 0
        self.vendor.save(update_fields=['rating', 'updated_at'])
