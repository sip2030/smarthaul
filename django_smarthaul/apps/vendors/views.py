"""Vendors views."""
from django.utils.timezone import now
from django.db import transaction
from django.db.models import F
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied
from apps.analytics.models import log_activity
from apps.communications.views import create_notification, notify_admins
from .models import Vendor, VendorListing, VendorOrder
from .serializers import VendorSerializer, VendorListingSerializer, VendorOrderSerializer, VendorOrderCreateSerializer


class VendorViewSet(viewsets.ModelViewSet):
    """Vendor management viewset."""
    
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Vendor.objects.all().order_by('-rating', '-created_at')

        category = self.request.query_params.get('category')
        location = self.request.query_params.get('location')
        min_rating = self.request.query_params.get('min_rating')

        if category:
            queryset = queryset.filter(category__iexact=category)
        if location:
            queryset = queryset.filter(location__icontains=location)
        if min_rating:
            try:
                queryset = queryset.filter(rating__gte=float(min_rating))
            except (TypeError, ValueError):
                return queryset.none()

        if self.request.user.role != 'admin':
            queryset = queryset.filter(onboarding_status='approved', document_status='approved')

        return queryset
    
    def create(self, request, *args, **kwargs):
        """Create vendor profile for current user."""
        if request.user.account_status == 'banned':
            return Response({'error': 'Banned accounts cannot submit verification'}, status=status.HTTP_403_FORBIDDEN)

        if hasattr(request.user, 'vendor_profile'):
            vendor = request.user.vendor_profile
            if vendor.onboarding_status in ['rejected', 'needs_more_info'] or vendor.document_status in ['rejected', 'missing']:
                return self._resubmit_vendor(request, vendor)
            return Response(
                {'error': 'User already has a vendor profile'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        vendor = Vendor.objects.create(
            user=request.user,
            submitted_at=now(),
            **serializer.validated_data,
        )
        log_activity(
            actor=request.user,
            action='vendor_verification_submitted',
            target_type='vendor',
            target_id=vendor.id,
            summary=f'Vendor profile #{vendor.id} submitted for review.',
            metadata={'category': vendor.category, 'location': vendor.location},
        )
        return Response(VendorSerializer(vendor).data, status=status.HTTP_201_CREATED)

    def _resubmit_vendor(self, request, vendor):
        serializer = self.get_serializer(vendor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(vendor, field, value)

        vendor.onboarding_status = 'pending_review'
        vendor.document_status = 'pending'
        vendor.onboarding_notes = ''
        vendor.submitted_at = now()
        vendor.reviewed_at = None
        vendor.save()
        log_activity(
            actor=request.user,
            action='vendor_verification_resubmitted',
            target_type='vendor',
            target_id=vendor.id,
            summary=f'Vendor profile #{vendor.id} was resubmitted for review.',
            metadata={'category': vendor.category, 'location': vendor.location},
        )
        return Response(VendorSerializer(vendor).data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def my_profile(self, request):
        """Get current vendor profile."""
        try:
            vendor = request.user.vendor_profile
            return Response(VendorSerializer(vendor).data)
        except Vendor.DoesNotExist:
            return Response(
                {'error': 'Vendor profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=['post'])
    def resubmit(self, request):
        """Resubmit a rejected or needs-more-info vendor application."""
        try:
            vendor = request.user.vendor_profile
        except Vendor.DoesNotExist:
            return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.account_status == 'banned':
            return Response({'error': 'Banned accounts cannot resubmit verification'}, status=status.HTTP_403_FORBIDDEN)

        if vendor.onboarding_status not in ['rejected', 'needs_more_info'] and vendor.document_status not in ['rejected', 'missing']:
            return Response({'error': 'Vendor profile is not in a resubmittable state'}, status=status.HTTP_400_BAD_REQUEST)

        return self._resubmit_vendor(request, vendor)
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve vendor (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can approve vendors'}, status=status.HTTP_403_FORBIDDEN)
        
        vendor = self.get_object()
        vendor.onboarding_status = 'approved'
        vendor.document_status = 'approved'
        vendor.reviewed_at = now()
        vendor.save()
        log_activity(
            actor=request.user,
            action='vendor_verification_approved',
            target_type='vendor',
            target_id=vendor.id,
            summary=f'Vendor profile #{vendor.id} was approved.',
            metadata={'vendor_user_id': vendor.user_id},
        )
        
        return Response(VendorSerializer(vendor).data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject vendor (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can reject vendors'}, status=status.HTTP_403_FORBIDDEN)
        
        vendor = self.get_object()
        vendor.onboarding_status = 'rejected'
        vendor.onboarding_notes = request.data.get('reason', '')
        vendor.reviewed_at = now()
        vendor.save()
        log_activity(
            actor=request.user,
            action='vendor_verification_rejected',
            target_type='vendor',
            target_id=vendor.id,
            summary=f'Vendor profile #{vendor.id} was rejected.',
            metadata={'reason': vendor.onboarding_notes, 'vendor_user_id': vendor.user_id},
        )
        
        return Response(VendorSerializer(vendor).data)


class VendorListingViewSet(viewsets.ModelViewSet):
    """Vendor listing management and browsing."""

    serializer_class = VendorListingSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = VendorListing.objects.select_related('vendor', 'vendor__user').order_by('-created_at')

        category = self.request.query_params.get('category')
        location = self.request.query_params.get('location')
        if category:
            queryset = queryset.filter(category__iexact=category)
        if location:
            queryset = queryset.filter(vendor__location__icontains=location)

        if user.role == 'admin':
            return queryset

        if hasattr(user, 'vendor_profile'):
            return queryset.filter(vendor=user.vendor_profile)

        return queryset.filter(is_active=True, vendor__onboarding_status='approved', vendor__document_status='approved')

    def perform_create(self, serializer):
        if self.request.user.role != 'vendor':
            raise PermissionDenied('Only vendors can create listings')
        try:
            vendor = self.request.user.vendor_profile
        except Vendor.DoesNotExist:
            raise PermissionDenied('Vendor profile not found')

        if self.request.user.account_status == 'banned' or vendor.permanently_banned:
            raise PermissionDenied('Banned vendors cannot create listings')

        serializer.save(vendor=vendor)

    def create(self, request, *args, **kwargs):
        if request.user.role != 'vendor':
            return Response({'error': 'Only vendors can create listings'}, status=status.HTTP_403_FORBIDDEN)
        try:
            request.user.vendor_profile
        except Vendor.DoesNotExist:
            return Response({'error': 'Vendor profile not found'}, status=status.HTTP_404_NOT_FOUND)

        return super().create(request, *args, **kwargs)

    def _ensure_listing_manager(self, request, listing):
        if request.user.role == 'admin':
            return None
        if getattr(request.user, 'vendor_profile', None) == listing.vendor:
            return None
        return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)

    def update(self, request, *args, **kwargs):
        listing = self.get_object()
        denial = self._ensure_listing_manager(request, listing)
        if denial:
            return denial
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        listing = self.get_object()
        denial = self._ensure_listing_manager(request, listing)
        if denial:
            return denial
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        listing = self.get_object()
        denial = self._ensure_listing_manager(request, listing)
        if denial:
            return denial
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        listing = self.get_object()
        if request.user.role != 'admin' and getattr(request.user, 'vendor_profile', None) != listing.vendor:
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)
        listing.is_active = True
        listing.save(update_fields=['is_active', 'updated_at'])
        return Response(VendorListingSerializer(listing).data)

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        listing = self.get_object()
        if request.user.role != 'admin' and getattr(request.user, 'vendor_profile', None) != listing.vendor:
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)
        listing.is_active = False
        listing.save(update_fields=['is_active', 'updated_at'])
        return Response(VendorListingSerializer(listing).data)

    @action(detail=True, methods=['post'])
    def remove(self, request, pk=None):
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can remove listings'}, status=status.HTTP_403_FORBIDDEN)

        listing = self.get_object()
        listing.is_active = False
        listing.save(update_fields=['is_active', 'updated_at'])

        reason = (request.data.get('reason') or '').strip()
        create_notification(
            user=listing.vendor.user,
            category='moderation',
            title='Listing removed',
            body=(
                f'Your listing "{listing.title}" was removed by admin.'
                + (f' Reason: {reason}' if reason else '')
            ),
        )
        log_activity(
            actor=request.user,
            action='vendor_listing_removed',
            target_type='vendor_listing',
            target_id=listing.id,
            summary=f'Admin removed listing "{listing.title}".',
            metadata={'reason': reason, 'vendor_id': listing.vendor_id},
        )
        return Response(VendorListingSerializer(listing).data)


class VendorOrderViewSet(viewsets.ModelViewSet):
    """Vendor order lifecycle viewset."""

    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'create':
            return VendorOrderCreateSerializer
        return VendorOrderSerializer

    def get_queryset(self):
        queryset = VendorOrder.objects.select_related('customer', 'vendor', 'listing').order_by('-created_at')

        if self.request.user.role == 'admin':
            return queryset
        if hasattr(self.request.user, 'vendor_profile'):
            return queryset.filter(vendor=self.request.user.vendor_profile)
        return queryset.filter(customer=self.request.user)

    def _can_manage_order(self, request, order):
        if request.user.role == 'admin':
            return True
        if request.user.id == order.customer_id:
            return True
        if getattr(request.user, 'vendor_profile', None) == order.vendor:
            return True
        return False

    def create(self, request, *args, **kwargs):
        if request.user.role != 'customer':
            return Response({'error': 'Only customers can place vendor orders'}, status=status.HTTP_403_FORBIDDEN)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        listing = serializer.validated_data['listing']
        if not listing.is_active or listing.vendor.onboarding_status != 'approved' or listing.vendor.document_status != 'approved':
            return Response({'error': 'Listing is not available for ordering'}, status=status.HTTP_400_BAD_REQUEST)

        quantity = serializer.validated_data['quantity']
        unit_price = listing.price
        total_amount = unit_price * quantity

        with transaction.atomic():
            order = VendorOrder.objects.create(
                customer=request.user,
                vendor=listing.vendor,
                listing=listing,
                quantity=quantity,
                unit_price=unit_price,
                total_amount=total_amount,
                customer_notes=serializer.validated_data.get('customer_notes', ''),
            )
            listing.vendor.total_orders = F('total_orders') + 1
            listing.vendor.save(update_fields=['total_orders', 'updated_at'])

        create_notification(
            user=listing.vendor.user,
            category='booking',
            title='New vendor order',
            body=f'Order #{order.id} was placed for {listing.title}.',
        )
        create_notification(
            user=request.user,
            category='booking',
            title='Vendor order created',
            body=f'Your order #{order.id} is pending vendor review.',
        )
        log_activity(
            actor=request.user,
            action='vendor_order_created',
            target_type='vendor_order',
            target_id=order.id,
            summary=f'Customer placed vendor order #{order.id}.',
            metadata={'vendor_id': order.vendor_id, 'listing_id': listing.id, 'quantity': quantity},
        )

        return Response(VendorOrderSerializer(order).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        order = self.get_object()
        if request.user.role != 'admin' and getattr(request.user, 'vendor_profile', None) != order.vendor:
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)

        new_status = (request.data.get('status') or '').strip()
        if new_status not in dict(VendorOrder.ORDER_STATUS_CHOICES):
            return Response({'error': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = order.status
        order.status = new_status
        order.vendor_notes = request.data.get('vendor_notes', order.vendor_notes)
        order.save(update_fields=['status', 'vendor_notes', 'status_updated_at', 'updated_at'])

        if new_status == 'completed' and previous_status != 'completed':
            order.fulfilled_at = now()
            order.save(update_fields=['fulfilled_at', 'updated_at'])
            order.vendor.total_completed_orders = F('total_completed_orders') + 1
            order.vendor.total_earnings = F('total_earnings') + order.total_amount
            order.vendor.save(update_fields=['total_completed_orders', 'total_earnings', 'updated_at'])

        create_notification(
            user=order.customer,
            category='booking',
            title='Vendor order updated',
            body=f'Order #{order.id} is now {order.status}.',
        )
        log_activity(
            actor=request.user,
            action='vendor_order_status_updated',
            target_type='vendor_order',
            target_id=order.id,
            summary=f'Order #{order.id} status changed from {previous_status} to {new_status}.',
            metadata={'previous_status': previous_status, 'new_status': new_status, 'vendor_id': order.vendor_id},
        )

        order.refresh_from_db()
        return Response(VendorOrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def cancel_order(self, request, pk=None):
        order = self.get_object()
        if not self._can_manage_order(request, order):
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)

        if order.status in ['completed', 'cancelled']:
            return Response({'error': f'Cannot cancel order in {order.status} status'}, status=status.HTTP_400_BAD_REQUEST)

        reason = (request.data.get('reason') or '').strip()
        previous_status = order.status
        cancellation_time = now()
        refund_review_required = previous_status in ['accepted', 'preparing', 'ready_for_pickup']
        order.status = 'cancelled'
        order.cancelled_at = cancellation_time
        order.cancelled_by = request.user.role
        order.cancellation_reason = reason
        if refund_review_required:
            order.refund_status = 'pending_review'
            order.refund_amount = order.total_amount
            order.refund_requested_by = request.user.role
            order.refund_requested_at = cancellation_time
            order.refund_reviewed_at = None
        else:
            order.refund_status = 'not_required'
            order.refund_amount = None
            order.refund_requested_by = request.user.role
            order.refund_requested_at = None
            order.refund_reviewed_at = None
        order.save(update_fields=['status', 'cancelled_at', 'cancelled_by', 'cancellation_reason', 'refund_status', 'refund_amount', 'refund_requested_by', 'refund_requested_at', 'refund_reviewed_at', 'status_updated_at', 'updated_at'])

        notified_user = order.vendor.user if request.user.id == order.customer_id else order.customer
        refund_note = ' Refund review has been queued.' if refund_review_required else ''
        create_notification(
            user=notified_user,
            category='booking',
            title='Vendor order cancelled',
            body=(
                f'Order #{order.id} was cancelled by {request.user.role}.'
                + (f' Reason: {reason}' if reason else '')
                + refund_note
            ),
        )
        if refund_review_required:
            notify_admins(
                category='payment',
                title='Vendor order refund review needed',
                body=(
                    f'Order #{order.id} was cancelled at status {previous_status} and needs refund review.'
                    + (f' Reason: {reason}' if reason else '')
                ),
            )
        log_activity(
            actor=request.user,
            action='vendor_order_cancelled',
            target_type='vendor_order',
            target_id=order.id,
            summary=f'Order #{order.id} was cancelled by {request.user.role}.',
            metadata={
                'reason': reason,
                'vendor_id': order.vendor_id,
                'customer_id': order.customer_id,
                'previous_status': previous_status,
                'refund_status': order.refund_status,
            },
        )

        order.refresh_from_db()
        return Response(VendorOrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def review_refund(self, request, pk=None):
        order = self.get_object()
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can review refunds'}, status=status.HTTP_403_FORBIDDEN)

        if order.status != 'cancelled':
            return Response({'error': 'Refund review is only available for cancelled orders'}, status=status.HTTP_400_BAD_REQUEST)

        refund_status = (request.data.get('refund_status') or '').strip()
        if refund_status not in {'approved', 'processed', 'rejected'}:
            return Response({'error': 'refund_status must be approved, processed, or rejected'}, status=status.HTTP_400_BAD_REQUEST)

        previous_refund_status = order.refund_status
        order.refund_status = refund_status
        order.refund_reviewed_at = now()
        if refund_status in {'approved', 'processed'} and not order.refund_amount:
            order.refund_amount = order.total_amount
        order.save(update_fields=['refund_status', 'refund_amount', 'refund_reviewed_at', 'updated_at'])

        if refund_status == 'processed':
            create_notification(
                user=order.customer,
                category='payment',
                title='Vendor order refund processed',
                body=f'Refund review for order #{order.id} was processed by admin.',
            )
        elif refund_status == 'approved':
            create_notification(
                user=order.customer,
                category='payment',
                title='Vendor order refund approved',
                body=f'Refund review for order #{order.id} was approved and is awaiting processing.',
            )
        else:
            create_notification(
                user=order.customer,
                category='payment',
                title='Vendor order refund rejected',
                body=f'Refund review for order #{order.id} was rejected by admin.',
            )

        log_activity(
            actor=request.user,
            action='vendor_order_refund_reviewed',
            target_type='vendor_order',
            target_id=order.id,
            summary=f'Order #{order.id} refund review updated to {refund_status}.',
            metadata={
                'previous_refund_status': previous_refund_status,
                'refund_status': refund_status,
                'vendor_id': order.vendor_id,
                'customer_id': order.customer_id,
            },
        )

        order.refresh_from_db()
        return Response(VendorOrderSerializer(order).data)

    @action(detail=True, methods=['post'])
    def submit_feedback(self, request, pk=None):
        order = self.get_object()

        if request.user.id != order.customer_id:
            return Response({'error': 'Only the ordering customer can submit feedback'}, status=status.HTTP_403_FORBIDDEN)
        if order.status != 'completed':
            return Response({'error': 'Feedback can only be submitted for completed orders'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rating = int(request.data.get('rating'))
        except (TypeError, ValueError):
            return Response({'error': 'rating must be an integer between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

        if rating < 1 or rating > 5:
            return Response({'error': 'rating must be an integer between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

        order.rating = rating
        order.feedback_comment = request.data.get('feedback_comment', '').strip()
        order.feedback_submitted_at = now()
        order.save(update_fields=['rating', 'feedback_comment', 'feedback_submitted_at', 'updated_at'])
        order.refresh_vendor_rating()

        create_notification(
            user=order.vendor.user,
            category='booking',
            title='New vendor feedback',
            body=f'Order #{order.id} received a {rating}/5 rating from the customer.',
        )
        log_activity(
            actor=request.user,
            action='vendor_order_feedback_submitted',
            target_type='vendor_order',
            target_id=order.id,
            summary=f'Customer submitted feedback for vendor order #{order.id}.',
            metadata={'rating': rating, 'vendor_id': order.vendor_id},
        )

        order.refresh_from_db()
        return Response(VendorOrderSerializer(order).data)
