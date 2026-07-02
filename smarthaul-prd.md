# SmartHaul Product Requirements Document (PRD)

## 1. Document Overview

Project Name: SmartHaul

Product Type: Multi-service mobility, logistics, and marketplace platform

Vision Statement:
SmartHaul is a future-ready platform that connects people, businesses, and service providers through reliable transportation, haulage, vendor services, and AI-powered support. The platform will simplify booking, improve safety, provide transparent tracking, and support business growth through intelligent monitoring and analytics.

Document Purpose:
This PRD defines the product scope, user needs, core features, technical assumptions, release phases, and success criteria for SmartHaul.

## 2. Problem Statement

Many users face challenges when trying to:
- Book transportation quickly and reliably
- Move goods safely and on time
- Find trusted local service providers or vendors
- Receive fast support when issues occur
- Monitor business operations in real time

Existing solutions often focus on only one category, such as ride-hailing or delivery, but do not combine mobility, logistics, and marketplace services into a single intelligent platform.

SmartHaul solves this by unifying:
- People transport
- Haulage and cargo movement
- Vendor and service marketplace
- AI-powered assistance
- Safety reporting and business monitoring

## 3. Product Goals

### Business Goals
- Create a scalable multi-service platform for transportation, logistics, and commerce
- Enable users and businesses to connect directly through a trusted digital marketplace
- Build a long-term AI-enhanced platform for future-ready mobility services
- Create revenue from service fees, subscriptions, commissions, and premium features

### User Goals
- Book movement of people or goods in a simple and transparent way
- Track services in real time
- Discover and hire trusted vendors and providers
- Get support from an AI assistant when needed
- Report safety issues quickly and confidently

### Product Goals for MVP
- Allow users to request transport or haulage services
- Allow providers and vendors to register and manage services
- Allow admins to monitor operations and disputes
- Provide basic AI support for user guidance and common questions

## 4. Target Users

### 4.1 End Customers
Customers who need:
- Personal transport to a destination
- Goods transport or haulage services
- Access to local vendors and service providers

### 4.2 Service Providers
Providers such as:
- Drivers
- Haulage operators
- Logistics partners
- Independent vendors
- Small businesses offering services

### 4.3 Business Owners / Administrators
People who manage:
- Platform operations
- User verification
- Business listings
- Payments and disputes
- Analytics and compliance

## 5. Product Scope

### In Scope for MVP
- User registration and authentication
- Customer booking flow for transport and haulage
- Provider and vendor registration
- Service listing and marketplace browsing
- Booking request and approval workflow
- In-app chat and support
- AI assistant for basic support and navigation
- Admin dashboard for monitoring and reporting
- Safety reporting and abuse handling
- Basic map-based location selection and routing

### Out of Scope for MVP
- Full autonomous vehicle integration
- Advanced predictive demand forecasting
- Full-scale video surveillance monitoring
- Fully autonomous customer support that replaces the required human escalation path
- Complex multi-country regulatory compliance tools

## 6. Core Use Cases

### 6.1 Customer Use Cases
- Sign up and create a profile
- Search for transport or haulage service
- Select pickup and destination locations
- Choose service type and estimate price
- Confirm booking and payment
- Track provider progress in real time
- Chat with provider or support
- Rate and review the service
- Report unsafe behavior or disputes

### 6.2 Provider Use Cases
- Register business or service profile
- Set availability and service area
- Respond to booking requests
- Accept or reject service requests
- Update trip or delivery status
- Communicate with customers
- Receive payment and view earnings
- Report customer issues or disputes

### 6.3 Vendor Use Cases
- Register a business or service listing
- Add products or services to the marketplace
- Set price, availability, and delivery options
- Receive orders or inquiries
- Manage order status and fulfillment
- View ratings and feedback

### 6.4 Admin Use Cases
- Review and approve providers and vendors
- Monitor transactions and bookings
- Investigate reported abuse or disputes
- Manage support requests
- View analytics for growth and operations

## 7. Functional Requirements

### 7.1 Authentication and User Accounts
- Users must be able to sign up using email, phone, or social login
- Users must verify identity where required
- Users must have separate roles: customer, provider, vendor, admin
- Users must be able to edit their profile and account settings

