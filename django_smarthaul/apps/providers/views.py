"""Providers views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Provider
from .serializers import ProviderSerializer


class ProviderViewSet(viewsets.ModelViewSet):
    """Provider management viewset."""
    
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        """Create provider profile for current user."""
        if hasattr(request.user, 'provider_profile'):
            return Response(
                {'error': 'User already has a provider profile'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        provider = Provider.objects.create(user=request.user, **serializer.validated_data)
        return Response(ProviderSerializer(provider).data, status=status.HTTP_201_CREATED)
    
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
        provider.save()
        
        return Response(ProviderSerializer(provider).data)
