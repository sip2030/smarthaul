"""Auth URLs."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AuthViewSet, UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path('register/', AuthViewSet.as_view({'post': 'register'}), name='register'),
    path('login/', AuthViewSet.as_view({'post': 'login'}), name='login'),
    path('logout/', AuthViewSet.as_view({'post': 'logout'}), name='logout'),
    path('me/', AuthViewSet.as_view({'get': 'me'}), name='current-user'),
    path('change-password/', AuthViewSet.as_view({'post': 'change_password'}), name='change-password'),
    path('health/', AuthViewSet.as_view({'get': 'health'}), name='health'),
    path('', include(router.urls)),
]
