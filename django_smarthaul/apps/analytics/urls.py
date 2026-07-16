from django.urls import path

from .views import analytics_activity, analytics_audit, analytics_alerts, analytics_dashboard, analytics_summary

urlpatterns = [
    path('analytics/summary/', analytics_summary, name='analytics-summary'),
    path('analytics/activity/', analytics_activity, name='analytics-activity'),
    path('analytics/audit/', analytics_audit, name='analytics-audit'),
    path('analytics/alerts/', analytics_alerts, name='analytics-alerts'),
    path('analytics/dashboard/', analytics_dashboard, name='analytics-dashboard'),
]