### 7.2 Booking and Request Management
- Customers must be able to request transport or haulage services
- Customers must be able to select pickup and destination addresses
- Customers must be able to choose service category and urgency
- Providers must be able to accept, decline, or reschedule requests
- Cancellation rules must be admin-configurable and must expose: (a) the penalty-free window duration in minutes after acceptance, (b) the cancellation fee percentage or fixed amount applied outside that window, and (c) the fee assignment logic when the provider cancels. Default values must be set before the platform goes live.
- Booking status must move through states such as pending, accepted, active, completed, cancelled, disputed
- If a customer raises a dispute within the payout window after a provider marks a booking as completed, the booking status must transition to disputed, funds must remain in escrow, and the case must be escalated to admin review before any payout is released.
- If a customer raises a dispute while the booking is still in active or accepted status, the booking must be immediately flagged and escalated to admin review. The booking must not be allowed to transition to completed until the dispute is resolved. Funds must remain in escrow for the duration of the review.
- If a booking request remains in pending status for longer than 10 minutes without provider acceptance, the system must automatically transition it to cancelled and notify the customer with an option to retry or widen their search radius
- When a customer retries after a timeout cancellation, the system must create a new booking record with a new booking ID. The original cancelled record must be retained for audit purposes. Widening the search radius must apply only to the new booking and must not modify the cancelled record.

### 7.3 Marketplace and Vendor Management
- Vendors must be able to create storefronts or service profiles
- Vendors must be able to manage product or service listings
- Customers must be able to browse vendors by category, location, and rating
- Customers must be able to place orders or book services
- Vendors must be able to manage fulfillment and status updates

### 7.4 Maps and Location Services
- The platform must support accurate pickup and drop-off location selection
- The platform must display route information and estimated travel time
- The platform must allow real-time tracking of active services
- The system must support map-based search and route visualization

### 7.5 Payments and Transactions
- The platform must support secure payments
- The system must support commission or service fee handling
- The system must store transaction histories for users and admins
- The system must support refunds or dispute resolution workflows
- Funds collected from customers must be held in escrow until the booking status moves to completed
- If the escrow hold fails at booking confirmation, the booking must not be set to accepted. The customer must be notified of the payment failure with an option to retry with a different payment method. The booking must remain in a payment-pending state and must not be dispatched to providers until payment is successfully captured.
- Provider payout must be triggered automatically after a dispute window that defaults to 24 hours and is configurable by admin. The window begins when the booking transitions to completed status, unless a dispute is raised.
- If a dispute is raised after the provider payout has already been released, the booking must be flagged for admin review. The dispute must be logged and linked to the completed booking record. Any remediation, including refunds or clawbacks, must be handled manually by admin. The customer must be notified that the dispute window has closed and that resolution is subject to admin discretion.

### 7.6 Communication and Support
- Users must be able to chat in-app
- Customers and providers must be able to receive booking notifications
- The AI assistant must help with navigation, FAQs, and service guidance
- The platform must allow escalation from AI support to human support

### 7.7 Safety and Reporting
- Users must be able to report abusive behavior or misconduct
- The platform must support dispute reporting and evidence capture
- The system must store incident records and review state
- The platform must support user blocking or account restriction

### 7.8 Admin and Monitoring Features
- Admin must be able to monitor bookings, users, vendors, and disputes
- Admin must be able to view business metrics and performance dashboards
- Admin must be able to issue warnings, suspend accounts, or remove listings
- The system must generate activity logs for audit and business review

## 8. Non-Functional Requirements

### 8.1 Performance
- The app must load the home, booking, and tracking screens within 2 seconds on a 4G mobile connection
- Booking confirmation must be returned to the user within 3 seconds of submission under normal load conditions
- Tracking location updates must be delivered to the customer within 5 seconds of a provider's position change during an active booking.
- If no provider location update is received for more than 60 seconds during an active booking, the tracking screen must display a stale-location indicator and notify the customer that live tracking is temporarily unavailable. The system must attempt to resume tracking automatically and notify the customer when updates resume. If the outage exceeds 5 minutes, the customer must be offered the option to contact the provider or support.

### 8.2 Reliability
- The system must handle peak demand without major failures
- Failures must be gracefully handled with retry or fallback logic

### 8.3 Security
- Data must be encrypted in transit and at rest
- User authentication must include secure password or token-based access
- Sensitive actions must require authorization checks
- Payments must comply with security best practices

### 8.4 Privacy
- Camera and audio features must be consent-based
- Users must be informed about recording, monitoring, and data usage
- The system must support access control for sensitive data

