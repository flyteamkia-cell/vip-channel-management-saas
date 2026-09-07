# Phase 0 — Final Clarifications & Business Rules

**Project**: VIP Channel Management SaaS

This document supersedes any ambiguity in the previous Phase 0 report. Use these
decisions as the current source of truth for Phase 1 architecture and
implementation.

---

## 1. Telegram Bot Architecture

The Telegram Bot Token currently found in the n8n workflow belongs to a TEST BOT.
It is NOT the intended production SaaS bot.

Therefore:

- Do not treat the current Telegram token as the production credential.
- It can be used temporarily for development/testing if necessary.
- Production will use a different Telegram bot.
- The architecture must support changing the bot token without changing source code.

### SaaS Requirement

This is a multi-tenant SaaS. Every customer/tenant using the platform must be
able to connect their own Telegram bot.

Expected architecture:

```
SaaS Platform
    │
    ├── Tenant A
    │     └── Telegram Bot A
    │
    ├── Tenant B
    │     └── Telegram Bot B
    │
    ├── Tenant C
    │     └── Telegram Bot C
    │
    └── Tenant D
          └── Telegram Bot D
```

Each tenant should be able to configure:

- Telegram Bot Token
- Telegram Channel IDs
- Telegram Group IDs where applicable
- Required bot permissions
- VIP destinations

---

## 2. Telegram Credential Security

Telegram Bot Tokens are sensitive credentials. They must:

- never be hard-coded in source code
- never be committed to Git
- never appear in logs
- never be returned through normal API responses
- never be exposed to frontend JavaScript

Store them using secure encrypted credential storage. Recommended model:

```
ProviderCredential
------------------
id
tenant_id
provider_type
credential_name
encrypted_secret
created_at
updated_at
```

The encryption key itself must remain outside the database, for example in:

```
ENV / Secret Manager
```

---

## 3. Telegram Connection Flow

A tenant should eventually be able to configure its Telegram integration through
the admin panel.

Expected flow:

```
Tenant Admin
     ↓
Enter Telegram Bot Token
     ↓
Validate Token
     ↓
Configure Channel
     ↓
Validate Channel
     ↓
Check Bot Permissions
     ↓
Connection = VERIFIED
```

The system should verify that the bot has the permissions required for the
configured functionality. Do not assume that a bot can perform an operation
unless the Telegram Bot API and its channel permissions actually allow it.

---

## 4. Current Development Bot

The existing test bot may be used during development. However:

```
TEST BOT ≠ PRODUCTION BOT
```

The code must never depend on the current token. All Telegram configuration must
be externalized.

---

## 5. Referral Minimum Balance

For the referral model:

**Current Crypto Minimum Balance**

```
300 USD
```

This is the current business requirement. However, 300 is NOT a hard-coded
constant. It must be configurable.

Example:

```
minimum_balance = 300
```

Later an administrator may change it to:

```
500
1000
1500
...
```

without modifying source code.

---

## 6. Referral Maximum Balance

There is NO maximum balance requirement. Eligibility is:

```
balance >= minimum_balance
```

Example:

```
$300   → eligible
$500   → eligible
$1,000 → eligible
$5,000 → eligible
```

Do not implement:

```
minimum <= balance <= maximum
```

There is no maximum.

---

## 7. Trading Activity Requirement

For referral users who receive VIP access:

```
Minimum qualifying trades = 1 per week
```

This is the current business rule. However, it must also be configurable.

Recommended configuration:

```
minimum_trades_per_week = 1
```

Future configurations may be:

```
2 trades/week
5 trades/week
10 trades/month
minimum volume
minimum lots
etc.
```

Do not hard-code `1`.

---

## 8. Important Distinction: Trading Activity vs Performance Log

These are two completely different concepts.

### Trading Activity

This answers: **Did the user actually trade?**

Source:

- Broker API
- Exchange API
- Trading/account API

Possible data:

```
number_of_trades
last_trade_timestamp
volume
lots
symbols
trade_history
qualifying_trades
```

This determines whether the user satisfies the trading activity requirement.

### Performance Log

This answers: **Did the user send us a performance/trading report?**

