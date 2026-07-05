"""Payments admin."""
from django.contrib import admin
from .models import Payment


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('id', 'booking', 'amount', 'status', 'gateway', 'payout_status', 'created_at')
    list_filter = ('status', 'gateway', 'payout_status', 'created_at')
    search_fields = ('booking__id', 'external_reference', 'transaction_id')
    readonly_fields = ('created_at', 'updated_at')
