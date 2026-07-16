# SmartHaul Implementation Backlog

This backlog is based on the verified Django backend in `django_smarthaul/` and the PRD requirements in `smarthaul-prd.md`.

## Priority 0: Close the biggest product gaps

### 1. Add support, messaging, notifications, and AI assistant APIs

Why this is first: the PRD treats human escalation, user support, and in-app communication as core requirements, but the backend URL map only exposes auth, bookings, vendors, providers, and payments.

Implementation targets:

- Add API apps and routes for support tickets, messaging, notifications, and AI assistant responses.
- Add escalation endpoints that convert unresolved AI cases into human support cases.
- Add notification delivery records for booking events, payment events, and safety events.

Acceptance checks:

- Users can open a support case from a booking or dispute.
- AI support can hand off to human support.
- Booking and payment events generate user-visible notifications.

### 2. Add explicit route, ETA, and map-search services

Why this is first: current tracking is snapshot-based, but the PRD expects route visualization, estimated travel time, and location search.

Implementation targets:

- Add a route estimation service that can compute ETA from pickup and destination.
- Add map search or geocoding endpoints for addresses and service areas.
- Extend tracking responses so the frontend can show route data and live ETA updates.

Acceptance checks:

- A booking can return a route summary with ETA.
- The map screen can search locations and render the active route.
- Live tracking updates include ETA changes, not only raw coordinates.

### 3. Automate escrow release and dispute-window payout handling

Why this is first: payout release is still manual in the current payment view, while the PRD requires funds to remain in escrow until completion and a dispute window.

Implementation targets:

- Add a payout scheduler or background job that releases funds automatically after the dispute window.
- Keep completed funds in escrow until the dispute window expires.
- Block payout release while a dispute is active.

Acceptance checks:

- Payment completion sets escrow to held.
- Completed bookings do not release provider payout immediately.
- Payout release happens automatically after the configured window unless a dispute exists.

## Priority 1: Complete booking lifecycle behavior

### 4. Add booking timeout and auto-cancel behavior

Why this matters: the PRD defines pending-booking behavior, but the backend does not yet enforce a timeout-based transition for requests that remain unaccepted.

Implementation targets:

- Add a configurable timeout for pending bookings.
- Auto-cancel bookings that exceed the acceptance window.
- Notify the customer when a booking times out and offer retry or search expansion options.

Acceptance checks:

- A pending booking older than the timeout transitions to cancelled.
- The customer receives a retry or widen-search notification.

### 5. Add a formal reschedule flow

Why this matters: providers can accept or decline today, but the PRD explicitly includes rescheduling.

Implementation targets:

- Add a reschedule action on bookings.
- Capture proposed new time or date and the responding party’s decision.
- Notify both sides when a booking is rescheduled.

Acceptance checks:

- A provider can propose a new slot.
- The customer can accept or reject the change.

### 6. Tighten cancellation policy enforcement

Why this matters: cancellation exists, but the PRD now requires a penalty-free window, fees outside that window, and clear fee ownership when the provider cancels.

Implementation targets:

- Store the cancellation window on bookings or payment policy settings.
- Compute whether a cancellation is penalty-free before applying fees.
- Record who bears the fee when a provider cancels.

Acceptance checks:

- Cancellations inside the window do not incur a fee.
- Provider cancellations outside the window apply the configured fee.
- The cancellation record shows who paid the fee.

## Priority 2: Operational and trust features

### 7. Add moderation and safety workflows beyond call logging

Why this matters: the code already logs calls for dispute or safety cases, but the PRD also expects moderation, abuse handling, and admin review flows.

Implementation targets:

- Add abuse-report queues and moderation case resolution endpoints.
- Link reports to bookings, vendors, providers, and user accounts.
- Add admin review actions for disputed and safety-related cases.

Acceptance checks:

- Admins can review and resolve safety reports.
- Reported entities stay linked to the original booking or profile.

### 8. Add richer admin and analytics endpoints

Why this matters: the PRD includes analytics and monitoring, but the backend surface does not yet expose dedicated analytics APIs.

Implementation targets:

- Add dashboard metrics endpoints for bookings, payments, disputes, vendor onboarding, and provider activity.
- Add activity feed or audit log endpoints.
- Add summary endpoints for operational reporting.

Acceptance checks:

- Admins can request booking, payment, and dispute summaries.
- The audit feed can be queried from the backend.

### 9. Add explicit notification generation for core lifecycle events

Why this matters: notifications are shown in the UI roadmap and PRD, but there is no backend notification module in the verified Django route map.

Implementation targets:

- Create persistent notification records.
- Trigger notifications on booking creation, acceptance, cancellation, completion, payment completion, and support escalation.
- Add read/unread state tracking.

Acceptance checks:

- A user can list notifications.
- Booking and payment events generate notifications automatically.

## Priority 3: Verification and hardening

### 10. Expand automated tests to cover missing PRD flows

Recommended test additions:

- Pending booking timeout auto-cancel.
- Cancellation fee calculation and fee ownership.
- Escrow release only after dispute window expiry.
- Support escalation from AI to human support.
- Notification creation for booking and payment events.
- Route ETA generation and map search behavior.

### 11. Update API documentation and deployment notes

Recommended docs updates:

- Document any new support, notification, analytics, and routing endpoints.
- Document escrow timing and payout rules.
- Document timeout and cancellation policy settings.

## Suggested order of execution

1. Support, messaging, notifications, and AI escalation.
2. Route estimation and map-search services.
3. Escrow automation and payout scheduling.
4. Booking timeout, reschedule, and cancellation policy enforcement.
5. Moderation, analytics, and audit reporting.
6. Test coverage and documentation updates.
