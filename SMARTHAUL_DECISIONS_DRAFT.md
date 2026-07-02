# SmartHaul Product Decisions Draft

This document turns the remaining open product questions into a concrete starting point.
It is provisional and should be confirmed with the business owner before launch.

## Recommended Answers

### First Launch Region
- Recommended: Lagos, Nigeria
- Why: the current UI, sample data, and routing assumptions already align well with a Lagos-first launch.
- Launch scope: start with a single metro region before expanding.

### Priority Services
- Recommended first services:
  - Personal transport / ride requests
  - Haulage and cargo movement
  - Vendor and local service marketplace listings
- Why: these are already represented in the current MVP and give the quickest path to product-market feedback.

### Platform Scope
- Recommended: web app first, with mobile-friendly responsive views as the primary launch surface.
- Follow-up: mobile app only after usage patterns and operations stabilize.

### Payment Provider
- Recommended: Flutterwave as the first production payment provider.
- Why: the codebase already includes payment initialization, webhook verification, and callback handling.

### Compliance and Safety
- Recommended initial focus:
  - Basic account verification and role checks
  - Strong password policy and session controls
  - Clear reporting, moderation, and dispute escalation flows
  - Privacy disclosures for support, calls, and moderation logging
- Deferred until later:
  - Multi-country compliance tooling
  - Full legal workflow automation
  - Region-specific payment or tax complexity beyond the first launch market

## Suggested Launch Sequence
1. Confirm Lagos as the launch region.
2. Launch ride, haulage, and vendor marketplace flows together.
3. Use Flutterwave for production payments.
4. Keep the responsive web app as the first release surface.
5. Validate support, moderation, and monitoring workflows with a pilot group.
6. Expand to mobile apps only after the first ops cycle is stable.

## Notes
- This draft intentionally follows the current implementation rather than inventing new product scope.
- The unresolved questions remain in [SMARTHAUL_STATUS_CHECKLIST.md](SMARTHAUL_STATUS_CHECKLIST.md) as launch decisions to confirm.