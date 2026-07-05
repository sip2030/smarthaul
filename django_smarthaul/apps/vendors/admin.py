"""Vendors admin."""
from django.contrib import admin
from .models import Vendor


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'onboarding_status', 'document_status', 'rating', 'total_earnings', 'created_at')
    list_filter = ('onboarding_status', 'document_status', 'category', 'created_at')
    search_fields = ('name', 'category', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
