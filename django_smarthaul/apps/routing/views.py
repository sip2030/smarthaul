from __future__ import annotations

import hashlib
import math
import os
from datetime import timedelta

import requests
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.bookings.models import Booking


KNOWN_LOCATIONS = [
    'Yaba',
    'Lekki',
    'Ikeja',
    'Victoria Island',
    'Surulere',
    'Ajah',
    'Ikorodu',
    'Ojota',
    'Mushin',
    'Maryland',
]


def _hash_to_float(value: str, min_value: float, max_value: float) -> float:
    digest = hashlib.sha256(value.encode('utf-8')).hexdigest()
    as_int = int(digest[:12], 16)
    ratio = as_int / float(0xFFFFFFFFFFFF)
    return min_value + (max_value - min_value) * ratio


def _coord_for_location(location: str) -> dict:
    normalized = (location or '').strip() or 'Unknown'
    return {
        'lat': round(_hash_to_float(f'{normalized}:lat', 6.35, 6.75), 6),
        'lng': round(_hash_to_float(f'{normalized}:lng', 3.20, 3.80), 6),
    }


def _distance_between(start: dict, end: dict) -> float:
    return round(
        math.sqrt((start['lat'] - end['lat']) ** 2 + (start['lng'] - end['lng']) ** 2) * 111,
        2,
    )


def _build_polyline(start: dict, end: dict):
    mid_lat = round((start['lat'] + end['lat']) / 2 + 0.02, 6)
    mid_lng = round((start['lng'] + end['lng']) / 2 - 0.02, 6)
    return [start, {'lat': mid_lat, 'lng': mid_lng}, end]


def _estimate_eta_minutes(distance_km: float) -> int:
    return max(6, int(round(distance_km * 2.2)))


def _route_provider_name():
    return (os.environ.get('ROUTING_PROVIDER') or 'simulated').strip().lower()


def _openrouteservice_headers():
    api_key = os.environ.get('OPENROUTESERVICE_API_KEY', '').strip()
    if not api_key:
        return None
    return {
        'Authorization': api_key,
        'Content-Type': 'application/json',
    }


def _geocode_location(location: str):
    headers = _openrouteservice_headers()
    if not headers:
        return None

    response = requests.get(
        'https://api.openrouteservice.org/geocode/search',
        headers=headers,
        params={'text': location, 'size': 1},
        timeout=8,
    )
    response.raise_for_status()
    payload = response.json()
    features = payload.get('features') or []
    if not features:
        return None
    coordinates = features[0].get('geometry', {}).get('coordinates') or []
    if len(coordinates) != 2:
        return None
    return {'lng': float(coordinates[0]), 'lat': float(coordinates[1])}


