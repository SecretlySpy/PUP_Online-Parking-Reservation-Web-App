# ISO/IEC 25010 Evaluation — PUP Online Parking Reservation

This document maps the implemented system to the study's named ISO/IEC 25010
product-quality characteristics: functional suitability, usability,
reliability, performance efficiency, and security.

Evidence labels: `T` automated test, `C` automated check, `F` implementation,
`O` operational requirement. Evidence reflects the 2026-07-13 checkout; no
undated manual walkthrough is treated as current proof.

## 1. Functional Suitability

| Sub-characteristic | Current evidence |
|---|---|
| Functional completeness | `F` Public facility/live availability; customer account/vehicle/booking/payment/QR/history/email flows; administrator inventory, monitoring, customer management, controlled reservation/billing transitions, and reports; automated lifecycle reconciliation. |
| Functional correctness | `T` 104 passing tests cover role rules, booking validation, time-window database integrity, overlap behavior, payment pairing/idempotency, webhook reconciliation, receipts, lifecycle transitions, QR/check-in, pagination, dashboard aggregates/actions, and error pages. |
| Functional appropriateness | `F` Role dispatcher and decorators send users to the relevant workspace. Browser payment return is informational while the signed webhook is authoritative. Dashboard choices expose only state-graph transitions. |

**Result:** `manage.py test --settings=config.settings_test` passed 104/104;
`manage.py check --settings=config.settings_test` reported 0 issues.

## 2. Usability

| Sub-characteristic | Current evidence |
|---|---|
| Appropriateness recognisability | `F` Role-aware navigation, explicit Reserve/Pay now/Verify/admin actions, status badges, and literal eligibility/error messages. |
| Learnability and operability | `F` Shared page shell/form renderer/pagination; guided empty states; facility cards; customer/admin workflows use consistent templates and messages. |
| User-error protection | `F` Server validation covers incomplete/past/short/long windows, inactive floors, maintenance, ownership/type mismatch, overlaps, invalid transitions, unpaid/early/expired arrival, and paid-state downgrade. Payment start requires a CSRF-protected POST. |
| UI aesthetics and device adaptability | `F` Responsive PUP-branded CSS, grid/flex layouts, local images, and no external frontend/CDN dependency. |
| Accessibility foundation | `F` Semantic forms/labels, keyboard-operable native controls, message regions, and custom error pages. `O` A formal WCAG audit with assistive technology remains required before making a conformance claim. |

**Human evaluation requirement:** administer the approved usability/UAT
instrument to representative students, employees, visitors, and administrators.
Record sample size, mean, standard deviation, task completion, and qualitative
issues; automated tests do not substitute for respondent evidence.

## 3. Reliability

| Sub-characteristic | Current evidence |
|---|---|
| Maturity | `T` 104-test hermetic regression suite plus migration, compilation, dependency, whitespace, deployment, and static-asset gates. CI repeats the clean-checkout path on Windows. |
| Fault avoidance | `F` Reservation creation/modification repeats mutable validation under Slot/Vehicle locks. Deployment MySQL `SELECT ... FOR UPDATE` serializes competing booking decisions. A database constraint enforces `end_at > start_at`; it does not itself prevent overlaps. |
| Financial consistency | `F` Reservation -> Payment lock order; one Payment per Reservation; one BillingRecord per Payment; stable per-attempt checkout idempotency key; paid state cannot be downgraded. |
| Duplicate/replay tolerance | `F` Webhook HMAC is mode/freshness bound; unique provider event IDs deduplicate across workers; exact session/reference/amount/currency validation fails closed; notification timestamps reserve at-most-once dispatch attempts. |
| Recoverability | `F` Signed webhook reconciles even if browser return is lost. Idempotent lifecycle command repairs ended/stale reservation state. Failed/cancelled notices guide customers; paid cancellation emits a refund-review audit marker. |
| Graceful degradation | `F` Polling retains the last server-rendered grid on fetch failure; pages work without JavaScript. Activity-log failures are reported to operator logs but do not abort domain requests. |

**Boundary:** SQLite is appropriate for hermetic tests/local development but
does not prove MySQL row-lock behavior. A deployment-stage MySQL concurrency
test remains recommended.

## 4. Performance Efficiency

