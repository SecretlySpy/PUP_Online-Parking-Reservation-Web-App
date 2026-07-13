# PUP Online Parking Reservation

A role-based Django web application for real-time parking availability,
time-window reservations, online payments, QR-assisted arrival verification,
and campus parking administration.

The application is a modular monolith built with **Django 6**, **MySQL** for
deployment (SQLite for local development and hermetic tests), **PayMongo** for
hosted checkout, and **WhiteNoise** for production static assets. Its quality
evidence is mapped in
[`docs/ISO-IEC-25010-evaluation.md`](docs/ISO-IEC-25010-evaluation.md).

## Capabilities

### Public

- Browse facility floors, photos, and current availability.
- Search slots by floor, vehicle type, availability, date, and time.
- Use branded 400, 403, 404, and 500 error pages.

### Customer

- Register as a student, employee, or visitor and manage a profile/vehicles.
- Reset passwords through Django's signed, single-use email workflow.
- Create or modify a reservation with active-floor, maintenance, vehicle
  ownership/type, time-window, and overlap validation.
- Receive a pending payment record atomically with each new reservation.
- Pay by GCash, Maya, or card through PayMongo hosted checkout.
- View paginated reservation/payment histories and canonical e-receipts.
- Receive reservation-created, cancellation, payment-confirmation, and
  payment-failure email notices.
- Access a signed QR only for a paid, active reservation.

### Administrator

- Monitor live floor/slot state and view aggregate KPIs/reports.
- Manage floors, slots, reservations, billing, and payment reconciliation.
- Follow the one-way reservation state graph:
  `RESERVED -> OCCUPIED/CANCELLED`, `OCCUPIED -> COMPLETED`.
- Verify paid arrivals by signed QR within the configured arrival window.
- Search/filter customers, inspect customer details, and safely
  activate/deactivate non-privileged accounts.
- Review explicit audit events when a paid cancellation needs a manual refund.

### Operational safeguards

- Booking and modification repeat mutable validation under database row locks.
  The deployment concurrency guarantee relies on MySQL `SELECT ... FOR UPDATE`;
  SQLite remains suitable for local development/tests but does not provide the
  same row-lock behavior.
- Checkout creation is POST-only and uses a stable per-attempt PayMongo
  idempotency key. Signed webhooks are mode/freshness checked, durably
  deduplicated, and matched by session/reference/amount/currency. A database
  constraint permits one canonical billing record per payment.
- Lifecycle automation completes ended occupied sessions, cancels ended unused
  sessions, and expires stale unpaid holds.
- Administrator self-registration is disabled by default and fails closed.
- Temporary administrator enrollment is throttled by source IP through durable
  audit events; Django's generic admin routes are absent outside debug.
- Payment simulation is explicit and limited to debug/test runtimes.
- CI runs dependency, system, migration, test, and production-static checks.

## Tech stack

| Concern | Implementation |
|---|---|
| Runtime | Python 3.12+; Python 3.14.4 used for the current QA run |
| Backend | Django 6.0.7 |
| Database | MySQL target; SQLite local/test |
| MySQL driver | PyMySQL |
| Payments | PayMongo REST checkout and signed webhooks |
| Auth | Django auth; PBKDF2-first password hashing; role decorators |
| QR | `django.core.signing`, `qrcode`, Pillow |
| Configuration | `django-environ` |
| Static assets | WhiteNoise compressed manifest storage in production |
| Frontend | Django templates and dependency-free JavaScript polling |

## Quick start

PowerShell commands from the repository root:

```powershell
uv venv .venv --python 3.14
uv pip install -r requirements.txt
Copy-Item .env.example .env
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_parking
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver
```

Open <http://127.0.0.1:8000>. The supplied `.env.example` enables the payment
simulator for local development. Emails print to the console unless SMTP is
configured.

The base settings fail closed when PayMongo is unconfigured. Simulation runs
only when all three conditions hold: `DEBUG=True`,
`PAYMENT_SIMULATION_ENABLED=True`, and no PayMongo secret key is present.

## Configuration

Copy `.env.example` to `.env` and review every value before deployment.