def _openrouteservice_route(pickup: str, destination: str):
    headers = _openrouteservice_headers()
    if not headers:
        return None

    pickup_point = _geocode_location(pickup)
    destination_point = _geocode_location(destination)
    if not pickup_point or not destination_point:
        return None

    response = requests.post(
        'https://api.openrouteservice.org/v2/directions/driving-car/geojson',
        headers=headers,
        json={'coordinates': [[pickup_point['lng'], pickup_point['lat']], [destination_point['lng'], destination_point['lat']]]},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    feature = (payload.get('features') or [{}])[0]
    summary = feature.get('properties', {}).get('summary', {})
    geometry_coordinates = feature.get('geometry', {}).get('coordinates') or []
    polyline = [{'lat': lat, 'lng': lng} for lng, lat in geometry_coordinates[:3]]
    if not polyline:
        polyline = [pickup_point, destination_point]

    return {
        'pickup': pickup,
        'destination': destination,
        'distance_km': round((summary.get('distance') or 0) / 1000, 2),
        'eta_minutes': max(1, int(round((summary.get('duration') or 0) / 60))),
        'route_source': 'openrouteservice',
        'route_status': 'estimated',
        'provider': 'openrouteservice',
        'current_position': pickup_point,
        'polyline': polyline,
    }


def _timeline_from_booking(booking: Booking | None):
    if not booking:
        return []

    timeline = [
        {
            'status': booking.status,
            'note': f'Booking is currently {booking.status}.',
            'created_at': booking.updated_at.isoformat() if booking.updated_at else timezone.now().isoformat(),
        }
    ]
    if booking.completed_at:
        timeline.insert(0, {
            'status': 'completed',
            'note': 'Service completed.',
            'created_at': booking.completed_at.isoformat(),
        })
    if booking.current_latitude is not None and booking.current_longitude is not None:
        timeline.append({
            'status': 'tracking',
            'note': f'Latest provider position: {booking.current_latitude}, {booking.current_longitude}.',
            'created_at': booking.provider_last_ping_at.isoformat() if booking.provider_last_ping_at else timezone.now().isoformat(),
        })
    return timeline


def route_estimate(request):
    pickup = (request.GET.get('pickup') or '').strip()
    destination = (request.GET.get('destination') or '').strip()
    if not pickup or not destination:
        return JsonResponse({'detail': 'pickup and destination are required'}, status=400)

    if _route_provider_name() == 'openrouteservice':
        try:
            route = _openrouteservice_route(pickup, destination)
            if route is not None:
                return JsonResponse(route)
        except requests.RequestException:
            pass

    pickup_point = _coord_for_location(pickup)
    destination_point = _coord_for_location(destination)
    distance_km = _distance_between(pickup_point, destination_point)
    eta_minutes = _estimate_eta_minutes(distance_km)

    route = {
        'pickup': pickup,
        'destination': destination,
        'distance_km': distance_km,
        'eta_minutes': eta_minutes,
        'route_source': 'simulated',
        'route_status': 'estimated',
        'provider': 'simulated',
        'current_position': pickup_point,
        'polyline': _build_polyline(pickup_point, destination_point),
    }
    return JsonResponse(route)


def location_search(request):
    query = (request.GET.get('query') or '').strip().lower()
    if not query:
        return JsonResponse({'results': []})

    results = []
    for location in KNOWN_LOCATIONS:
        if query in location.lower():
            results.append({
                'name': location,
                'display_name': f'{location}, Lagos',
                'lat': _coord_for_location(location)['lat'],
                'lng': _coord_for_location(location)['lng'],
            })

    if not results:
        results = [
            {
                'name': location,
                'display_name': f'{location}, Lagos',
                'lat': _coord_for_location(location)['lat'],
                'lng': _coord_for_location(location)['lng'],
            }
            for location in KNOWN_LOCATIONS[:5]
        ]

    return JsonResponse({'results': results})


def live_tracking(request, booking_id):
    booking = get_object_or_404(Booking, id=booking_id)

    pickup_point = _coord_for_location(booking.pickup)
    destination_point = _coord_for_location(booking.destination)
    current_point = (
        {'lat': booking.current_latitude, 'lng': booking.current_longitude}
        if booking.current_latitude is not None and booking.current_longitude is not None
        else pickup_point
    )
    distance_km = _distance_between(current_point, destination_point)
    eta_minutes = booking.eta_minutes or _estimate_eta_minutes(distance_km)
    status = booking.status if booking.status in {'accepted', 'in_progress', 'completed'} else 'pending'

    route = {
        'pickup': booking.pickup,
        'destination': booking.destination,
        'distance_km': distance_km,
        'eta_minutes': eta_minutes,
        'route_source': 'booking',
        'route_status': status,
        'provider': booking.provider.get_full_name() if booking.provider else 'simulated',
        'current_position': current_point,
        'polyline': _build_polyline(current_point, destination_point),
    }

    response = {
        'booking_id': booking.id,
        'status': booking.status,
        'eta_minutes': eta_minutes,
        'current_position': current_point,
        'route': route,
        'timeline': _timeline_from_booking(booking),
        'last_updated_at': booking.updated_at.isoformat() if booking.updated_at else timezone.now().isoformat(),
    }
    return JsonResponse(response)


def route_overview(request):
    booking_id = request.GET.get('booking_id')
    if booking_id:
        booking = get_object_or_404(Booking, id=booking_id)
        return live_tracking(request, booking.id)

    return route_estimate(request)
