from django.utils.timezone import now
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.analytics.models import log_activity
from apps.auth.models import CustomUser
from apps.bookings.models import Booking
from .models import Notification, SupportCase, SafetyReport
from .serializers import (
    NotificationSerializer,
    SupportCaseSerializer,
    SupportCaseCreateSerializer,
    SafetyReportSerializer,
    SafetyReportCreateSerializer,
)


def create_notification(*, user, category, title, body, booking_id=None):
    return Notification.objects.create(
        user=user,
        category=category,
        title=title,
        body=body,
        booking_id=booking_id,
    )


def notify_admins(*, category, title, body, booking_id=None):
    admins = CustomUser.objects.filter(role='admin')
    for admin in admins:
        create_notification(
            user=admin,
            category=category,
            title=title,
            body=body,
            booking_id=booking_id,
        )


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        notification.mark_read()
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=['post'])
    def mark_all_read(self, request):
        updated = self.get_queryset().filter(read_at__isnull=True)
        timestamp = now()
        updated.update(read_at=timestamp)
        return Response({'count': updated.count(), 'status': 'ok'})

    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        return Response({'count': self.get_queryset().filter(read_at__isnull=True).count()})


class SupportCaseViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return SupportCase.objects.all()
        return SupportCase.objects.filter(user=user)

    def get_serializer_class(self):
        if self.action == 'create':
            return SupportCaseCreateSerializer
        return SupportCaseSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.validated_data.get('booking')
        if booking and booking.customer_id != request.user.id:
            return Response({'error': 'You can only open cases for your own bookings'}, status=status.HTTP_403_FORBIDDEN)

        support_case = SupportCase.objects.create(user=request.user, **serializer.validated_data)
        support_case.ai_summary = self._generate_ai_summary(support_case)
        support_case.save(update_fields=['ai_summary'])
        create_notification(
            user=request.user,
            category='support',
            title='Support case opened',
            body='Your support case has been created and is awaiting review.',
            booking_id=support_case.booking_id,
        )
        log_activity(
            actor=request.user,
            action='support_case_created',
            target_type='support_case',
            target_id=support_case.id,
            summary=f'Support case #{support_case.id} was created.',
            metadata={'booking_id': support_case.booking_id, 'priority': support_case.priority},
        )
        return Response(SupportCaseSerializer(support_case).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def escalate(self, request, pk=None):
        support_case = self.get_object()
        if request.user.role != 'admin' and support_case.user_id != request.user.id:
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)
        support_case.mark_escalated(summary=support_case.ai_summary or self._generate_ai_summary(support_case))
        create_notification(
            user=support_case.user,
            category='support',
            title='Support case escalated',
            body='Your case has been escalated to a human support agent.',
            booking_id=support_case.booking_id,
        )
        log_activity(
            actor=request.user,
            action='support_case_escalated',
            target_type='support_case',
            target_id=support_case.id,
            summary=f'Support case #{support_case.id} was escalated.',
            metadata={'booking_id': support_case.booking_id},
        )
        return Response(SupportCaseSerializer(support_case).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        support_case = self.get_object()
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can resolve cases'}, status=status.HTTP_403_FORBIDDEN)
        support_case.status = 'resolved'
        support_case.resolution_notes = request.data.get('resolution_notes', support_case.resolution_notes)
        support_case.resolved_at = now()
        support_case.save(update_fields=['status', 'resolution_notes', 'resolved_at', 'updated_at'])
        create_notification(
            user=support_case.user,
            category='support',
            title='Support case resolved',
            body='Your support case has been resolved.',
            booking_id=support_case.booking_id,
        )
        log_activity(
            actor=request.user,
            action='support_case_resolved',
            target_type='support_case',
            target_id=support_case.id,
            summary=f'Support case #{support_case.id} was resolved.',
            metadata={'booking_id': support_case.booking_id},
        )
        return Response(SupportCaseSerializer(support_case).data)

    @action(detail=False, methods=['post'])
    def assistant(self, request):
        booking_id = request.data.get('booking_id')
        question = (request.data.get('question') or '').strip()
        booking = None
        if booking_id:
            try:
                booking = Booking.objects.get(id=booking_id, customer=request.user)
            except Booking.DoesNotExist:
                return Response({'error': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

        answer, needs_human = self._answer_question(question, booking)
        payload = {'answer': answer, 'needs_human_support': needs_human}
        if needs_human:
            support_case = SupportCase.objects.create(
                user=request.user,
                booking=booking,
                subject='AI escalated support request',
                description=question,
                status='escalated',
                priority='normal',
                ai_summary=answer,
            )
            create_notification(
                user=request.user,
                category='support',
                title='Human support requested',
                body='Your request has been escalated to human support.',
                booking_id=support_case.booking_id,
            )
            payload['support_case_id'] = support_case.id
        return Response(payload)

    def _generate_ai_summary(self, support_case):
        booking_ref = f' for booking #{support_case.booking_id}' if support_case.booking_id else ''
        return f'Support case opened{booking_ref} with priority {support_case.priority}. Human review recommended.'

    def _answer_question(self, question, booking):
        normalized = question.lower()
        if not question:
            return 'Please describe your issue so support can help.', True
        if 'refund' in normalized:
            return 'Refunds are reviewed after payment verification or a valid dispute. If you want, I can open a support case.', False
        if 'cancel' in normalized and booking:
            return f'Booking #{booking.id} can be cancelled from the booking screen, subject to the cancellation rules.', False
        if 'driver' in normalized or 'provider' in normalized:
            return 'I can help with provider status, but if the issue is urgent I can escalate it to human support.', True
        return 'I can help with booking, payment, or tracking questions. If you need human help, I can escalate this now.', True


class SafetyReportViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'admin':
            return SafetyReport.objects.all()
        return SafetyReport.objects.filter(reporter=user)

    def get_serializer_class(self):
        if self.action == 'create':
            return SafetyReportCreateSerializer
        return SafetyReportSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_data = dict(serializer.validated_data)
        booking = validated_data.pop('booking', None)
        target_user = validated_data.pop('target_user', None)
        target_reference = validated_data.pop('target_reference', '') or ''
        linked_entity_available = validated_data.pop('linked_entity_available', True)
        linked_entity_note = validated_data.pop('linked_entity_note', '')

        if not target_reference:
            if booking is not None:
                target_reference = str(booking.id)
            elif target_user is not None:
                target_reference = str(target_user.id)
            else:
                target_reference = serializer.validated_data.get('target_name', '')

        if booking is None and target_user is None:
            linked_entity_available = False
            if not linked_entity_note:
                linked_entity_note = 'Referenced entity was unavailable at the time of report submission.'

        if booking and booking.customer_id != request.user.id and booking.provider_id != request.user.id and request.user.role != 'admin':
            # Third-party reports are allowed, but the report must at least reference a target user or booking.
            if not target_user:
                return Response({'error': 'Provide a target_user when reporting a booking you are not part of.'}, status=status.HTTP_400_BAD_REQUEST)

        report = SafetyReport.objects.create(
            reporter=request.user,
            booking=booking,
            target_user=target_user,
            target_reference=target_reference,
            linked_entity_available=linked_entity_available,
            linked_entity_note=linked_entity_note,
            **validated_data,
        )
        create_notification(
            user=request.user,
            category='moderation',
            title='Safety report submitted',
            body=f'Your {report.report_type} report has been submitted and is pending review.',
            booking_id=report.booking_id,
        )
        log_activity(
            actor=request.user,
            action='safety_report_created',
            target_type='safety_report',
            target_id=report.id,
            summary=f'Safety report #{report.id} was submitted.',
            metadata={'booking_id': report.booking_id, 'report_type': report.report_type},
        )
        notify_admins(
            category='moderation',
            title='New safety report',
            body=(
                f'A new {report.report_type} report needs review.'
                if report.linked_entity_available
                else f'A new {report.report_type} report references an unavailable entity and needs review.'
            ),
            booking_id=report.booking_id,
        )
        return Response(SafetyReportSerializer(report).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def mark_under_review(self, request, pk=None):
        report = self.get_object()
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can review reports'}, status=status.HTTP_403_FORBIDDEN)
        report.mark_under_review(request.user)
        create_notification(
            user=report.reporter,
            category='moderation',
            title='Safety report under review',
            body=f'Your {report.report_type} report is now under review.',
            booking_id=report.booking_id,
        )
        log_activity(
            actor=request.user,
            action='safety_report_under_review',
            target_type='safety_report',
            target_id=report.id,
            summary=f'Safety report #{report.id} was marked under review.',
            metadata={'booking_id': report.booking_id, 'report_type': report.report_type},
        )
        return Response(SafetyReportSerializer(report).data)

    @action(detail=True, methods=['post'])
    def resolve(self, request, pk=None):
        report = self.get_object()
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can resolve reports'}, status=status.HTTP_403_FORBIDDEN)

        action_name = (request.data.get('moderation_action') or '').strip()
        notes = request.data.get('moderator_notes', '')
        report.mark_resolved(request.user, notes=notes, action=action_name)

        target_user = report.target_user
        if action_name == 'restrict_account' and target_user is not None:
            target_user.account_status = 'restricted'
            target_user.account_restricted_reason = notes or f'Safety report #{report.id}'
            target_user.account_restricted_at = now()
            target_user.save(update_fields=['account_status', 'account_restricted_reason', 'account_restricted_at', 'updated_at'])
        elif action_name == 'ban_account' and target_user is not None:
            target_user.account_status = 'banned'
            target_user.account_restricted_reason = notes or f'Safety report #{report.id}'
            target_user.account_restricted_at = now()
            target_user.save(update_fields=['account_status', 'account_restricted_reason', 'account_restricted_at', 'updated_at'])

        create_notification(
            user=report.reporter,
            category='moderation',
            title='Safety report resolved',
            body=f'Your {report.report_type} report has been resolved.',
            booking_id=report.booking_id,
        )
        log_activity(
            actor=request.user,
            action='safety_report_resolved',
            target_type='safety_report',
            target_id=report.id,
            summary=f'Safety report #{report.id} was resolved.',
            metadata={'booking_id': report.booking_id, 'action': action_name},
        )
        return Response(SafetyReportSerializer(report).data)

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        report = self.get_object()
        if request.user.role != 'admin' and report.reporter_id != request.user.id:
            return Response({'error': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)
        report.mark_closed(moderator=request.user if request.user.role == 'admin' else None, notes=request.data.get('notes', ''))
        return Response(SafetyReportSerializer(report).data)
