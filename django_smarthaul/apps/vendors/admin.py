"""Vendors admin."""
from django.contrib import admin
from .models import Vendor, VendorListing


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'category', 'onboarding_status', 'document_status', 'rating', 'total_earnings', 'created_at')
    list_filter = ('onboarding_status', 'document_status', 'category', 'created_at')
    search_fields = ('name', 'category', 'user__email')
    readonly_fields = ('created_at', 'updated_at', 'submitted_at', 'reviewed_at')


@admin.register(VendorListing)
class VendorListingAdmin(admin.ModelAdmin):
    list_display = ('id', 'vendor', 'title', 'listing_type', 'category', 'price', 'quantity_available', 'is_active', 'created_at')
    list_filter = ('listing_type', 'category', 'is_active', 'created_at')
    search_fields = ('title', 'description', 'vendor__name', 'vendor__user__email')
    readonly_fields = ('created_at', 'updated_at')
