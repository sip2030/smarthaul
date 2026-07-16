from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import NotificationViewSet, SafetyReportViewSet, SupportCaseViewSet

router = DefaultRouter()
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'support-cases', SupportCaseViewSet, basename='support-case')
router.register(r'safety-reports', SafetyReportViewSet, basename='safety-report')

urlpatterns = [
    path('', include(router.urls)),
]
