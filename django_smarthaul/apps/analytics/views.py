"""Admin analytics endpoints."""

from datetime import timedelta

from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.utils.timezone import now
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from apps.auth.models import CustomUser
from apps.analytics.models import ActivityLog
from apps.bookings.models import Booking
from apps.communications.models import SafetyReport, SupportCase
from apps.payments.models import Payment
from apps.providers.models import Provider
from apps.vendors.models import Vendor, VendorOrder


def _require_admin(request):
    if not request.user.is_authenticated:
        return Response({'error': 'Authentication required'}, status=status.HTTP_401_UNAUTHORIZED)
    if getattr(request.user, 'role', None) != 'admin':
        return Response({'error': 'Only admins can access analytics'}, status=status.HTTP_403_FORBIDDEN)
    return None


def _daily_series(queryset, date_field, value_field=None, days=7):
    start_date = (now() - timedelta(days=days - 1)).date()
    daily = (
        queryset.filter(**{f'{date_field}__date__gte': start_date})
        .annotate(day=TruncDate(date_field))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )
    if value_field is not None:
        daily = daily.annotate(total=Sum(value_field))
    return [
        {
            'date': item['day'].isoformat() if item['day'] else None,
            'count': item['count'],
            **({'total': item['total']} if value_field is not None else {}),
        }
        for item in daily
    ]


def _activity_action_counts(actions):
    return list(
        ActivityLog.objects.filter(action__in=actions)
        .values('action')
        .annotate(count=Count('id'))
        .order_by('action')
    )


