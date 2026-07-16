"""Vendors URLs."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import VendorViewSet, VendorListingViewSet, VendorOrderViewSet

router = DefaultRouter()
router.register(r'', VendorViewSet, basename='vendor')

urlpatterns = [
    path('listings/', VendorListingViewSet.as_view({'get': 'list', 'post': 'create'}), name='vendor-listing-list'),
    path('listings/<int:pk>/', VendorListingViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='vendor-listing-detail'),
    path('listings/<int:pk>/publish/', VendorListingViewSet.as_view({'post': 'publish'}), name='vendor-listing-publish'),
    path('listings/<int:pk>/unpublish/', VendorListingViewSet.as_view({'post': 'unpublish'}), name='vendor-listing-unpublish'),
    path('listings/<int:pk>/remove/', VendorListingViewSet.as_view({'post': 'remove'}), name='vendor-listing-remove'),
    path('orders/', VendorOrderViewSet.as_view({'get': 'list', 'post': 'create'}), name='vendor-order-list'),
    path('orders/<int:pk>/', VendorOrderViewSet.as_view({'get': 'retrieve', 'put': 'update', 'patch': 'partial_update', 'delete': 'destroy'}), name='vendor-order-detail'),
    path('orders/<int:pk>/update_status/', VendorOrderViewSet.as_view({'post': 'update_status'}), name='vendor-order-update-status'),
    path('orders/<int:pk>/cancel_order/', VendorOrderViewSet.as_view({'post': 'cancel_order'}), name='vendor-order-cancel'),
    path('orders/<int:pk>/review_refund/', VendorOrderViewSet.as_view({'post': 'review_refund'}), name='vendor-order-review-refund'),
    path('orders/<int:pk>/submit_feedback/', VendorOrderViewSet.as_view({'post': 'submit_feedback'}), name='vendor-order-submit-feedback'),
    path('', include(router.urls)),
]