| Variable | Purpose | Base default |
|---|---|---|
| `DEBUG` | Development diagnostics | `True` |
| `SECRET_KEY` | Django signing/encryption secret | insecure development value |
| `ALLOWED_HOSTS` | Comma-separated host names | `*` |
| `DATABASE_URL` | Django database URL | repository SQLite file |
| `EMAIL_*` | SMTP transport | console backend |
| `EMAIL_TIMEOUT` | Maximum email backend operation time in seconds | `10` |
| `ADMIN_SIGNUP_ENABLED` | Temporarily expose admin self-registration | `False` |
| `ADMIN_SIGNUP_CODE` | Strong enrollment code when signup is enabled | empty/fail-closed |
| `ADMIN_SIGNUP_MAX_ATTEMPTS` | Failed code guesses allowed per source IP/window | `5` |
| `ADMIN_SIGNUP_WINDOW_MINUTES` | Enrollment throttle window | `15` |
| `PAYMONGO_SECRET_KEY` | Server-side PayMongo credential | empty |
| `PAYMONGO_PUBLIC_KEY` | PayMongo public credential | empty |
| `PAYMONGO_WEBHOOK_SECRET` | Webhook HMAC secret | empty |
| `PAYMONGO_WEBHOOK_TOLERANCE_SECONDS` | Maximum signed-event age | `300` |
| `PAYMENT_SIMULATION_ENABLED` | Allow explicit debug/test simulator | `False` |
| `RESERVATION_FEE_CENTS` | Fee snapshot in centavos | `5000` |
| `RESERVATION_PAYMENT_GRACE_MINUTES` | Age before an unpaid future hold expires; `0` disables expiry | `30` |
| `RESERVATION_ARRIVAL_GRACE_MINUTES` | Allowed early-arrival window | `15` |
| `SITE_BASE_URL` | Absolute root for email and QR links | `http://127.0.0.1:8000` |
| `LOG_LEVEL` | Application/security console logging threshold | `INFO` |

### MySQL

Create a MySQL 8 database/user, then set:

```text
DATABASE_URL=mysql://pup_user:pup_pass@127.0.0.1:3306/pup_parking
```

Run `.venv\Scripts\python.exe manage.py migrate`. The current migration set
includes positive reservation-window integrity, payment notification/receipt
deduplication, checkout idempotency keys, and durable PayMongo event records.

### Real PayMongo

Set all three PayMongo variables, set `PAYMENT_SIMULATION_ENABLED=False`, and
point PayMongo's webhook to `/payments/webhook/`. The browser return URL is
informational; the signed webhook is the financial source of truth. Missing or
invalid production payment configuration never marks a payment paid.

### Administrator enrollment

Prefer `manage.py createsuperuser`. If temporary web enrollment is required,
set `ADMIN_SIGNUP_ENABLED=True` and use a non-placeholder code of at least 16
characters. Disable the endpoint immediately afterward. The endpoint returns
404 while disabled.

## Reservation lifecycle job

Preview and apply due transitions with:

```powershell
.venv\Scripts\python.exe manage.py process_reservations --dry-run
.venv\Scripts\python.exe manage.py process_reservations
.venv\Scripts\python.exe manage.py process_reservations --at "2026-07-13T18:00:00+08:00"
```

Schedule the idempotent command every minute in the deployment platform. Each
run:

- changes ended `OCCUPIED` reservations to `COMPLETED`;
- changes ended unused `RESERVED` reservations to `CANCELLED`;
- cancels stale future unpaid holds after the configured grace period;
- writes activity records and schedules cancellation notices after commit.

## QA

The dedicated test settings use in-memory SQLite, local-memory email/cache,
plain static storage, and explicit test-only payment simulation.

```powershell
.venv\Scripts\python.exe manage.py test --settings=config.settings_test
.venv\Scripts\python.exe manage.py check --settings=config.settings_test
.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.settings_test
.venv\Scripts\python.exe -m compileall -q accounts config core dashboard parking payments reservations
uv pip check --python .venv\Scripts\python.exe
git diff --check
```

Current result: **104 tests passed**; system checks found 0 issues; no migration
drift; dependency compatibility and compilation passed.

For deployment validation, use real secret values and run:

```powershell
.venv\Scripts\python.exe manage.py check --deploy
.venv\Scripts\python.exe manage.py collectstatic --noinput
```

The custom deploy checks require safe administrator enrollment/throttle
settings, the simulator disabled, matching-mode non-placeholder PayMongo
secret/public/webhook values, a positive webhook tolerance, public HTTPS
`SITE_BASE_URL`, and a delivery-capable email backend with a positive timeout.
WhiteNoise serves compressed, fingerprinted `STATIC_ROOT` assets when
`DEBUG=False`; user-uploaded media still requires separate production storage
or serving.

## Project structure

```text
config/          settings, deployment checks, root routing, WSGI/ASGI
core/            landing dispatch, constants, audit log, request IP middleware
accounts/        custom user, roles, authentication, profiles, vehicles
parking/         floors, slots, availability, facility and admin views
reservations/    booking services, state policy, QR, email, lifecycle command
payments/        PayMongo gateway, reconciliation services, receipts, email
dashboard/       monitoring, customer management, billing, reports, pagination
templates/       role-aware pages, fragments, email and error templates
static/          local CSS, JavaScript, and images
.github/         Windows CI workflow
```

See [`AI Documentation Notes.md`](AI%20Documentation%20Notes.md) for the
module/function reference and end-to-end control flows.

## Delimitations

This is a web-only, single-campus system. It has no barrier, CCTV, IoT, or
native mobile integration. PayMongo is the online payment provider. Refunds and
disputes remain manual; the system creates an explicit audit signal for paid
cancellations. Email delivery requires a configured SMTP service.
