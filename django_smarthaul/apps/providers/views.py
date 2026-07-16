"""Providers views."""
from django.utils.timezone import now
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from apps.analytics.models import log_activity
from .models import Provider
from .serializers import ProviderSerializer


class ProviderViewSet(viewsets.ModelViewSet):
    """Provider management viewset."""
    
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        """Create provider profile for current user."""
        if request.user.account_status == 'banned':
            return Response({'error': 'Banned accounts cannot submit verification'}, status=status.HTTP_403_FORBIDDEN)

        if hasattr(request.user, 'provider_profile'):
            provider = request.user.provider_profile
            if provider.verification_status in ['rejected', 'needs_more_info']:
                return self._resubmit_verification(request, provider)
            return Response(
                {'error': 'User already has a provider profile'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        provider = Provider.objects.create(
            user=request.user,
            verification_status='pending_review',
            verification_submitted_at=now(),
            **serializer.validated_data,
        )
        log_activity(
            actor=request.user,
            action='provider_verification_submitted',
            target_type='provider',
            target_id=provider.id,
            summary=f'Provider profile #{provider.id} submitted for verification.',
            metadata={'service_area': provider.service_area},
        )
        return Response(ProviderSerializer(provider).data, status=status.HTTP_201_CREATED)

    def _resubmit_verification(self, request, provider):
        serializer = self.get_serializer(provider, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        for field, value in serializer.validated_data.items():
            setattr(provider, field, value)

        provider.verification_status = 'pending_review'
        provider.verification_notes = ''
        provider.verification_submitted_at = now()
        provider.verification_reviewed_at = None
        provider.save()
        log_activity(
            actor=request.user,
            action='provider_verification_resubmitted',
            target_type='provider',
            target_id=provider.id,
            summary=f'Provider profile #{provider.id} was resubmitted for verification.',
            metadata={'service_area': provider.service_area},
        )
        return Response(ProviderSerializer(provider).data, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def my_profile(self, request):
        """Get current provider profile."""
        try:
            provider = request.user.provider_profile
            return Response(ProviderSerializer(provider).data)
        except Provider.DoesNotExist:
            return Response(
                {'error': 'Provider profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve provider verification (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can approve providers'}, status=status.HTTP_403_FORBIDDEN)

        provider = self.get_object()
        provider.verification_status = 'approved'
        provider.verification_notes = ''
        provider.verification_reviewed_at = now()
        provider.save(update_fields=['verification_status', 'verification_notes', 'verification_reviewed_at', 'updated_at'])
        log_activity(
            actor=request.user,
            action='provider_verification_approved',
            target_type='provider',
            target_id=provider.id,
            summary=f'Provider profile #{provider.id} was approved.',
            metadata={'provider_user_id': provider.user_id},
        )

        return Response(ProviderSerializer(provider).data)

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject provider verification (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can reject providers'}, status=status.HTTP_403_FORBIDDEN)

        provider = self.get_object()
        provider.verification_status = 'rejected'
        provider.verification_notes = request.data.get('reason', '')
        provider.verification_reviewed_at = now()
        provider.save(update_fields=['verification_status', 'verification_notes', 'verification_reviewed_at', 'updated_at'])
        log_activity(
            actor=request.user,
            action='provider_verification_rejected',
            target_type='provider',
            target_id=provider.id,
            summary=f'Provider profile #{provider.id} was rejected.',
            metadata={'reason': provider.verification_notes, 'provider_user_id': provider.user_id},
        )

        return Response(ProviderSerializer(provider).data)

    @action(detail=False, methods=['post'])
    def resubmit(self, request):
        """Resubmit a rejected or needs-more-info provider verification."""
        try:
            provider = request.user.provider_profile
        except Provider.DoesNotExist:
            return Response({'error': 'Provider profile not found'}, status=status.HTTP_404_NOT_FOUND)

        if request.user.account_status == 'banned':
            return Response({'error': 'Banned accounts cannot resubmit verification'}, status=status.HTTP_403_FORBIDDEN)

        if provider.verification_status not in ['rejected', 'needs_more_info']:
            return Response({'error': 'Verification is not in a resubmittable state'}, status=status.HTTP_400_BAD_REQUEST)

        return self._resubmit_verification(request, provider)
    
    @action(detail=False, methods=['post'])
    def toggle_availability(self, request):
        """Toggle provider availability."""
        try:
            provider = request.user.provider_profile
            if provider.permanently_banned:
                return Response(
                    {'error': 'Banned providers cannot change availability'},
                    status=status.HTTP_403_FORBIDDEN
                )

            provider.is_available = not provider.is_available
            provider.save()
            return Response(ProviderSerializer(provider).data)
        except Provider.DoesNotExist:
            return Response(
                {'error': 'Provider profile not found'},
                status=status.HTTP_404_NOT_FOUND
            )
    
    @action(detail=True, methods=['post'])
    def ban(self, request, pk=None):
        """Ban provider (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can ban providers'}, status=status.HTTP_403_FORBIDDEN)
        
        provider = self.get_object()
        provider.permanently_banned = True
        provider.ban_reason = request.data.get('reason', '')
        provider.is_available = False
        provider.verification_status = 'rejected'
        provider.verification_notes = provider.ban_reason
        provider.verification_reviewed_at = now()
        provider.save()
        log_activity(
            actor=request.user,
            action='provider_banned',
            target_type='provider',
            target_id=provider.id,
            summary=f'Provider profile #{provider.id} was banned.',
            metadata={'reason': provider.ban_reason, 'provider_user_id': provider.user_id},
        )
        
        return Response(ProviderSerializer(provider).data)
