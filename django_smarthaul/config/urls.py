"""
URL configuration for SmartHaul project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers

router = routers.DefaultRouter()

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('apps.routing.urls')),
    path('api/', include(router.urls)),
    path('api/auth/', include('apps.auth.urls')),
    path('api/bookings/', include('apps.bookings.urls')),
    path('api/vendors/', include('apps.vendors.urls')),
    path('api/providers/', include('apps.providers.urls')),
    path('api/payments/', include('apps.payments.urls')),
    path('api/', include('apps.communications.urls')),
    path('api/', include('apps.analytics.urls')),
    path('api-auth/', include('rest_framework.urls')),
]
