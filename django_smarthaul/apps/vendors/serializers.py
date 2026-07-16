"""Vendors serializers."""
from rest_framework import serializers
from .models import Vendor, VendorListing, VendorOrder


class VendorSerializer(serializers.ModelSerializer):
    """Vendor serializer."""
    
    class Meta:
        model = Vendor
        fields = [
            'id', 'user', 'name', 'category', 'location', 'rating', 'contact_email',
            'contact_phone', 'website', 'onboarding_status', 'document_status',
            'onboarding_notes', 'submitted_at', 'reviewed_at',
            'total_earnings', 'total_orders', 'total_completed_orders',
            'permanently_banned', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'user', 'total_earnings', 'total_orders', 'total_completed_orders',
            'created_at', 'updated_at', 'submitted_at', 'reviewed_at',
        ]


class VendorListingSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    vendor_category = serializers.CharField(source='vendor.category', read_only=True)
    vendor_location = serializers.CharField(source='vendor.location', read_only=True)

    class Meta:
        model = VendorListing
        fields = [
            'id', 'vendor', 'vendor_name', 'vendor_category', 'vendor_location',
            'title', 'description', 'listing_type', 'category', 'price', 'unit_label',
            'quantity_available', 'is_active', 'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'vendor', 'vendor_name', 'vendor_category', 'vendor_location', 'created_at', 'updated_at']


class VendorOrderSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source='vendor.name', read_only=True)
    listing_title = serializers.CharField(source='listing.title', read_only=True)
    customer_email = serializers.EmailField(source='customer.email', read_only=True)

    class Meta:
        model = VendorOrder
        fields = [
            'id', 'customer', 'customer_email', 'vendor', 'vendor_name', 'listing', 'listing_title',
            'quantity', 'unit_price', 'total_amount', 'status', 'customer_notes', 'vendor_notes',
            'cancelled_by', 'cancellation_reason',
            'refund_status', 'refund_amount', 'refund_requested_by', 'refund_requested_at', 'refund_reviewed_at',
            'rating', 'feedback_comment',
            'created_at', 'updated_at', 'status_updated_at', 'fulfilled_at', 'cancelled_at', 'feedback_submitted_at',
        ]
        read_only_fields = [
            'id', 'customer', 'vendor', 'vendor_name', 'listing_title', 'customer_email',
            'unit_price', 'total_amount', 'created_at', 'updated_at', 'status_updated_at',
            'fulfilled_at', 'cancelled_at', 'feedback_submitted_at', 'cancelled_by',
            'refund_status', 'refund_amount', 'refund_requested_by', 'refund_requested_at', 'refund_reviewed_at',
        ]


class VendorOrderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = VendorOrder
        fields = ['listing', 'quantity', 'customer_notes']

    def validate_quantity(self, value):
        if value < 1:
            raise serializers.ValidationError('quantity must be at least 1')
        return value
