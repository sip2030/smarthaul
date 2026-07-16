"""Providers admin."""
from django.contrib import admin
from .models import Provider


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'service_area', 'verification_status', 'is_available', 'rating', 'completed_bookings', 'created_at')
    list_filter = ('verification_status', 'is_available', 'permanently_banned', 'created_at')
    search_fields = ('user__email', 'service_area', 'vehicle_type')
    readonly_fields = ('created_at', 'updated_at')
