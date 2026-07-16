from django.urls import path

from .views import live_tracking, location_search, route_estimate, route_overview

urlpatterns = [
    path('route/estimate', route_estimate, name='route-estimate'),
    path('route/search', location_search, name='location-search'),
    path('tracking/<int:booking_id>/live', live_tracking, name='live-tracking'),
    path('route/overview', route_overview, name='route-overview'),
]