| Sub-characteristic | Current evidence |
|---|---|
| Time behavior | `F` Availability uses one overlap query plus `select_related("floor")`; reservation overlap/monitor lookups have a composite `(slot,status,start_at,end_at)` index. |
| Resource utilization | `F` Live refresh requests only slot-grid fragments at 10-second intervals; JSON snapshot is compact; WhiteNoise emits compressed/fingerprinted production assets. |
| Capacity protection | `F` Customer reservation/payment histories: 20/page. Reservation manager: 50/page. Billing payments and billing records: independent 50/page. Customer list: 50/page. Customer detail reservation/payment histories: independent 20/page. |
| External-call bounds | `F` PayMongo REST uses a 20-second request timeout and idempotency key. Email backend has configurable positive timeout validated for deployment. |

**Measurement requirement:** load-test availability, booking contention, webhook
delivery, and dashboard pagination against representative MySQL data. Report
median/p95/p99 latency, throughput, error rate, and database lock waits rather
than inferring performance from unit tests.

## 5. Security

| Sub-characteristic | Current evidence |
|---|---|
| Confidentiality and access control | `T/F` Owner-scoped reservations/vehicles/receipts; customer/admin decorators; privileged/non-customer accounts excluded from customer actions; generic Django admin route absent outside debug. |
| Authenticity | `F` PBKDF2-first hashing, Django sessions, signed single-use password reset, signed QR token. `T` password hashes and tamper rejection covered. |
| Privileged enrollment | `F` Admin registration disabled by default; disabled route returns 404; configured code required and constant-time compared; failed code guesses are IP/window throttled through durable audit records. |
| Payment authenticity/integrity | `F` Explicit debug/test-only simulator; unconfigured production checkout fails closed; POST-only checkout; PayMongo idempotency key; mode/freshness-aware HMAC; unique event dedupe; exact financial/session validation. |
| State integrity | `F` One-way reservation graph; paid QR/check-in requirement; arrival window enforcement; database positive-window and receipt/event uniqueness constraints; controlled dashboard reconciliation. |
| Request forgery protection | `F` Browser state-changing forms use Django CSRF and POST requirements. The PayMongo webhook is intentionally CSRF-exempt and authenticated with its provider HMAC instead. |
| Accountability | `F` ActivityLog captures actor label/IP/action; manual financial actions attribute the administrator; provider-event outcome/detail is retained; paid cancellation produces explicit refund-review evidence. |
| Deployment hardening | `C` `check --deploy` passed with DEBUG off, strong secret, allowed host, matching PayMongo key mode, webhook secret/tolerance, simulator off, safe admin enrollment/throttle, public HTTPS site URL, and configured email delivery. HTTPS redirect, secure cookies, HSTS/preload, nosniff, and proxy SSL handling are enabled outside debug. |

## 6. Objective Evidence Summary

| Command | Verified result |
|---|---|
| `.venv\Scripts\python.exe manage.py test --settings=config.settings_test -v 1` | **104 passed** in 124.285 seconds |
| `.venv\Scripts\python.exe manage.py check --settings=config.settings_test` | **0 issues** |
| `.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_test` | **No changes detected** |
| `.venv\Scripts\python.exe -m compileall -q accounts config core dashboard parking payments reservations` | **Passed** |
| `uv pip check --python .venv\Scripts\python.exe` | **15 packages compatible** |
| `git diff --check` | **No whitespace errors**; CRLF conversion notices only |
| `manage.py check --deploy` with complete temporary production settings | **0 issues** |
| `manage.py collectstatic --noinput` with `DEBUG=False` | **138 present, 365 post-processed** |

## 7. Residual Operational Requirements

| Requirement | Status and rationale |
|---|---|
| Lifecycle scheduling | `O` Repository provides an idempotent command; deployment must invoke it approximately every minute. |
| SMTP delivery monitoring/retry | `O` Notification timestamps indicate an attempted dispatch, not confirmed delivery. Monitor the provider and define retry/escalation policy. |
| Refund execution | `O` Paid cancellation creates an audit marker and guidance; refund state/API execution remains manual. |
| Production media storage | `O` WhiteNoise serves static files only; uploaded media requires dedicated storage/serving. |
| Asynchronous webhook work | `O` Reconciliation is synchronous and financially idempotent. If provider acknowledgement latency becomes material, introduce a durable job queue/outbox rather than an in-process thread. |
| Compatibility/maintainability/portability | Structurally supported by modular apps, ORM/config separation, CI, comments, and `AI Documentation Notes.md`; quantitative evaluation is outside the study's five selected characteristics. |
