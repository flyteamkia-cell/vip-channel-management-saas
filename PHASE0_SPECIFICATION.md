# Phase 0 — Final Clarifications & Business Rules
**Project**: VIP Channel Management SaaS  
This document supersedes any ambiguity in the previous Phase 0 report. Use these decisions as the current source of truth for Phase 1 architecture and implementation.

---

## 1. Telegram Bot Architecture
The Telegram Bot Token currently found in the n8n workflow belongs to a TEST BOT. It is NOT the intended production SaaS bot.
- Do not treat the current Telegram token as the production credential.
- It can be used temporarily for development/testing if necessary.
- Production will use a different Telegram bot.
- The architecture must support changing the bot token without changing source code.

### SaaS Requirement
This is a multi-tenant SaaS. Every customer/tenant using the platform must be able to connect their own Telegram bot.

Expected architecture:
SaaS Platform
│
├── Tenant A -> Telegram Bot A
├── Tenant B -> Telegram Bot B
├── Tenant C -> Telegram Bot C
└── Tenant D -> Telegram Bot D


Each tenant should be able to configure:
- Telegram Bot Token
- Telegram Channel IDs
- Telegram Group IDs where applicable
- Required bot permissions
- VIP destinations

---

## 2. Telegram Credential Security
Telegram Bot Tokens are sensitive credentials. They must:
- Never be hard-coded in source code
- Never be committed to Git
- Never appear in logs
- Never be returned through normal API responses
- Never be exposed to frontend JavaScript

Store them using secure encrypted credential storage:
ProviderCredential
id
tenant_id
provider_type
credential_name
encrypted_secret
created_at
updated_at

The encryption key itself must remain outside the database (e.g., ENV / Secret Manager).

---

## 3. Telegram Connection Flow
A tenant should eventually be able to configure its Telegram integration through the admin panel.
Expected flow:
Tenant Admin -> Enter Telegram Bot Token -> Validate Token -> Configure Channel -> Validate Channel -> Check Bot Permissions -> Connection = VERIFIED

The system should verify that the bot has the permissions required for the configured functionality. Do not assume that a bot can perform an operation unless the Telegram Bot API and its channel permissions actually allow it.

---

## 4. Current Development Bot
The existing test bot may be used during development. However:
- TEST BOT ≠ PRODUCTION BOT
- The code must never depend on the current token.
- All Telegram configuration must be externalized.

---

## 5. Referral Minimum Balance
For the referral model:
- **Current Crypto Minimum Balance**: 300 USD
- This is the current business requirement. However, 300 is NOT a hard-coded constant. It must be configurable without modifying source code.

---

## 6. Referral Maximum Balance
There is NO maximum balance requirement. Eligibility is:
balance >= minimum_balance

- $300 → eligible
- $500 → eligible
- $1,000 → eligible
- $5,000 → eligible  
Do NOT implement minimum <= balance <= maximum. There is no maximum.

---

## 7. Trading Activity Requirement
For referral users who receive VIP access:
- **Minimum qualifying trades**: 1 per week (current rule).
- Must be configurable (minimum_trades_per_week = 1). Do not hard-code 1.

---

## 8. Important Distinction: Trading Activity vs Performance Log
These are two completely different concepts:

- **Trading Activity** (Answers: *Did the user actually trade?*):
  - Source: Broker API / Exchange API / Trading account API.
  - Data: 
umber_of_trades, last_trade_timestamp, olume, lots, symbols, qualifying_trades.
  - Determines whether the user satisfies the trading activity requirement.

- **Performance Log** (Answers: *Did the user send us a performance/trading report?*):
  - User sends: screenshot, image, text, CSV, document, evidence.
  - Used for: performance reporting, social proof, internal analysis, marketing campaigns.
  - **Do NOT use the existence of a PerformanceLog as proof that the user actually traded.**

---

## 9. Performance Log Rules
The architecture must support both:
- **Last-log rule** (e.g., maximum_days_since_last_log = 30)
- **Count-based rule** (e.g., minimum_performance_logs = 10, performance_log_window_days = 30)

The exact final business policy can be configured later.

---

## 10. Paid Access Model
Paid access and referral access are different eligibility mechanisms:
Paid:     Payment -> Payment Verification -> Subscription / Entitlement -> VIP Membership
Referral: Referral Verification -> Balance Verification -> Trading Eligibility -> Subscription / Entitlement -> VIP Membership


---