def _suspicious_alerts():
    alerts = []

    pending_review_count = Booking.objects.filter(status='admin_review').count()
    if pending_review_count:
        alerts.append({
            'severity': 'high',
            'type': 'booking_review',
            'message': f'{pending_review_count} booking(s) require admin review.',
        })

    unresolved_reports = SafetyReport.objects.filter(status__in=['pending', 'under_review']).count()
    if unresolved_reports:
        alerts.append({
            'severity': 'medium',
            'type': 'safety_report_backlog',
            'message': f'{unresolved_reports} safety report(s) are awaiting resolution.',
        })

    restricted_users = CustomUser.objects.filter(account_status='restricted').count()
    banned_users = CustomUser.objects.filter(account_status='banned').count()
    if restricted_users or banned_users:
        alerts.append({
            'severity': 'medium',
            'type': 'account_restrictions',
            'message': f'{restricted_users} restricted and {banned_users} banned account(s) are on record.',
        })

    locked_accounts = CustomUser.objects.filter(locked_until__isnull=False).count()
    if locked_accounts:
        alerts.append({
            'severity': 'high',
            'type': 'login_lockouts',
            'message': f'{locked_accounts} account(s) are currently locked due to login failures.',
        })

    failed_logins = CustomUser.objects.filter(failed_login_attempts__gte=3).count()
    if failed_logins:
        alerts.append({
            'severity': 'medium',
            'type': 'failed_logins',
            'message': f'{failed_logins} account(s) have 3 or more failed login attempts.',
        })

    refund_reviews = VendorOrder.objects.filter(refund_status='pending_review').count()
    if refund_reviews:
        alerts.append({
            'severity': 'medium',
            'type': 'vendor_refund_reviews',
            'message': f'{refund_reviews} vendor order refund review(s) are pending.',
        })

    return alerts


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_summary(request):
    denial = _require_admin(request)
    if denial:
        return denial

    total_users = CustomUser.objects.count()
    active_users = CustomUser.objects.filter(account_status='active').count()
    restricted_users = CustomUser.objects.filter(account_status='restricted').count()
    banned_users = CustomUser.objects.filter(account_status='banned').count()

    booking_counts = Booking.objects.values('status').annotate(count=Count('id')).order_by('status')
    payment_counts = Payment.objects.values('status').annotate(count=Count('id')).order_by('status')
    vendor_order_counts = VendorOrder.objects.values('status').annotate(count=Count('id')).order_by('status')
    payout_counts = Payment.objects.values('payout_status').annotate(count=Count('id')).order_by('payout_status')

    completed_bookings = Booking.objects.filter(status='completed')
    completed_revenue = Payment.objects.filter(status='completed', payout_status__in=['pending', 'released']).aggregate(
        total=Sum('amount')
    )['total'] or 0
    refunded_payments = Payment.objects.filter(status='refunded').aggregate(total=Sum('amount'))['total'] or 0
    held_escrow = Payment.objects.filter(escrow_status='held').aggregate(total=Sum('amount'))['total'] or 0

    support_cases = SupportCase.objects.values('status').annotate(count=Count('id')).order_by('status')
    safety_reports = SafetyReport.objects.values('status').annotate(count=Count('id')).order_by('status')

    provider_profiles = Provider.objects.count()
    vendor_profiles = Vendor.objects.count()

    top_providers = list(
        Provider.objects.select_related('user')
        .order_by('-completed_bookings', '-total_bookings')[:5]
        .values(
            'id', 'user__first_name', 'user__last_name', 'user__email', 'service_area',
            'completed_bookings', 'total_bookings', 'rating', 'total_earnings'
        )
    )
    top_vendors = list(
        Vendor.objects.select_related('user')
        .order_by('-total_completed_orders', '-total_orders')[:5]
        .values(
            'id', 'name', 'category', 'contact_email', 'onboarding_status', 'rating',
            'total_orders', 'total_completed_orders', 'total_earnings'
        )
    )
    activity_totals = {
        'warnings': ActivityLog.objects.filter(action='account_warned').count(),
        'restrictions': ActivityLog.objects.filter(action='account_restricted').count(),
        'bans': ActivityLog.objects.filter(action__in=['account_banned', 'provider_banned']).count(),
        'support_escalations': ActivityLog.objects.filter(action='support_case_escalated').count(),
        'audit_events_total': ActivityLog.objects.count(),
    }

    return Response({
        'generated_at': now(),
        'users': {
            'total': total_users,
            'active': active_users,
            'restricted': restricted_users,
            'banned': banned_users,
            'providers': CustomUser.objects.filter(role='provider').count(),
            'vendors': CustomUser.objects.filter(role='vendor').count(),
            'customers': CustomUser.objects.filter(role='customer').count(),
            'admins': CustomUser.objects.filter(role='admin').count(),
        },
        'bookings': {
            'total': Booking.objects.count(),
            'completed': completed_bookings.count(),
            'active': Booking.objects.filter(status__in=['accepted', 'in_progress']).count(),
            'cancelled': Booking.objects.filter(status='cancelled').count(),
            'disputed': Booking.objects.filter(status='disputed').count(),
            'statuses': list(booking_counts),
            'daily': _daily_series(Booking.objects.all(), 'created_at'),
        },
        'payments': {
            'total': Payment.objects.count(),
            'completed': Payment.objects.filter(status='completed').count(),
            'refunded': Payment.objects.filter(status='refunded').count(),
            'held_in_escrow': Payment.objects.filter(escrow_status='held').count(),
            'released': Payment.objects.filter(payout_status='released').count(),
            'disputed': Payment.objects.filter(booking__has_active_dispute=True).count(),
            'status_breakdown': list(payment_counts),
            'payout_breakdown': list(payout_counts),
            'gross_completed_value': completed_revenue,
            'refunded_value': refunded_payments,
            'escrow_value': held_escrow,
            'daily': _daily_series(Payment.objects.all(), 'created_at', 'amount'),
        },
        'support': {
            'cases_total': SupportCase.objects.count(),
            'cases_by_status': list(support_cases),
            'safety_reports_total': SafetyReport.objects.count(),
            'safety_reports_by_status': list(safety_reports),
        },
        'activity': activity_totals,
        'marketplace': {
            'provider_profiles': provider_profiles,
            'vendor_profiles': vendor_profiles,
            'top_providers': top_providers,
            'top_vendors': top_vendors,
            'vendor_orders': {
                'total': VendorOrder.objects.count(),
                'cancelled': VendorOrder.objects.filter(status='cancelled').count(),
                'refund_reviews': VendorOrder.objects.filter(refund_status='pending_review').count(),
                'statuses': list(vendor_order_counts),
            },
        },
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_activity(request):
    denial = _require_admin(request)
    if denial:
        return denial

    bookings = list(
        Booking.objects.select_related('customer', 'provider')
        .order_by('-updated_at')[:5]
        .values('id', 'status', 'service_type', 'customer__email', 'provider__email', 'created_at', 'updated_at')
    )
    payments = list(
        Payment.objects.select_related('booking')
        .order_by('-updated_at')[:5]
        .values('id', 'status', 'payout_status', 'amount', 'booking_id', 'created_at', 'updated_at')
    )
    support_cases = list(
        SupportCase.objects.select_related('user')
        .order_by('-updated_at')[:5]
        .values('id', 'status', 'priority', 'user__email', 'booking_id', 'created_at', 'updated_at')
    )
    safety_reports = list(
        SafetyReport.objects.select_related('reporter')
        .order_by('-updated_at')[:5]
        .values('id', 'status', 'report_type', 'reporter__email', 'booking_id', 'created_at', 'updated_at')
    )
    activity_logs = list(
        ActivityLog.objects.select_related('actor')
        .order_by('-created_at')[:10]
        .values('id', 'action', 'target_type', 'target_id', 'summary', 'actor__email', 'actor_role', 'created_at')
    )

    for entry in bookings + payments + support_cases + safety_reports + activity_logs:
        if entry.get('created_at'):
            entry['created_at'] = entry['created_at'].isoformat()
        if entry.get('updated_at'):
            entry['updated_at'] = entry['updated_at'].isoformat()

    return Response({
        'generated_at': now(),
        'recent_bookings': bookings,
        'recent_payments': payments,
        'recent_support_cases': support_cases,
        'recent_safety_reports': safety_reports,
        'recent_activity_logs': activity_logs,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_audit(request):
    denial = _require_admin(request)
    if denial:
        return denial

    logs = ActivityLog.objects.select_related('actor').order_by('-created_at')[:50]
    payload = [
        {
            'id': log.id,
            'action': log.action,
            'target_type': log.target_type,
            'target_id': log.target_id,
            'summary': log.summary,
            'actor_email': log.actor.email if log.actor else None,
            'actor_role': log.actor_role,
            'metadata': log.metadata,
            'created_at': log.created_at.isoformat(),
        }
        for log in logs
    ]

    return Response({
        'generated_at': now(),
        'count': len(payload),
        'results': payload,
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_dashboard(request):
    denial = _require_admin(request)
    if denial:
        return denial

    today = now().date()
    seven_days_ago = today - timedelta(days=6)
    thirty_days_ago = today - timedelta(days=29)

    bookings_7d = Booking.objects.filter(created_at__date__gte=seven_days_ago)
    bookings_30d = Booking.objects.filter(created_at__date__gte=thirty_days_ago)
    payments_7d = Payment.objects.filter(created_at__date__gte=seven_days_ago)
    completed_bookings = Booking.objects.filter(status='completed')

    customer_growth = _daily_series(CustomUser.objects.filter(role='customer'), 'created_at', days=7)
    provider_growth = _daily_series(CustomUser.objects.filter(role='provider'), 'created_at', days=7)
    vendor_growth = _daily_series(CustomUser.objects.filter(role='vendor'), 'created_at', days=7)

    dispute_trend = _daily_series(Booking.objects.filter(has_active_dispute=True), 'dispute_started_at', days=7)
    report_trend = _daily_series(SafetyReport.objects.exclude(linked_entity_available=True), 'created_at', days=7)
    moderation_trend = _daily_series(
        ActivityLog.objects.filter(action__in=['account_warned', 'account_restricted', 'account_banned', 'provider_banned']),
        'created_at',
        days=7,
    )
    audit_action_breakdown = _activity_action_counts([
        'account_warned',
        'account_restricted',
        'account_banned',
        'provider_banned',
        'support_case_escalated',
        'safety_report_resolved',
        'vendor_listing_removed',
    ])
    vendor_order_status_breakdown = list(VendorOrder.objects.values('status').annotate(count=Count('id')).order_by('status'))
    vendor_order_refund_breakdown = list(VendorOrder.objects.values('refund_status').annotate(count=Count('id')).order_by('refund_status'))

    revenue_7d = payments_7d.aggregate(total=Sum('amount'))['total'] or 0
    revenue_30d = Payment.objects.filter(created_at__date__gte=thirty_days_ago).aggregate(total=Sum('amount'))['total'] or 0
    refunded_payments_7d = Payment.objects.filter(created_at__date__gte=seven_days_ago, status='refunded')
    refunded_value_7d = refunded_payments_7d.aggregate(total=Sum('amount'))['total'] or 0
    completion_rate = 0
    if bookings_30d.exists():
        completion_rate = round((completed_bookings.filter(created_at__date__gte=thirty_days_ago).count() / bookings_30d.count()) * 100, 2)

    customer_satisfaction = Booking.objects.filter(rating__isnull=False).aggregate(avg_rating=Sum('rating'))['avg_rating']
    rating_count = Booking.objects.filter(rating__isnull=False).count()
    average_rating = round((customer_satisfaction / rating_count), 2) if customer_satisfaction and rating_count else None

    return Response({
        'generated_at': now(),
        'overview': {
            'active_bookings': Booking.objects.filter(status__in=['accepted', 'in_progress']).count(),
            'revenue_7d': revenue_7d,
            'revenue_30d': revenue_30d,
            'refunded_value_7d': refunded_value_7d,
            'completion_rate_30d': completion_rate,
            'average_rating': average_rating,
            'dispute_count': Booking.objects.filter(has_active_dispute=True).count(),
            'pending_reports': SafetyReport.objects.filter(status__in=['pending', 'under_review']).count(),
            'pending_vendor_refunds': VendorOrder.objects.filter(refund_status='pending_review').count(),
            'audit_events_7d': ActivityLog.objects.filter(created_at__date__gte=seven_days_ago).count(),
        },
        'trends': {
            'bookings_7d': _daily_series(bookings_7d, 'created_at', days=7),
            'payments_7d': _daily_series(payments_7d, 'created_at', 'amount', days=7),
            'refunded_payments_7d': _daily_series(refunded_payments_7d, 'created_at', 'amount', days=7),
            'customer_growth_7d': customer_growth,
            'provider_growth_7d': provider_growth,
            'vendor_growth_7d': vendor_growth,
            'dispute_trend_7d': dispute_trend,
            'report_trend_7d': report_trend,
            'moderation_trend_7d': moderation_trend,
            'audit_action_breakdown': audit_action_breakdown,
            'vendor_order_status_breakdown': vendor_order_status_breakdown,
            'vendor_order_refund_breakdown': vendor_order_refund_breakdown,
        },
        'alerts': _suspicious_alerts(),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def analytics_alerts(request):
    denial = _require_admin(request)
    if denial:
        return denial

    alerts = _suspicious_alerts()
    return Response({
        'generated_at': now(),
        'count': len(alerts),
        'results': alerts,
    })
