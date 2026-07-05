"""Bookings admin."""
from django.contrib import admin
from .models import Booking, BookingTracking


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    """Booking admin."""
    
    list_display = ['id', 'customer', 'provider', 'service_type', 'status', 'price', 'created_at']
    list_filter = ['status', 'service_type', 'created_at']
    search_fields = ['customer__email', 'provider__email', 'service_type', 'pickup', 'destination']
    readonly_fields = ['created_at', 'updated_at', 'completed_at']


@admin.register(BookingTracking)
class BookingTrackingAdmin(admin.ModelAdmin):
    """Booking tracking admin."""
    
    list_display = ['booking', 'latitude', 'longitude', 'created_at']
    list_filter = ['created_at']
    search_fields = ['booking__id']
    readonly_fields = ['created_at']
