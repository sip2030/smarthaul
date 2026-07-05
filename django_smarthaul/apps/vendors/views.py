"""Vendors views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .models import Vendor
from .serializers import VendorSerializer


class VendorViewSet(viewsets.ModelViewSet):
    """Vendor management viewset."""
    
    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated]
    
    def create(self, request, *args, **kwargs):
        """Create vendor profile for current user."""
        if hasattr(request.user, 'vendor_profile'):
            return Response(
                {'error': 'User already has a vendor profile'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        vendor = Vendor.objects.create(user=request.user, **serializer.validated_data)
        return Response(VendorSerializer(vendor).data, status=status.HTTP_201_CREATED)
    
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
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve vendor (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can approve vendors'}, status=status.HTTP_403_FORBIDDEN)
        
        vendor = self.get_object()
        vendor.onboarding_status = 'approved'
        vendor.save()
        
        return Response(VendorSerializer(vendor).data)
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject vendor (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can reject vendors'}, status=status.HTTP_403_FORBIDDEN)
        
        vendor = self.get_object()
        vendor.onboarding_status = 'rejected'
        vendor.onboarding_notes = request.data.get('reason', '')
        vendor.save()
        
        return Response(VendorSerializer(vendor).data)