The user may send:

- screenshot
- image
- text
- CSV
- document
- other configured evidence

Performance logs are primarily used for:

- performance reporting
- social proof
- internal analysis
- future marketing/campaigns

Do NOT use the existence of a PerformanceLog as proof that the user actually
traded.

---

## 9. Performance Log Rules

The architecture must support both:

**Last-log rule** — example:

```
maximum_days_since_last_log = 30
```

and:

**Count-based rule** — example:

```
minimum_performance_logs = 10
performance_log_window_days = 30
```

These are not equivalent.

The system must support configurable rules such as:

```
minimum_performance_logs
performance_log_window_days
maximum_days_since_last_performance_log
```

The exact final business policy can be configured later.

---

## 10. Paid Access Model

Paid access and referral access are different eligibility mechanisms.

**Paid**

```
Payment
   ↓
Payment Verification
   ↓
Subscription / Entitlement
   ↓
VIP Membership
```

**Referral**

```
Referral Verification
   ↓
Balance Verification
   ↓
Trading Eligibility
   ↓
Subscription / Entitlement
   ↓
VIP Membership
```

---

## 11. Important Domain Separation

Do NOT treat:

```
Payment = Membership
```

They are separate concepts.

### Payment

Represents money received. Example:

```
User
Payment #1
TXID
Amount
Network
Asset
Timestamp
Verification status
```

### Subscription / Entitlement

Represents the user's right to access the service. Example:

```
Plan
Start Date
End Date
Access Type
Status
```

### VIP Membership

Represents the actual Telegram access state. Example:

```
ACTIVE
SUSPENDED
EXPIRED
REVOKED
```

---

## 12. Why This Separation Matters

Example:

A user pays $49:

```
Payment #1
↓
Subscription #1
↓
VIP Membership ACTIVE
```

One month later the user pays again:

```
Payment #2
↓
Subscription Renewal
↓
VIP Membership remains ACTIVE
```

If the subscription expires:

```
Payment history remains intact
Subscription = EXPIRED
Membership = REVOKED
```

Never delete or overwrite the historical payment.

---

## 13. Referral Users Have No Payment

A referral user may become eligible without making a payment to our platform.

Therefore:

```
Referral verification
      ↓
Eligibility
      ↓
Access entitlement
      ↓
VIP Membership
```

Do not force referral users through the payment subsystem.

---

## 14. Payment Verification Requirements

For paid users, the system must verify:

- transaction exists
- correct blockchain/network
- correct destination wallet
- correct asset
- correct amount
- successful transaction
- sufficient confirmations
- transaction not previously used

**The same TX hash must never be accepted for multiple users.**

---

## 15. Payment Idempotency

Payment verification must be idempotent.

If the same user submits the same TX hash multiple times:

```
First submission:
VERIFY → ACCEPT

Second submission:
DO NOT create another payment
DO NOT create another subscription
DO NOT create another membership
```

If another user submits the same TX hash:

```
REJECT / DUPLICATE
```

Use database-level uniqueness constraints where appropriate.

---

## 16. Money Handling

Never use floating point for financial values.

Use:

```
Decimal
```

and appropriate database numeric/decimal types.

---

## 17. Current Paid Plans

Current values extracted from the existing system:

```
1 Month  = $49
3 Months = $130
```

These are initial values only. They must be configurable. Do not hard-code them
into business logic.

---

## 18. Referral Eligibility

Current Crypto rule:

```
minimum balance = $300
```

Current Forex rule from existing system:

```
minimum balance/deposit = $500
```

The Forex value must also be configurable.

---

## 19. Forex IB ID

The current n8n workflow contains:

```
ib_id = 265676
```

Do NOT assume this is globally hard-coded for the SaaS. Model it as
provider/tenant configuration. For example:

```
ReferralProviderConfiguration
    tenant_id
    provider
    market
    ib_id
```

The current value can be used as the initial development configuration.

---

## 20. Trial

The existing workflow contains a:

```
7-day trial
```

and a:

```
7-hour grace period
```

Do not assume these are universal SaaS rules. Make them configurable.

