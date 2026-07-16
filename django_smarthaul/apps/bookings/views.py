"""Bookings views."""
from datetime import timedelta
from decimal import Decimal
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.utils.dateparse import parse_datetime
from django.utils.timezone import now
from apps.analytics.models import log_activity
from .models import Booking, BookingTracking, CallLog
from .serializers import (
    BookingSerializer, BookingCreateSerializer, BookingUpdateSerializer,
    BookingTrackingSerializer, CallLogSerializer
)
from apps.communications.views import create_notification


class BookingViewSet(viewsets.ModelViewSet):
    """Booking management viewset."""
    
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter bookings based on user role."""
        self._expire_stale_pending_bookings()
        user = self.request.user
        if user.role == 'admin':
            return Booking.objects.all()
        elif user.role == 'provider':
            return Booking.objects.filter(provider=user)
        else:  # customer or vendor
            return Booking.objects.filter(customer=user)
    
    def get_serializer_class(self):
        """Get appropriate serializer based on action."""
        if self.action == 'create':
            return BookingCreateSerializer
        elif self.action in ['partial_update', 'update']:
            return BookingUpdateSerializer
        return BookingSerializer

    def get_booking(self, pk):
        """Fetch a booking for detail actions without applying list-level role filters."""
        self._expire_stale_pending_bookings(booking_ids=[pk])
        return Booking.objects.get(pk=pk)

    def _expire_stale_pending_bookings(self, booking_ids=None):
        """Auto-cancel pending bookings that exceeded the acceptance window."""
        threshold = now()
        queryset = Booking.objects.filter(status='pending', pending_expires_at__lte=threshold)
        if booking_ids is not None:
            queryset = queryset.filter(id__in=booking_ids)

        for booking in queryset.select_related('customer'):
            booking.status = 'cancelled'
            booking.cancelled_by = 'system'
            booking.save(update_fields=['status', 'cancelled_by', 'updated_at'])
            create_notification(
                user=booking.customer,
                category='booking',
                title='Booking expired',
                body=(
                    f'Booking #{booking.id} expired because no provider accepted it within '
                    f'{booking.pending_timeout_minutes} minutes.'
                ),
                booking_id=booking.id,
            )

    @action(detail=False, methods=['post'])
    def check_pending_timeouts(self, request):
        """Admin or system-triggered check for bookings that timed out while pending."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can run this check'}, status=status.HTTP_403_FORBIDDEN)

        threshold = now()
        timed_out = Booking.objects.filter(status='pending', pending_expires_at__lte=threshold)
        expired_ids = []
        for booking in timed_out.select_related('customer'):
            booking.status = 'cancelled'
            booking.cancelled_by = 'system'
            booking.save(update_fields=['status', 'cancelled_by', 'updated_at'])
            create_notification(
                user=booking.customer,
                category='booking',
                title='Booking expired',
                body=(
                    f'Booking #{booking.id} expired because no provider accepted it within '
                    f'{booking.pending_timeout_minutes} minutes.'
                ),
                booking_id=booking.id,
            )
            expired_ids.append(booking.id)

        return Response({
            'expired_bookings': expired_ids,
            'count': len(expired_ids),
        })
    
    def create(self, request, *args, **kwargs):
        """Create a new booking."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        booking = Booking.objects.create(
            customer=request.user,
            **serializer.validated_data
        )

        create_notification(
            user=request.user,
            category='booking',
            title='Booking created',
            body=f'Booking #{booking.id} was created and is pending provider acceptance.',
            booking_id=booking.id,
        )
        
        return Response(
            BookingSerializer(booking).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['post'])
    def accept_booking(self, request, pk=None):
        """Accept a booking (provider only)."""
        booking = self.get_booking(pk)
        
        if request.user.role != 'provider':
            return Response(
                {'error': 'Only providers can accept bookings'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if booking.status != 'pending':
            return Response(
                {'error': f'Cannot accept booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if booking.pending_expires_at and booking.pending_expires_at <= now():
            booking.status = 'cancelled'
            booking.cancelled_by = 'system'
            booking.save(update_fields=['status', 'cancelled_by', 'updated_at'])
            create_notification(
                user=booking.customer,
                category='booking',
                title='Booking expired',
                body=(
                    f'Booking #{booking.id} expired because no provider accepted it within '
                    f'{booking.pending_timeout_minutes} minutes.'
                ),
                booking_id=booking.id,
            )
            return Response(
                {'error': 'Booking expired before acceptance'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        booking.provider = request.user
        booking.status = 'accepted'
        booking.accepted_at = now()
        booking.save()
        log_activity(
            actor=request.user,
            action='booking_accepted',
            target_type='booking',
            target_id=booking.id,
            summary=f'Provider accepted booking #{booking.id}.',
            metadata={'customer_id': booking.customer_id, 'provider_id': request.user.id},
        )

        create_notification(
            user=booking.customer,
            category='booking',
            title='Booking accepted',
            body=f'Provider {request.user.get_full_name() or request.user.username} accepted booking #{booking.id}.',
            booking_id=booking.id,
        )
        
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def start_booking(self, request, pk=None):
        """Start a booking."""
        booking = self.get_booking(pk)
        
        if booking.status != 'accepted':
            return Response(
                {'error': f'Cannot start booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        booking.status = 'in_progress'
        booking.save()
        
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def complete_booking(self, request, pk=None):
        """Complete a booking."""
        booking = self.get_booking(pk)
        
        if booking.status != 'in_progress':
            return Response(
                {'error': f'Cannot complete booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        booking.complete_booking()
        log_activity(
            actor=request.user,
            action='booking_completed',
            target_type='booking',
            target_id=booking.id,
            summary=f'Booking #{booking.id} was marked completed.',
            metadata={'customer_id': booking.customer_id, 'provider_id': booking.provider_id},
        )

        create_notification(
            user=booking.customer,
            category='booking',
            title='Booking completed',
            body=f'Booking #{booking.id} was marked complete.',
            booking_id=booking.id,
        )
        
        return Response(BookingSerializer(booking).data)

    @action(detail=True, methods=['post'])
    def reschedule_booking(self, request, pk=None):
        """Request, accept, or reject a booking reschedule."""
        booking = self.get_booking(pk)
        decision = (request.data.get('decision') or 'request').strip().lower()

        if booking.status not in ['accepted', 'in_progress']:
            return Response(
                {'error': f'Cannot reschedule booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if decision == 'request':
            if request.user.id not in [booking.customer_id, booking.provider_id]:
                return Response({'error': 'Only booking parties can request a reschedule'}, status=status.HTTP_403_FORBIDDEN)

            proposed_for = parse_datetime(request.data.get('proposed_for_at') or '')
            if proposed_for is None:
                return Response({'error': 'proposed_for_at is required and must be an ISO datetime'}, status=status.HTTP_400_BAD_REQUEST)

            booking.scheduled_for_at = booking.scheduled_for_at or proposed_for
            booking.reschedule_status = 'pending'
            booking.reschedule_requested_by = request.user.role
            booking.reschedule_requested_at = now()
            booking.reschedule_proposed_for_at = proposed_for
            booking.reschedule_reason = request.data.get('reason', '')
            booking.reschedule_response_at = None
            booking.save()

            counterparty = booking.provider if request.user.id == booking.customer_id else booking.customer
            create_notification(
                user=counterparty,
                category='booking',
                title='Reschedule requested',
                body=(
                    f'Booking #{booking.id} has a reschedule request for '
                    f'{proposed_for.isoformat()}. Please review it.'
                ),
                booking_id=booking.id,
            )

            return Response(BookingSerializer(booking).data, status=status.HTTP_200_OK)

        if decision not in ['accept', 'reject']:
            return Response({'error': "decision must be 'request', 'accept', or 'reject'"}, status=status.HTTP_400_BAD_REQUEST)

        if booking.reschedule_status != 'pending':
            return Response({'error': 'There is no pending reschedule request'}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.role == booking.reschedule_requested_by:
            return Response({'error': 'The requester cannot respond to their own reschedule request'}, status=status.HTTP_403_FORBIDDEN)

        if decision == 'accept':
            booking.scheduled_for_at = booking.reschedule_proposed_for_at or booking.scheduled_for_at
            booking.reschedule_status = 'accepted'
            booking.reschedule_response_at = now()
            booking.save()

            requester = booking.customer if booking.reschedule_requested_by == 'customer' else booking.provider
            create_notification(
                user=requester,
                category='booking',
                title='Reschedule accepted',
                body=(
                    f'Your reschedule request for booking #{booking.id} was accepted. '
                    f'New schedule: {booking.scheduled_for_at.isoformat() if booking.scheduled_for_at else "unscheduled"}.'
                ),
                booking_id=booking.id,
            )
            return Response(BookingSerializer(booking).data)

        booking.reschedule_status = 'rejected'
        booking.reschedule_response_at = now()
        booking.save()

        requester = booking.customer if booking.reschedule_requested_by == 'customer' else booking.provider
        create_notification(
            user=requester,
            category='booking',
            title='Reschedule rejected',
            body=f'Your reschedule request for booking #{booking.id} was rejected.',
            booking_id=booking.id,
        )
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def cancel_booking(self, request, pk=None):
        """Cancel a booking."""
        booking = self.get_booking(pk)
        original_status = booking.status

        if original_status not in ['pending', 'accepted']:
            return Response(
                {'error': f'Cannot cancel booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.cancelled_by = request.user.role
        booking.status = 'cancelled'

        current_time = now()
        within_window = booking.is_within_cancellation_window(current_time=current_time)
        fee_applies = original_status in ['accepted', 'in_progress'] and not within_window

        if fee_applies:
            booking.cancellation_fee_owed = (booking.price * (booking.cancellation_fee_percent / Decimal('100'))).quantize(
                Decimal('0.01')
            )
            booking.cancellation_fee_paid_by = request.user.role
            booking.cancellation_fee_logged_at = current_time

        # Refund escrow automatically when the cancellation should not incur a fee.
        if hasattr(booking, 'payment'):
            payment = booking.payment
            if payment.escrow_status == 'held' and payment.status == 'completed':
                should_refund = (
                    request.user.role == 'provider' and fee_applies
                ) or (
                    request.user.role == 'customer' and not fee_applies
                )
                if should_refund:
                    payment.status = 'refunded'
                    payment.escrow_status = 'refunded'
                    payment.save(update_fields=['status', 'escrow_status', 'updated_at'])

        booking.save()
        log_activity(
            actor=request.user,
            action='booking_cancelled',
            target_type='booking',
            target_id=booking.id,
            summary=f'Booking #{booking.id} was cancelled by {request.user.role}.',
            metadata={'cancelled_by': request.user.role, 'fee_applies': bool(fee_applies)},
        )

        create_notification(
            user=booking.customer,
            category='booking',
            title='Booking cancelled',
            body=f'Booking #{booking.id} was cancelled by {request.user.role}.',
            booking_id=booking.id,
        )
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def add_tracking(self, request, pk=None):
        """Add location tracking for a booking."""
        booking = self.get_booking(pk)
        
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        if not latitude or not longitude:
            return Response(
                {'error': 'Latitude and longitude are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        tracking = BookingTracking.objects.create(
            booking=booking,
            latitude=latitude,
            longitude=longitude
        )
        
        # Update booking location and provider last ping timestamp
        booking.current_latitude = latitude
        booking.current_longitude = longitude
        booking.provider_last_ping_at = now()
        booking.save()
        
        return Response(
            BookingTrackingSerializer(tracking).data,
            status=status.HTTP_201_CREATED
        )
    
    @action(detail=True, methods=['get'])
    def tracking_history(self, request, pk=None):
        """Get booking tracking history."""
        booking = self.get_booking(pk)
        tracking = booking.tracking_events.all().order_by('created_at')
        serializer = BookingTrackingSerializer(tracking, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def my_bookings(self, request):
        """Get current user's bookings."""
        bookings = self.get_queryset()
        serializer = self.get_serializer(bookings, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def provider_heartbeat(self, request, pk=None):
        """Provider activity ping for an accepted/in-progress booking."""
        booking = self.get_booking(pk)

        if request.user.role != 'provider' or booking.provider_id != request.user.id:
            return Response(
                {'error': 'Only the assigned provider can send a heartbeat'},
                status=status.HTTP_403_FORBIDDEN
            )

        if booking.status not in ['accepted', 'in_progress']:
            return Response(
                {'error': f'Cannot send heartbeat for booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )

        booking.provider_last_ping_at = now()
        booking.save(update_fields=['provider_last_ping_at'])

        return Response({
            'status': 'heartbeat_recorded',
            'booking_id': booking.id,
            'timestamp': booking.provider_last_ping_at,
        })

    @action(detail=False, methods=['post'])
    def check_unresponsive_providers(self, request):
        """Admin: escalate accepted bookings with no provider activity in 15+ minutes."""
        if request.user.role != 'admin':
            return Response(
                {'error': 'Only admins can run this check'},
                status=status.HTTP_403_FORBIDDEN
            )

        threshold = now() - timedelta(minutes=15)

        # Unresponsive if: no ping ever and accepted >15 min ago, OR last ping >15 min ago
        unresponsive = Booking.objects.filter(status='accepted').filter(
            Q(provider_last_ping_at__isnull=True, accepted_at__lt=threshold)
            | Q(provider_last_ping_at__lt=threshold)
        )

        escalated_ids = []
        for booking in unresponsive:
            booking.status = 'admin_review'
            booking.save(update_fields=['status'])
            escalated_ids.append(booking.id)

        return Response({
            'escalated_bookings': escalated_ids,
            'count': len(escalated_ids),
            'message': (
                'Bookings escalated to admin_review due to unresponsive provider. '
                'Admin must decide to reassign or cancel with full refund.'
            ),
        })

    @action(detail=True, methods=['post'])
    def start_call(self, request, pk=None):
        """Start a call for a booking and log if dispute/safety report is active."""
        booking = self.get_booking(pk)

        caller_id = request.data.get('caller_id')
        recipient_id = request.data.get('recipient_id')
        call_type = request.data.get('call_type', 'outbound')
        call_medium = request.data.get('call_medium', 'audio')
        consent_acknowledged = request.data.get('consent_acknowledged', False)

        if not caller_id or not recipient_id:
            return Response(
                {'error': 'caller_id and recipient_id are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if str(consent_acknowledged).lower() not in ['true', '1', 'yes']:
            return Response(
                {'error': 'Consent must be acknowledged before starting a call'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determine if call should be logged
        should_log, reason = CallLog.should_log_call(booking)

        call_log = CallLog.objects.create(
            booking=booking,
            caller_id=caller_id,
            recipient_id=recipient_id,
            call_type=call_type,
            call_medium=call_medium,
            consent_acknowledged=True,
            started_at=now(),
            call_should_be_logged=should_log,
            reason_for_logging=reason or ''
        )

        return Response(
            CallLogSerializer(call_log).data,
            status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=['post'], url_path='calls/(?P<call_id>[0-9]+)/end')
    def end_call(self, request, pk=None, call_id=None):
        """End a call log and record duration."""
        try:
            call_log = CallLog.objects.get(id=call_id, booking_id=pk)
        except CallLog.DoesNotExist:
            return Response(
                {'error': 'Call log not found'},
                status=status.HTTP_404_NOT_FOUND
            )

        call_log.ended_at = now()
        if call_log.started_at:
            call_log.duration_seconds = int((call_log.ended_at - call_log.started_at).total_seconds())
        call_log.save()

        return Response(CallLogSerializer(call_log).data)

    @action(detail=True, methods=['post'])
    def file_dispute_or_report(self, request, pk=None):
        """Admin: mark a booking as having an active dispute or safety report filed."""
        if request.user.role != 'admin':
            return Response(
                {'error': 'Only admins can file disputes or reports'},
                status=status.HTTP_403_FORBIDDEN
            )

        booking = self.get_booking(pk)
        dispute_active = request.data.get('dispute_active', False)
        safety_report_filed = request.data.get('safety_report_filed', False)

        if dispute_active:
            booking.has_active_dispute = True
            booking.dispute_started_at = now()
        
        if safety_report_filed:
            booking.safety_report_filed_at = now()

        booking.save()

        return Response({
            'booking_id': booking.id,
            'has_active_dispute': booking.has_active_dispute,
            'dispute_started_at': booking.dispute_started_at,
            'safety_report_filed_at': booking.safety_report_filed_at,
            'message': 'Booking dispute/report status updated. Future calls will be logged.'
        })

    @action(detail=True, methods=['get'])
    def call_logs(self, request, pk=None):
        """Get all call logs for a booking (only accessible to booking parties and admin)."""
        booking = self.get_booking(pk)

        # Only allow access if user is customer, provider, or admin
        if (request.user.role != 'admin' and 
            request.user.id != booking.customer_id and 
            request.user.id != booking.provider_id):
            return Response(
                {'error': 'Not authorized to view call logs for this booking'},
                status=status.HTTP_403_FORBIDDEN
            )

        calls = booking.call_logs.all().order_by('-created_at')
        serializer = CallLogSerializer(calls, many=True)
        return Response(serializer.data)
