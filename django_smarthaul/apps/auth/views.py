"""Auth views."""
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.utils.timezone import now
from .models import CustomUser
from .serializers import UserSerializer, RegisterSerializer, LoginSerializer, LoginResponseSerializer
from .authentication import generate_jwt_token


class AuthViewSet(viewsets.ViewSet):
    """Authentication endpoints."""
    
    permission_classes = [AllowAny]

    def get_permissions(self):
        """Apply strict permissions for protected actions when using manual as_view mappings."""
        protected_actions = {'me', 'logout', 'change_password'}
        if getattr(self, 'action', None) in protected_actions:
            return [IsAuthenticated()]
        return [AllowAny()]
    
    @action(detail=False, methods=['post'])
    def register(self, request):
        """Register a new user."""
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            return Response({
                'message': 'User registered successfully',
                'user': UserSerializer(user).data
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['post'])
    def login(self, request):
        """Login user and return JWT token."""
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.validated_data['user']
            
            # Check if account is active
            if user.account_status != 'active':
                return Response({
                    'error': f'Account is {user.account_status}'
                }, status=status.HTTP_403_FORBIDDEN)
            
            # Update last login
            user.last_login_at = now()
            user.failed_login_attempts = 0
            user.locked_until = None
            user.save()
            
            # Generate token
            token = generate_jwt_token(user)
            
            response_data = {
                'token': token,
                'user': UserSerializer(user).data
            }
            return Response(response_data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=False, methods=['get'])
    def me(self, request):
        """Get current user profile."""
        serializer = UserSerializer(request.user)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def logout(self, request):
        """Logout user."""
        # Token-based logout is handled on client side
        return Response({
            'message': 'Logged out successfully'
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['post'])
    def change_password(self, request):
        """Change user password."""
        user = request.user
        old_password = request.data.get('old_password')
        new_password = request.data.get('new_password')
        new_password2 = request.data.get('new_password2')
        
        if not user.check_password(old_password):
            return Response({
                'error': 'Old password is incorrect'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if new_password != new_password2:
            return Response({
                'error': 'New passwords do not match'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if len(new_password) < 8:
            return Response({
                'error': 'Password must be at least 8 characters'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        user.set_password(new_password)
        user.password_updated_at = now()
        user.save()
        
        return Response({
            'message': 'Password changed successfully'
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get'])
    def health(self, request):
        """Health check endpoint."""
        return Response({
            'status': 'healthy',
            'user': request.user.email if request.user.is_authenticated else 'anonymous'
        })


class UserViewSet(viewsets.ModelViewSet):
    """User management viewset."""
    
    queryset = CustomUser.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter users based on permissions."""
        user = self.request.user
        # Admins can see all users, others can only see themselves
        if user.role == 'admin':
            return CustomUser.objects.all()
        return CustomUser.objects.filter(id=user.id)
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def restrict_account(self, request, pk=None):
        """Restrict a user account (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can restrict accounts'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        user = self.get_object()
        user.account_status = 'restricted'
        user.account_restricted_reason = request.data.get('reason', '')
        user.account_restricted_at = now()
        user.save()
        
        return Response({
            'message': 'Account restricted',
            'user': UserSerializer(user).data
        })
    
    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def unrestrict_account(self, request, pk=None):
        """Unrestrict a user account (admin only)."""
        if request.user.role != 'admin':
            return Response({'error': 'Only admins can unrestrict accounts'}, 
                          status=status.HTTP_403_FORBIDDEN)
        
        user = self.get_object()
        user.account_status = 'active'
        user.account_restricted_reason = ''
        user.account_restricted_at = None
        user.save()
        
        return Response({
            'message': 'Account unrestricted',
            'user': UserSerializer(user).data
        })