The existing workflow appears to expose the trial primarily through the Crypto
referral path. Before implementing Forex trial behavior, confirm the business
rule. Do not invent Forex trial behavior.

---

## 21. Monitoring

Referral users must be periodically monitored. At minimum:

**Balance** — check:

```
current balance
```

**Referral status** — check:

```
still under our referral
```

**Trading activity** — check:

```
qualifying trades during the required period
```

Current requirement:

```
>= 1 qualifying trade per week
```

---

## 22. Compliance State

Do not immediately revoke a user based on a temporary API failure.

Distinguish between:

```
COMPLIANT
WARNING
NON_COMPLIANT
SUSPENDED
REVOKED
```

and:

```
PROVIDER_UNAVAILABLE
VERIFICATION_PENDING
```

An API outage must NOT be interpreted as user inactivity.

---

## 23. Grace Period

Use configurable grace periods. Example:

```
grace_period_days
```

Do not hard-code business timing into code.

---

## 24. Warning System

The existing workflow has:

```
maximum 3 warnings
warning interval = 5 days
```

Treat these as current configuration, not permanent constants. Example:

```
max_warnings = 3
warning_interval_days = 5
```

---

## 25. New User Protection

A newly approved member must NOT immediately be treated as non-compliant. The
compliance engine must respect a configurable onboarding/grace period. Example:

```
compliance_grace_period_days = 30
```

Current interpretation from the corrected workflow is that compliance warnings
should NOT start on day 1. Make this configurable.

---

## 26. Existing n8n Bug Corrections

The following bugs identified during Phase 0 must NOT be reproduced.

### BUG-01

Broken Telegram invite generation due to malformed expression/string
construction.

Implement one centralized, tested, idempotent:

```
InviteService
```

Do not duplicate invite-generation logic across payment/referral/trial branches.

### BUG-02

30-minute log window accidentally used instead of the intended compliance policy.

Do not reproduce this. All timing rules must be explicit configuration.

### BUG-03

Crypto referral minimum accidentally became **$10**.

Correct initial value:

```
$300
```

But keep it configurable.

### BUG-04

Forex channel membership removal incorrectly hard-coded to Crypto channel.

Never hard-code channel IDs. All membership operations must resolve the correct
channel from tenant/market configuration.

---

## 27. Multi-Tenant Telegram Model

Each tenant may have:

```
Telegram Bot
+
Forex VIP Channel
+
Crypto VIP Channel
+
Optional additional channels
```

Example:

```
Tenant A
 ├── Bot A
 ├── Forex Channel A
 └── Crypto Channel A

Tenant B
 ├── Bot B
 ├── Forex Channel B
 └── Crypto Channel B
```

Channel IDs must be tenant configuration.

---

## 28. Tenant Credential Isolation

A provider credential belongs to a tenant.

Never allow:

```
Tenant A
    ↓
access
    ↓
Tenant B credentials
```

All provider calls must be scoped to tenant.

---

## 29. Telegram Bot Permissions

Before enabling a tenant's Telegram integration, verify:

- bot token valid
- channel exists
- bot is present
- required admin permissions exist
- required operations are actually supported

If a required Telegram operation cannot be performed due to Bot API limitations,
return a clear configuration error. Do not silently fail.

---

## 30. Security of Existing Test Credentials

The existing n8n file contains real credentials. The current Telegram bot is a
TEST BOT. Nevertheless:

- Supabase service-role credentials must be rotated if the file was shared
  outside a trusted environment.
- Any production credential accidentally present in the file must be rotated.
- The Python implementation must never import these secrets into source code.
- New credentials must be injected through secure configuration.

---

## 31. Current Architecture Decision

Use:

```
Modular Monolith
+
FastAPI
+
PostgreSQL
+
Redis
+
APScheduler
+
SQLAlchemy
+
Alembic
```

Do NOT introduce microservices unless a concrete requirement appears. The
architecture should preserve clear domain boundaries so future extraction is
possible.

---

## 32. Scheduled Job Safety

Multiple application instances must not execute the same scheduled business
operation simultaneously.

Use:

- distributed locking
- idempotency
- unique job execution keys