### 8.5 Scalability
- The platform must support growth from local launch to broader regions
- The architecture must support adding new services and features over time

## 9. AI Assistant Requirements

### 9.1 Purpose of the AI Agent
The AI assistant will help users navigate the platform, answer common questions, guide them through bookings, and provide support referrals.

### 9.2 AI Assistant Capabilities
- Answer frequently asked questions
- Help users find transport or vendor options
- Guide users through booking steps
- Provide service-related recommendations
- Summarize support policies and dispute steps
- Escalate difficult cases to human support

### 9.3 AI Assistant Constraints
- The AI must not make final legal or safety decisions
- It must clearly communicate when human assistance is necessary
- It must not expose private user data without authorization

### 9.4 MVP AI Assistant Scope
- For the MVP, the AI assistant will provide lightweight conversational support for booking guidance, FAQs, vendor discovery, and basic troubleshooting.
- It will initially use rule-based and templated responses, with later expansion to more advanced AI capabilities.
- It must escalate unresolved or sensitive issues to human support quickly and clearly.

### 9.5 AI Assistant Success Criteria
- Users must receive an AI assistant response to a question within 3 seconds of submission under normal load conditions.
- The assistant can help a user move from inquiry to booking request without manual intervention.
- The assistant reduces routine support load while preserving a safe handoff to human agents when needed.

## 10. Safety, Compliance, and Trust Requirements

### 10.1 Identity Verification
- Providers must submit identity or business documents before their first booking is accepted. Vendors must submit business documents before their storefront is made publicly visible. Document requirements may be adjusted per service category by admin configuration.
- Accounts must be reviewed before full platform access is granted
- Before granting full platform access, admin must confirm: (a) identity or business document has been submitted and is legible, (b) the applicant's role matches their submitted credentials (e.g., commercial license for haulage operators), and (c) no existing account flag or ban exists for the same identity. Accounts that fail any check must be set to a rejected state with a reason communicated to the applicant.
- A rejected applicant must be permitted to resubmit a corrected application. Resubmissions must be treated as a new review cycle. An applicant whose identity is matched to a banned account must not be permitted to reapply and must be permanently blocked from registration.

### 10.2 Abuse Reporting
- Users must be able to report harassment, misconduct, fraud, or unsafe conduct
- Reports must be linked to the relevant booking, service, or vendor profile
- If the referenced booking, service, or vendor profile is no longer available at the time of report submission, the system must still accept and store the report using the entity identifier as a reference, and flag it for admin review with a note that the linked entity is unavailable.
- Report states must include pending, under review, resolved, and closed

### 10.3 Communication Safety
- In-app messages must support moderation tools
- Reported messages can be reviewed by admins
- The platform should support blocking or restricting malicious users

### 10.4 Camera, Audio, and Call Features
- Audio or video calling must be optional and consent-based
- Users must be informed before any audio or video communication starts
- Calls must be logged only when either party has an active dispute open against them, or when a safety report referencing the same booking ID has been filed at any point from booking creation through 24 hours after the booking reaches a completed or disputed state. All other calls must not be recorded

## 11. Maps and Routing Requirements

### 11.1 Mapping Requirements
- The platform must support accurate location search and address input
- The system must display service areas and provider proximity
- The platform must support route visualization and estimated travel time

### 11.2 Routing Accuracy Expectations
- Routing should be based on current maps and routing data
- The app should aim for high accuracy in address matching and route guidance
- The platform should support real-time route changes where relevant

### 11.3 API Strategy
To keep the platform affordable and sustainable:
- Prefer open-source or free-tier mapping and geocoding services for the MVP
- Avoid unnecessary paid services in early releases
- Keep APIs modular so providers can be swapped later

## 12. Dashboard and Monitoring Requirements

### 12.1 Admin Dashboard
The admin dashboard must provide:
- Overview of active bookings and revenue
- Provider and vendor activity statistics
- User growth and retention metrics
- Dispute and report trends
- Alerts for suspicious activity

### 12.2 Business Monitoring
The platform should allow business owners to monitor:
- Daily bookings
- Service performance
- Completion rates
- Revenue trends
- Customer satisfaction ratings

### 12.3 Surveillance and Monitoring Philosophy
Monitoring should support operational safety and business visibility, not invasive surveillance by default. The platform should prioritize consent, transparency, and secure handling of data.

