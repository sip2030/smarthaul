"""Bookings views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils.timezone import now
from .models import Booking, BookingTracking
from .serializers import (
    BookingSerializer, BookingCreateSerializer, BookingUpdateSerializer, 
    BookingTrackingSerializer
)


class BookingViewSet(viewsets.ModelViewSet):
    """Booking management viewset."""
    
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter bookings based on user role."""
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
        return Booking.objects.get(pk=pk)
    
    def create(self, request, *args, **kwargs):
        """Create a new booking."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        booking = Booking.objects.create(
            customer=request.user,
            **serializer.validated_data
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
        
        booking.provider = request.user
        booking.status = 'accepted'
        booking.save()
        
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
        
        return Response(BookingSerializer(booking).data)
    
    @action(detail=True, methods=['post'])
    def cancel_booking(self, request, pk=None):
        """Cancel a booking."""
        booking = self.get_booking(pk)
        
        if booking.status not in ['pending', 'accepted']:
            return Response(
                {'error': f'Cannot cancel booking in {booking.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        booking.status = 'cancelled'
        booking.save()
        
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
        
        # Update booking location
        booking.current_latitude = latitude
        booking.current_longitude = longitude
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
