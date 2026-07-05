"""Auth serializers."""
from rest_framework import serializers
from django.contrib.auth import authenticate
from .models import CustomUser
from .authentication import generate_jwt_token


class UserSerializer(serializers.ModelSerializer):
    """User serializer."""
    
    class Meta:
        model = CustomUser
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'phone_number', 
                  'avatar', 'bio', 'account_status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class RegisterSerializer(serializers.ModelSerializer):
    """User registration serializer."""
    
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)
    
    class Meta:
        model = CustomUser
        fields = ['email', 'first_name', 'last_name', 'password', 'password2', 'role', 'phone_number']
    
    def validate(self, data):
        """Validate that passwords match."""
        if data['password'] != data.pop('password2'):
            raise serializers.ValidationError({'password': 'Passwords do not match.'})
        return data
    
    def create(self, validated_data):
        """Create user with hashed password."""
        user = CustomUser.objects.create_user(
            email=validated_data['email'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            password=validated_data['password'],
            role=validated_data.get('role', 'customer'),
            phone_number=validated_data.get('phone_number', ''),
            username=validated_data['email']  # Use email as username
        )
        return user


class LoginSerializer(serializers.Serializer):
    """User login serializer."""
    
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    def validate(self, data):
        """Authenticate user."""
        user = authenticate(username=data['email'], password=data['password'])
        if not user:
            raise serializers.ValidationError('Invalid email or password.')
        data['user'] = user
        return data


class LoginResponseSerializer(serializers.Serializer):
    """Login response with token."""
    
    token = serializers.CharField()
    user = UserSerializer()