Example:

```
weekly_trade_check:
tenant_id + period_start
```

Running the same job twice must not send duplicate messages or perform duplicate
membership actions.

---

## 33. Existing n8n Migration

Do not reproduce n8n node-by-node. Extract business logic and implement it as:

```
Domain
Services
Repositories
Providers
Jobs
```

The Telegram layer must only handle I/O. Business logic must not live inside
Telegram handlers.

---

## 34. Migration Strategy

Keep n8n alive during the initial migration. Use:

```
n8n
+
Python
```

in a controlled parallel validation period.

Compare:

- eligibility decisions
- payment verification
- referral verification
- membership actions
- compliance results

Only after confidence is established should n8n be disabled.

---

## 35. Signal Mirroring

Signal mirroring is a separate optional module. Do NOT mix it with the core
membership engine.

Architecture:

```
Master Channel
      ↓
Signal Parser
      ↓
Normalized Signal
      ↓
Mirror Engine
      ↓
Client Channels
```

It should be protected by a feature flag:

```
signal_mirroring_enabled = false
```

initially. Implement it after the core VIP management system is stable.

---

## 36. AI Messaging

AI is optional. The entire system must work without AI.

Architecture:

```
Messaging Engine
      ↓
Messaging Strategy
      ├── Template Strategy
      └── AI Strategy
```

AI should generate communication. AI must NOT independently decide:

- payment validity
- referral eligibility
- balance eligibility
- trading eligibility
- membership status
- suspension
- revocation

Those decisions must remain deterministic and auditable.

---

## 37. Required Phase 1 Output

Before generating large amounts of code, provide:

### A. Final Architecture

Include:

- component architecture
- domain boundaries
- provider interfaces
- database architecture
- Telegram architecture
- scheduler architecture

### B. ERD

Show relationships between:

```
Tenant
User
Payment
PaymentVerification
Plan
Subscription
ReferralProvider
ReferralAccount
TradingActivity
PerformanceLog
VIPMembership
TelegramBot
TelegramChannel
MessageTemplate
MessageLog
Rule
AuditLog
ProviderCredential
```

### C. State Machines

Document:

- onboarding state machine
- payment state machine
- referral state machine
- membership state machine
- compliance state machine

### D. Configuration Model

Clearly separate:

```
Infrastructure Secrets
Business Configuration
Tenant Configuration
System Defaults
```

### E. Provider Contracts

Define interfaces for:

```
BlockchainProvider
ReferralProvider
TradingActivityProvider
TelegramProvider
PerformanceLogProvider
AIProvider
```

### F. Testing Strategy

Show:

- unit tests
- integration tests
- end-to-end tests
- mock providers
- idempotency tests
- multi-tenant isolation tests

---

## 38. Important Rule

If any external API is unclear: **DO NOT invent endpoints.**

Instead:

1. inspect official documentation;
2. ask for API documentation/sample responses if required;
3. implement the provider interface;
4. implement a mock provider;
5. test business logic against the mock;
6. integrate the real provider once documentation is available.

This applies especially to:

- Bitunix
- ePlanet
- blockchain providers
- Telegram operations

---

## 39. Current Business Rules — Source of Truth

For the current implementation:

```
Paid:
1 Month  = $49
3 Months = $130

Crypto Referral:
Minimum Balance = $300
Maximum Balance = None

Forex Referral:
Minimum Balance = $500
IB ID = 265676

Trading:
Minimum Qualifying Trades = 1 / week

Trial:
7 days
Grace = 7 hours

Warnings:
Maximum  = 3
Interval = 5 days

AI:
Optional

Signal Mirroring:
Disabled initially
```

All of these except structural behavior must remain configurable.

---

## 40. Final Instruction

Do not interpret this document as permission to blindly implement every existing
n8n behavior.

The goal is:

```
Existing validated business logic
+
Corrections for identified bugs
+
Clean domain architecture
+
Multi-tenancy
+
Security
+
Idempotency
+
Configurability
+
Testability
```

If the existing n8n behavior conflicts with the rules in this document, this
document takes precedence.

Proceed with Phase 1 architecture and implementation planning.