## 13. User Stories

### Customer
- As a customer, I want to book a ride or haulage service quickly so I can reach my destination without stress.
- As a customer, I want to track my provider in real time so I know where my service is.
- As a customer, I want to contact support quickly if something goes wrong.

### Provider
- As a provider, I want to receive booking requests clearly so I can manage my schedule.
- As a provider, I want to communicate with customers easily so I can avoid confusion.
- As a provider, I want to view earnings and performance so I can improve my business.

### Vendor
- As a vendor, I want to list my products or services so more customers can find me.
- As a vendor, I want to manage my orders from one dashboard so I can operate efficiently.

### Admin
- As an admin, I want to monitor reports and disputes so I can maintain platform trust.
- As an admin, I want to view analytics so I can improve operations.

## 14. Release Plan

### Phase 1: Foundation
- Authentication and user roles
- Profile management
- Basic booking and request flow
- Basic maps and location selection

### Phase 2: Marketplace and Operations
- Vendor listings
- Product/service management
- Booking approvals and status updates
- Notifications and chat support

### Phase 3: AI and Safety
- AI assistant for support and guidance
- Abuse reporting and disputes
- Verification workflows
- Emergency support and reporting flows

### Phase 4: Intelligence and Growth
- Advanced analytics dashboard
- Business monitoring tools
- Optional audio/video support
- Performance optimization and scaling

## 15. MVP Success Metrics

The MVP will be considered successful if:
- Users can sign up and book a service successfully
- Providers can accept and complete requests
- Vendors can list and fulfill services
- AI assistant can answer common questions effectively
- Admin can review requests and reports
- The app is stable enough for pilot testing

### Suggested KPIs
- Booking completion rate
- Average response time for providers
- Customer satisfaction score
- Vendor activation rate
- Report resolution time
- Daily active users

## 16. Risks and Mitigations

### Risk: High complexity of building everything at once
Mitigation: Launch the MVP first and expand features in phases.

### Risk: Cost of mapping and communication APIs
Mitigation: Use open-source or free-tier services for initial launch.

### Risk: Privacy concerns around monitoring and calls
Mitigation: Make camera and audio features opt-in and clearly disclosed.

### Risk: Abuse and fraud
Mitigation: Use verification, reporting, blocking, and moderation workflows.

## 17. Open Questions

- Which city or region will be the first launch target?
- Which transport and haulage services will be prioritized first?
- Will the initial launch focus on mobile app, web app, or both?
- Which payment providers will be used?
- Is there a need for local regulatory compliance tools in the first release?

## 18. Assumptions

- The platform will start with a focused MVP before scaling to larger markets
- The platform will support both individual users and businesses
- Free or low-cost APIs will be prioritized in early development
- The AI assistant will initially focus on support and navigation rather than full autonomous operations

## 19. Summary

SmartHaul is a future-ready platform for transportation, logistics, vendors, and AI-powered support. Its MVP should focus on reliable booking, provider management, vendor marketplace functionality, AI help, and safety reporting. The platform should be built in phases so it can grow from a strong local launch to a broader intelligent marketplace over time.

## 20. Current Implementation Status

The prototype now includes the main MVP surfaces described in this PRD:
- Public landing, auth, workspace, admin, provider, vendor, support, moderation, messaging, tracking, analytics, map, calls, and chatbot pages
- SQLite-backed bookings, vendors, providers, quotes, notifications, messages, payments, refunds, disputes, and reports
- Session-based authentication with role checks for protected areas
- Booking lifecycle updates, feedback collection, and tracking lookups
- Rule-based AI support and escalation guidance
- Free-tier Render deployment configuration

Verified state:
- The current codebase passes 18 automated tests locally

Remaining next steps:
- Connect the prototype to real external providers for maps, routing, and payments
- Expand moderation and trust workflows beyond the MVP ruleset
- Replace the lightweight session store with a production-ready auth/session layer when scaling beyond the prototype

## 21. Launch Checklist

Priority 1:
- Confirm the Render deployment path end to end
- Keep the current test suite green before each release
- Validate the core customer booking flow in the deployed environment

Priority 2:
- Add real map, routing, and payment providers
- Move session handling to a production-ready store
- Expand role-based moderation and trust workflows

Priority 3:
- Add stronger analytics and operational alerts
- Improve onboarding for providers and vendors
- Prepare a production support and incident process
