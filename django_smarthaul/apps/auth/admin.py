"""Auth admin configuration."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import CustomUser


class CustomUserAdmin(BaseUserAdmin):
    """Custom user admin."""
    
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Custom Fields', {'fields': ('role', 'phone_number', 'avatar', 'bio', 'account_status', 
                                       'account_restricted_reason', 'account_restricted_at',
                                       'last_login_at', 'failed_login_attempts', 'locked_until',
                                       'password_updated_at', 'address', 'city', 'state', 
                                       'country', 'zip_code')}),
    )
    list_display = ['email', 'first_name', 'last_name', 'role', 'account_status', 'date_joined']
    list_filter = ['role', 'account_status', 'date_joined']
    search_fields = ['email', 'first_name', 'last_name', 'phone_number']

# Register after Django admin app loads
admin.site.register(CustomUser, CustomUserAdmin)

