# ISO/IEC 25010 Evaluation — PUP Online Parking Reservation

This document maps the system to the ISO/IEC 25010 product-quality
characteristics named in the study's objectives — **functional suitability,
usability, reliability, performance efficiency, and security** — with the
design decisions and **objective evidence** (automated tests, checks, live
runs) that support each. It also proposes the respondent instrument for the
usability/UAT portion.

Evidence key: `T` = automated test, `C` = management check, `L` = live run,
`F` = feature/implementation.

---

## 1. Functional Suitability
*Completeness, correctness, appropriateness — does it do the specified tasks correctly?*

| Sub-characteristic | Evidence |
|---|---|
| Functional completeness (all specified features present) | `F` all six objectives implemented across `accounts/parking/reservations/payments/dashboard`; feature list in README. |
| Functional correctness | `T` 45 automated tests: PBKDF2 hashing, overlap-free booking, double-booking rejection, availability math, payment idempotency, webhook reconciliation, status transitions, dashboard aggregates. |
| Functional appropriateness | `F` role-based workflows route each user to the right tasks (customer booking vs admin management); `L` live admin walkthrough of all dashboard pages. |

**Result:** all 45 tests pass; `manage.py check` reports 0 issues.

---

## 2. Usability
*Learnability, operability, UI aesthetics, accessibility, error protection.*

| Sub-characteristic | Evidence |
|---|---|
| Appropriateness recognisability | `F` role-appropriate landing + navigation; clear CTAs ("Reserve", "Pay now", "Verify"). |
| Learnability / operability | `F` consistent page shell, uniform forms, dashboard subnav; guided empty states. |
| User-error protection | `F` server-side validation (past-time, duration bounds, overlap, maintenance); `F` CSRF on all forms; confirm-before-cancel. |
| UI aesthetics | `F` responsive PUP-branded design (maroon/gold), mobile-first grid/flex, no horizontal overflow. |
| Accessibility | `F` semantic HTML, labelled form fields, sufficient contrast, keyboard-usable controls. |

**Instrument (to be administered):** a respondent survey (e.g., 4-point Likert,
adapted from the ISO 25010 usability sub-characteristics / a standard usability
scale) across a representative sample of students, employees, visitors, and
administrators. Record mean and standard deviation per item; target ≥ 3.25/4.

---

## 3. Reliability
*Maturity, availability, fault tolerance, recoverability.*

| Sub-characteristic | Evidence |
|---|---|
| Maturity | `T` regression suite (45 tests) exercised each phase; the gate caught and forced reconciliation of a behavior change. |
| Fault tolerance | `F` payment state transitions are **idempotent** (duplicate webhook → one receipt/email); `T` covered. `F` activity logging and email sending never raise into the request path (`fail_silently` / swallowed). |
| Availability | `F` real-time views degrade gracefully — polling keeps the last good render on transient fetch errors; server-rendered fallback works without JS. |
| Recoverability | `F` gateway webhook is the source of truth, so a dropped return redirect still reconciles payment; DB constraints prevent inconsistent bookings. |

---

## 4. Performance Efficiency
*Time behaviour, resource utilisation, capacity.*

| Sub-characteristic | Evidence |
|---|---|
| Time behaviour | `F` availability queries use `select_related("floor")` and a single overlap query; `F` composite DB index on `Reservation(slot,status,start_at,end_at)` backs overlap/monitor lookups. |
| Resource utilisation | `F` real-time refresh fetches only the **grid fragment** (not the whole page) every 10 s; JSON API returns a compact snapshot. |
| Capacity | `F` list views bound result sets (dashboard tables capped at 200/50 rows); pagination-ready query patterns. |

**Suggested measurement:** load-test the availability endpoint (e.g., with a
seeded 200+ slot dataset) and record median/95th-percentile response time; the
fragment endpoint should stay well within interactive latency (< 300 ms local).

---

## 5. Security
*Confidentiality, integrity, authenticity, accountability, non-repudiation.*

| Sub-characteristic | Evidence |
|---|---|
| Confidentiality / access control | `T` cross-user denial: a customer cannot view/cancel another's reservation (403/404) or view another's receipt (403); admin-only areas return 403 for customers. |
| Authenticity (identity) | `F` PBKDF2 password hashing (pinned); `T` verified hashes start with `pbkdf2_`. `F` one-time, token-verified password reset by email. |
| Integrity | `F` QR payloads are **signed** (`django.core.signing`); `T` tampered tokens rejected. `F` PayMongo webhook **signature verification** (HMAC-SHA256). `F` CSRF protection on all state-changing forms. |
| Accountability | `F` `ActivityLog` records registrations, bookings, payments, status changes, verifications (surfaced in reports). |
| Deployment hardening | `C` `check --deploy` is **clean** with `DEBUG=False` + strong `SECRET_KEY`: SSL redirect, secure session/CSRF cookies, HSTS (+preload), content-type nosniff. |

---

## Summary of objective evidence

| Command | Result |
|---|---|
| `python manage.py test` | **45 passed** |
| `python manage.py check` | **0 issues** |
| `python manage.py check --deploy` (DEBUG=False, strong SECRET_KEY) | **0 issues** |
| Live HTTP admin walkthrough (login → all dashboard pages) | **all 200; anon → 302 login** |

The remaining ISO/IEC 25010 characteristics (compatibility, maintainability,
portability) are supported structurally — a modular Django app layout, a
DB-agnostic ORM (SQLite/MySQL via one env var), and a documented module
reference (`AI Documentation Notes.md`) — but were outside the study's stated
evaluation scope.
