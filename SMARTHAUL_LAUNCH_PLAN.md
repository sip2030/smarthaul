# SmartHaul Launch Plan

## 1. Product Summary
SmartHaul is a future-ready platform for transportation, haulage, vendor marketplace services, AI support, safety reporting, and business monitoring. It combines mobility, logistics, and commerce into one intelligent platform.

## 2. What the Prototype Includes
- Customer-facing landing experience
- Auth and sign-in pages
- Booking and vendor workspace
- Admin dashboard
- AI assistant interface
- Safety and abuse reporting flow
- Live tracking view
- Messaging and moderation pages
- Analytics and map-style dashboards
- Free-tier deployment files for Render

## 3. Target Users
- Customers needing transport or haulage
- Providers and drivers
- Vendors and local businesses
- Platform admins and operators

## 4. Core Value Proposition
SmartHaul helps users:
- Book transport and haulage quickly
- Access vendors and services in one place
- Get AI-guided support
- Report safety issues securely
- Let admins monitor activity and trust signals

## 5. Launch Strategy
### Phase 1: Prototype Launch
- Deploy a working free-tier version
- Test core flows
- Gather feedback from early users

### Phase 2: Local Market Expansion
- Stronger authentication with password policy, session expiry, logout, and lockout controls
- Improved booking tracking with timeline events, live route snapshots, and richer notifications
- Expanded vendor onboarding with document status, review queue, and admin approval workflow

### Phase 3: Scale-Up
- Add map-style routing with simulated live coordinates and route polylines
- Add chat and call support with call logs and moderated messaging
- Add analytics and moderation automation through admin operations metrics and auto-generated review cases

## 6. Free-Tier Hosting Plan
Use Render with the provided configuration for the initial launch.

## 7. Revenue Model (Future)
- Booking commissions
- Vendor subscription plans
- Provider listing fees
- Premium analytics and support features

## 8. Next Milestones
- Launch prototype publicly
- Collect feedback
- Improve onboarding and trust systems
- Replace simulated map flows with provider-backed production routing integrations

## 9. Launch Decisions
These are the current recommended defaults for the first public launch.

- Launch region: Lagos, Nigeria
- Initial services: ride requests, haulage, and vendor marketplace flows
- Platform scope: responsive web app first
- Payment provider: Flutterwave
- Safety baseline: account verification, password policy, session controls, moderation, and dispute handling

## 10. Decision Rationale
- Lagos-first matches the current data, UI assumptions, and routing setup.
- The current MVP already covers the initial services needed for a useful pilot.
- Responsive web first keeps launch operations simpler while staying mobile-friendly.
- Flutterwave is already integrated in the codebase and fits the current deployment flow.
- The existing moderation, dispute, and auth controls provide a practical launch safety baseline.