## 11. Important Domain Separation
Do NOT treat Payment = Membership. They are separate concepts:
- **Payment**: Represents money received (Payment #1, TXID, Amount, Network, Asset, Verification status).
- **Subscription / Entitlement**: Represents the user's right to access (Plan, Start Date, End Date, Access Type, Status).
- **VIP Membership**: Represents actual Telegram access state (ACTIVE, SUSPENDED, EXPIRED, REVOKED).

---

## 12. Why This Separation Matters
Example:
1. User pays  -> Payment #1 -> Subscription #1 -> VIP Membership ACTIVE
2. One month later user pays again -> Payment #2 -> Subscription Renewal -> VIP Membership remains ACTIVE
3. If subscription expires -> Payment history remains intact, Subscription = EXPIRED, Membership = REVOKED. Never delete or overwrite historical payments.

---

## 13. Referral Users Have No Payment
A referral user may become eligible without making a payment to our platform. Do not force referral users through the payment subsystem.

---

## 14. Payment Verification Requirements
For paid users, the system must verify:
- Transaction exists
- Correct blockchain/network
- Correct destination wallet
- Correct asset
- Correct amount
- Successful transaction
- Sufficient confirmations
- Transaction not previously used  
**The same TX hash must never be accepted for multiple users.**

---

## 15. Payment Idempotency
Payment verification must be idempotent:
- **First submission**: VERIFY -> ACCEPT
- **Second submission (same user)**: DO NOT create another payment/subscription/membership.
- **Another user submits same TX hash**: REJECT / DUPLICATE. Use database-level uniqueness constraints.

---

## 16. Money Handling
Never use floating point for financial values. Use Decimal and appropriate database numeric/decimal types.

---

## 17. Current Paid Plans
- 1 Month = 
- 3 Months =   
Initial values only; must be configurable in business logic.

---

## 18. Referral Eligibility
- Current Crypto rule: minimum balance = 
- Current Forex rule: minimum balance/deposit =  (Must be configurable).

---

## 19. Forex IB ID
The current workflow contains ib_id = 265676. Model it as tenant configuration (ReferralProviderConfiguration). Current value can be used as initial dev configuration.

---

## 20. Trial & Grace Period
- 7-day trial
- 7-hour grace period  
Make them configurable. Confirm Forex trial behavior before implementing (do not invent rules).

---

## 21. Monitoring
Referral users must be periodically monitored for:
- Balance (Check current balance)
- Referral status (Check still under our IB/ref)
- Trading activity (Check qualifying trades, e.g., >= 1/week)

---

## 22. Compliance State
Do not immediately revoke a user based on a temporary API failure. Distinguish between:
- COMPLIANT, WARNING, NON_COMPLIANT, SUSPENDED, REVOKED
- PROVIDER_UNAVAILABLE, VERIFICATION_PENDING  
An API outage must NOT be interpreted as user inactivity.

---

## 23. Grace Period
Use configurable grace periods (grace_period_days). Do not hard-code timing.

---

## 24. Warning System
- Maximum warnings = 3
- Warning interval = 5 days  
Treat as configuration parameters (max_warnings = 3, warning_interval_days = 5).

---

## 25. New User Protection
Newly approved members must NOT be treated as non-compliant on Day 1. Respect an onboarding grace period (compliance_grace_period_days = 30).

---

## 26. Existing n8n Bug Corrections
Do NOT reproduce these bugs from the prototype:
- **BUG-01**: Broken Telegram invite generation. Implement one centralized, tested, idempotent InviteService.
- **BUG-02**: 30-minute log window accidentally used instead of intended compliance policy.
- **BUG-03**: Crypto referral minimum accidentally became  (Correct initial = ).
- **BUG-04**: Forex channel removal hard-coded to Crypto channel. All membership operations must resolve channel IDs from tenant config.

---

## 27. Multi-Tenant Telegram Model
Each tenant may have: Telegram Bot + Forex VIP Channel + Crypto VIP Channel + Optional Channels. Channel IDs must be tenant configuration.

---

## 28. Tenant Credential Isolation
A provider credential belongs to a tenant. Never allow Tenant A to access Tenant B credentials. All provider calls must be scoped to tenant.

---

## 29. Telegram Bot Permissions
Before enabling a tenant's Telegram integration, verify: bot token valid, channel exists, bot is present, required admin permissions exist. Return clear configuration errors if unsupported.

---

## 30. Security of Existing Test Credentials
Never import credentials from old workflow files into source code. Inject new credentials through secure configuration.

---

## 31. Current Architecture Decision
Use: **Modular Monolith + FastAPI + PostgreSQL + Redis + APScheduler + SQLAlchemy + Alembic**. Do NOT introduce microservices unless explicitly required.

---

## 32. Scheduled Job Safety
Use distributed locking and idempotency keys (	enant_id + period_start) so multiple instances do not execute duplicate jobs or actions.

---

## 33. Existing n8n Migration
Extract business logic into: Domain, Services, Repositories, Providers, Jobs. The Telegram layer must only handle I/O.

---

## 34. Migration Strategy
Keep n8n alive during initial migration for parallel validation. Compare eligibility decisions, payments, referral verifications, and compliance results before disabling n8n.

---

## 35. Signal Mirroring
Optional module protected by feature flag (signal_mirroring_enabled = false). Implement after core VIP management is stable.

---

## 36. AI Messaging
AI is optional. System must work with template fallback. AI must NOT independently decide payments, eligibility, or membership status.

---

## 37. Required Phase 1 Output
Provide:
- Final Architecture & Domain boundaries
- ERD (Relationships between Tenant, User, Payment, Plan, Subscription, Referral, Trading, VIPMembership, etc.)
- State Machines (Onboarding, Payment, Referral, Membership, Compliance)
- Configuration Model
- Provider Contracts (BlockchainProvider, ReferralProvider, TradingActivityProvider, TelegramProvider, etc.)
- Testing Strategy

---

## 38. External API Rule
If an external API is unclear, DO NOT invent endpoints. Implement provider interfaces and mock providers to test business logic first.

---

## 39. Current Business Rules — Source of Truth
- **Paid**: 1 Month = , 3 Months = 
- **Crypto Referral**: Min Balance = , Max = None
- **Forex Referral**: Min Balance = , IB ID = 265676
- **Trading**: Min Qualifying Trades = 1 / week
- **Trial**: 7 days, Grace = 7 hours
- **Warnings**: Max = 3, Interval = 5 days
- **AI**: Optional
- **Signal Mirroring**: Disabled initially

---

## 40. Final Instruction
This document takes precedence if any existing n8n behavior conflicts with these rules. Proceed with Phase 1 architecture and implementation planning.
