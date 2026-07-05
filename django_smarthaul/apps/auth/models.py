"""Auth models."""
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.timezone import now


class CustomUser(AbstractUser):
    """Custom user model with additional fields."""
    
    ROLE_CHOICES = [
        ('customer', 'Customer'),
        ('provider', 'Provider'),
        ('vendor', 'Vendor'),
        ('admin', 'Admin'),
    ]
    
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='customer')
    phone_number = models.CharField(max_length=20, blank=True)
    avatar = models.URLField(blank=True)
    bio = models.TextField(blank=True)
    
    # Account status
    account_status = models.CharField(
        max_length=20,
        choices=[('active', 'Active'), ('restricted', 'Restricted'), ('banned', 'Banned')],
        default='active'
    )
    account_restricted_reason = models.TextField(blank=True)
    account_restricted_at = models.DateTimeField(null=True, blank=True)
    
    # Login tracking
    last_login_at = models.DateTimeField(null=True, blank=True)
    failed_login_attempts = models.IntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    
    # Password
    password_updated_at = models.DateTimeField(auto_now_add=True)
    
    # Address
    address = models.TextField(blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=100, default='Nigeria')
    zip_code = models.CharField(max_length=20, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['account_status']),
            models.Index(fields=['email']),
        ]
    
    def __str__(self):
        return f"{self.email} ({self.get_role_display()})"
    
    def is_active_user(self):
        """Check if user account is active."""
        return self.account_status == 'active'
