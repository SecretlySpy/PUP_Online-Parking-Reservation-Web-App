# AI Documentation Notes

> Machine-readable reference for the **PUP Online Parking Reservation** system.
> Maintained per the mandatory post-change workflow (QA → gate → static analysis → docs).
> Field labels are uniform: **Purpose / Inputs / Outputs / Dependencies / Behavior**.
> Status legend: ✅ implemented & tested · 🔜 planned phase.

---

## 1. System Overview

- **Purpose:** Role-based web app to view real-time parking-slot availability, reserve slots for a date/time, pay reservation fees online, and give admins management + reporting tools. Replaces a manual Google-Forms process for a single campus facility.
- **Stack:** Python 3.14, Django 6.0.7, PyMySQL (MySQL driver), django-environ (config), qrcode+Pillow (QR), requests (PayMongo). venv at `.venv` (created with `uv`).
- **Database:** Driven by `DATABASE_URL`. Dev default = SQLite (`db.sqlite3`); production target = MySQL (utf8mb4, STRICT mode). ORM-portable; no raw SQL.
- **Entry points:** `manage.py` (CLI), `config/wsgi.py` (WSGI). Root URLconf `config/urls.py`. See also `README.md` and `docs/ISO-IEC-25010-evaluation.md`.
- **Architecture:** Standard Django MVT split into apps: `core` (shared), `accounts` (identity), `parking` (inventory + availability), `reservations` (bookings + QR), `payments` (gateway + billing), `dashboard` (admin + reports).
- **Control flow (request):** URL → app URLconf → view (function-based) → service/model → template. `ActivityLogMiddleware` annotates each request with `client_ip`.
- **Data flow (availability, the core real-time feature):** browser polls `parking:slots_partial`/`slots_api` every 10s → `_resolve_filters` parses filters → `services.slots_with_availability` queries `Slot` + (lazily) overlapping `Reservation`s → annotated slots rendered to grid/JSON.
- **Auth model:** Single `accounts.User` table with a `role` field. PBKDF2 password hashing (Django default, pinned in settings).

### Run / QA commands
```
uv pip install -r requirements.txt
python manage.py migrate
python manage.py seed_parking          # demo floors/slots
python manage.py runserver
python manage.py check                 # QA: system check
python manage.py check --deploy        # QA: security posture (clean when DEBUG=False + SECRET_KEY set)
python manage.py test                  # QA: 45 tests, all passing
```

---

## 2. Configuration — `config/`

### `config/__init__.py`
- **Purpose:** Register PyMySQL as the `MySQLdb` driver.
- **Behavior:** Calls `pymysql.install_as_MySQLdb()` at import. No-op semantics for SQLite. Runs before any DB engine loads.

### `config/settings.py`
- **Purpose:** Central configuration via environment variables.
- **Inputs:** `.env` file / OS env (read by `environ.Env`).
- **Key settings (literal):**
  - `AUTH_USER_MODEL = "accounts.User"`.
  - `PASSWORD_HASHERS[0] = PBKDF2PasswordHasher` (spec requirement, explicitly pinned).
  - `DATABASES["default"] = env.db("DATABASE_URL")`; MySQL branch injects `charset=utf8mb4`, `sql_mode=STRICT_TRANS_TABLES`.
  - `INSTALLED_APPS` local: `core, accounts, parking, reservations, payments, dashboard`.
  - `MIDDLEWARE` appends `core.middleware.ActivityLogMiddleware`.
  - `TEMPLATES.DIRS = [BASE_DIR/"templates"]`; context processor `core.context_processors.site`.
  - `TIME_ZONE = "Asia/Manila"`, `USE_TZ = True`.
  - Email: console backend by default; SMTP via env.
  - PayMongo keys, `RESERVATION_FEE_CENTS` (default 5000), `ADMIN_SIGNUP_CODE`, `SITE_*` branding.
  - `if not DEBUG`: enables SSL redirect, secure cookies, HSTS, nosniff.
- **Dependencies:** `django-environ`.

### `config/urls.py`
- **Purpose:** Root URL routing.
- **Outputs (routes):** `django-admin/` (Django admin), `accounts/`, `parking/`, `""`→`core`. Serves `MEDIA`/`STATIC` when `DEBUG`.
- **Note:** `reservations`, `payments`, `dashboard` includes added in their phases.

---

## 3. Core app — `core/`

### `core/constants.py`
- **`VehicleType(TextChoices)`** — Purpose: shared vehicle/slot categories for matching. Values: `MOTORCYCLE, CAR, SUV, VAN, TRUCK`. Consumed by `accounts.Vehicle`, `parking.Slot`.

### `core/models.py`
- **`ActivityLog(models.Model)`** ✅
  - Purpose: audit trail for reports.
  - Fields: `actor`(FK User, `SET_NULL`, nullable), `actor_label`(char150), `action`(char64, indexed), `description`(char255), `ip_address`(GenericIPAddress, nullable), `created_at`(auto_now_add, indexed).
  - Behavior: `Meta.ordering=["-created_at"]`. `__str__` = `"{actor_label or system}: {action}"`.
- **`log_activity(action, description="", actor=None, request=None)`** ✅
  - Purpose: write one audit entry from a domain event.
  - Inputs: `action`(str), `description`(str), `actor`(User|None), `request`(HttpRequest|None).
  - Outputs: `ActivityLog | None`.
  - Dependencies: `ActivityLog`.
  - Behavior/side effects: resolves actor from `request.user` if omitted; pulls `request.client_ip`; truncates to field limits; **DB insert**; swallows ALL exceptions (safe pre-migration).

### `core/middleware.py`
- **`ActivityLogMiddleware(get_response)`** ✅
  - Purpose: attach client IP to each request.
  - Behavior: sets `request.client_ip` (honors `X-Forwarded-For` first hop). Static `_client_ip(request) -> str|None`.

### `core/context_processors.py`
- **`site(request) -> dict`** ✅ — Outputs `{SITE_NAME, SITE_SHORT_NAME}` for all templates. Depends on `settings`.

### `core/views.py`
- **`home(request)`** ✅
  - Purpose: landing page + role dispatcher.
  - Outputs: `HttpResponse` (render `core/home.html`) or redirect.
  - Behavior: authenticated admin→`dashboard:home`, customer→`parking:slots`; on `NoReverseMatch` (target phase not built) falls back to rendering `core/home.html`; anonymous→render landing.

### `core/urls.py`
- Route: `""` → `home` (name `core:home`). `app_name="core"`.

### `core/admin.py`
- `ActivityLogAdmin`: read-only list (no add permission).

---

## 4. Accounts app — `accounts/`

### `accounts/models.py`
- **`Roles(TextChoices)`** ✅ — `STUDENT, EMPLOYEE, VISITOR, ADMIN`. `CUSTOMER_ROLES=(STUDENT,EMPLOYEE,VISITOR)`.
- **`CustomUserManager(UserManager)`** ✅ — `create_superuser(username, email=None, password=None, **extra)` forces `role=ADMIN`.
- **`User(AbstractUser)`** ✅
  - Fields added: `role`(char16, default VISITOR), `middle_name`, `id_number`, `contact_number`, `address`, `email`(**unique**, required for reset).
  - Props: `is_admin_role` (role==ADMIN or is_staff), `is_customer_role` (role in CUSTOMER_ROLES).
  - Override: `get_full_name()` joins first/middle/last.
- **`Vehicle(models.Model)`** ✅
  - Fields: `owner`(FK User CASCADE, related `vehicles`), `plate_number`(char16), `vehicle_type`(VehicleType), `make`, `model`, `color`, `created_at`.
  - Constraint: unique `(owner, plate_number)`. Prop `label`.

### `accounts/forms.py`
- **`_style(fields)`** — adds `form-input` CSS class to widgets.
- **`CustomerRegistrationForm(UserCreationForm)`** ✅ — fields `username, role, PROFILE_FIELDS`; `role` limited to customer roles; `clean_role` rejects non-customer; requires first/last/email. Side effect on save: `set_password` (PBKDF2).
- **`AdminRegistrationForm(UserCreationForm)`** ✅ — extra `access_code`; `clean_access_code` validates against `settings.ADMIN_SIGNUP_CODE` (only if configured); `save()` sets `role=ADMIN, is_staff=True`.
- **`LoginForm(AuthenticationForm)`**, **`ProfileForm(ModelForm=PROFILE_FIELDS)`**, **`VehicleForm(ModelForm)`** (`clean_plate_number` → upper).

### `accounts/decorators.py`
- **`admin_required(view)`** ✅ — Behavior: anon→login redirect; non-admin→`PermissionDenied` (403); admin→proceed.
- **`customer_required(view)`** ✅ — Behavior: anon→login redirect; admin→redirect `core:home`; non-customer→403; customer→proceed.

### `accounts/views.py`  (all ✅)
| Function | Purpose | Inputs | Output | Side effects |
|---|---|---|---|---|
| `register_customer(request)` | customer signup | POST form | redirect `core:home` / render | create User (PBKDF2), `log_activity`, `login()` |
| `register_admin(request)` | admin signup | POST form | redirect / render | create admin User, `log_activity`, `login()` |
| `profile(request)` | view/edit own profile | POST `ProfileForm` | redirect / render | update User, `log_activity`. `@login_required` |
| `vehicle_list(request)` | list own vehicles | — | render | `@customer_required` |
| `vehicle_add(request)` | add vehicle | POST `VehicleForm` | redirect | create Vehicle (owner=self), `log_activity` |
| `vehicle_edit(request, pk)` | edit own vehicle | POST | redirect | update; 404 if not owner |
| `vehicle_delete(request, pk)` | delete own vehicle | POST | redirect | delete, `log_activity` |

### `accounts/urls.py` (`app_name="accounts"`)
- Session: `login/` (LoginView + LoginForm), `logout/` (LogoutView, POST).
- Registration: `register/`, `register/admin/`.
- Profile/vehicles: `profile/`, `vehicles/`, `vehicles/add/`, `vehicles/<pk>/edit/`, `vehicles/<pk>/delete/`.
- Password change: `password/change/`, `.../done/` (built-in views).
- **Password reset (one-time email token):** `password/reset/` (PasswordResetView + custom email templates), `.../done/`, `.../<uidb64>/<token>/` (confirm), `.../complete/`.

### `accounts/admin.py`
- `CustomUserAdmin` (adds "Parking profile" fieldset, role filters), `VehicleAdmin`.

---

## 5. Parking app — `parking/`

### `parking/models.py`
- **`SlotStatus(TextChoices)`** ✅ — `AVAILABLE, MAINTENANCE` (physical state; occupancy derived from reservations).
- **`Floor(models.Model)`** ✅ — `name, code`(unique), `sort_order`, `is_active`, **`image`** (static-relative photo path, blank). Ordered by sort_order.
- **`Slot(models.Model)`** ✅
  - Fields: `floor`(FK CASCADE, related `slots`), `code`, `slot_type`(VehicleType), `status`(SlotStatus), `created_at`.
  - Constraint: unique `(floor, code)`.
  - Props/methods: `is_open` (status==AVAILABLE), `status_badge` ("available"/"maintenance"), `accommodates(vehicle_type)`.

### `parking/services.py`  (availability engine)
- **`build_window(date=None, start_time=None, end_time=None) -> (start, end)`** ✅ — combines into aware datetimes; returns `(None, None)` if incomplete or `end<=start`. Depends on `timezone`.
- **`blocked_slot_ids(start, end) -> set[int]`** ✅ — slot ids with an active (`RESERVED|OCCUPIED`) reservation overlapping `[start,end)`. **Lazy** `apps.get_model("reservations","Reservation")`; returns `set()` if model absent (pre-Phase 3). Overlap rule: `start_at < end AND end_at > start`.
- **`query_slots(floor=None, vehicle_type=None) -> QuerySet`** ✅ — active-floor slots, optional floor/type filter, `select_related("floor")`.
- **`slots_with_availability(*, floor, vehicle_type, only_available, start, end) -> (list[Slot], dict)`** ✅
  - Behavior: annotates each slot with `.available = is_open AND id not in blocked`; optionally drops unavailable; returns `(slots, {total, available, maintenance})`.
- **`active_floors() -> QuerySet`** ✅.
- **`facility_floors() -> list[dict]`** ✅ — per active floor `{floor, total, available, occupied, maintenance}` using live occupancy (reservation covering `now`); powers the public Facility Guide.

### `parking/forms.py`
- **`SlotFilterForm(Form)`** ✅ — fields `floor, vehicle_type, availability, date, start_time, end_time` (all optional; HTML5 date/time widgets).
- **`FloorForm(ModelForm)`**, **`SlotForm(ModelForm)`** (`clean_code` → upper).

### `parking/views.py`
- **`_resolve_filters(request) -> (form, filters_dict)`** ✅ — parses `SlotFilterForm` from GET into `{floor, vehicle_type, only_available, start, end}`.
- Public:
  - **`facility(request)`** ✅ — Facility Guide `parking/facility.html`: floor cards with photos + live availability, link to slots filtered by floor. Repurposes the legacy static gallery + p1–p4 pages.
- Customer (public):
  - **`slots(request)`** ✅ — full page `parking/slots.html` (filter bar + grid + poll script).
  - **`slots_partial(request)`** ✅ — renders only `parking/_slot_grid.html` (polled every 10s / on filter change).
  - **`slots_api(request)`** ✅ — `JsonResponse{summary, slots[]}` (machine-readable snapshot).
- Admin (`@admin_required`):
  - **`floor_list/add/edit`** ✅ — Floor CRUD.
  - **`slot_list(request)`** ✅ — table, optional `?floor=` filter.
  - **`slot_add/edit`** ✅ — Slot CRUD.
  - **`slot_toggle(request, pk)`** ✅ `@require_POST` — flips AVAILABLE↔MAINTENANCE, `log_activity`, redirect back to referer.

### `parking/urls.py` (`app_name="parking"`)
- `facility/`, `slots/`, `slots/grid/`, `api/slots/`, `manage/floors[/add|/<pk>/edit]`, `manage/slots[/add|/<pk>/edit|/<pk>/toggle]`.

### `parking/management/commands/seed_parking.py`
- **`Command.handle`** ✅ — Purpose: idempotent demo seed (**4 floors, 63 slots**, each floor with a repurposed area photo) via `get_or_create`; refreshes name/order/image each run. Side effect: DB inserts.

---

## 5B. Reservations app — `reservations/`

### `reservations/utils.py`
- **`make_reservation_code() -> str`** ✅ — `"PUP-" + 6 hex` (upper). Uses `secrets`.
- **`sign_reservation(reservation) -> str`** ✅ — `signing.dumps({id, code}, salt=QR_SALT)`; tamper-proof token embedded in the QR.
- **`unsign_token(token, max_age=None) -> dict|None`** ✅ — reverses signing; returns `None` on `BadSignature`/expiry.
- **`qr_png_bytes(data) -> bytes`** ✅ — renders `data` to PNG via `qrcode`+Pillow.
- **`verification_url(reservation) -> str`** ✅ — absolute `SITE_BASE_URL + reservations:verify?t=<token>` (QR contents).

### `reservations/models.py`
- **`ReservationStatus(TextChoices)`** ✅ — `RESERVED, OCCUPIED, COMPLETED, CANCELLED`. `ACTIVE_STATUSES=(RESERVED,OCCUPIED)` (block overlaps).
- **`Reservation(models.Model)`** ✅
  - Fields: `customer`(FK User CASCADE), `slot`(FK Slot **PROTECT**), `vehicle`(FK Vehicle SET_NULL), `start_at`, `end_at`, `status`, `code`(unique, non-editable), `fee_cents`, `created_at`, `updated_at`. Index on `(slot,status,start_at,end_at)`.
  - `save()` side effects: assigns unique `code` (5 retries) + default `fee_cents` from `settings.RESERVATION_FEE_CENTS` on first save.
  - Props: `is_active`, `is_cancellable` (RESERVED & future), `is_modifiable`, `fee_display` (₱), `qr_token`, `status_badge`.
  - **`overlapping(slot, start, end, exclude_pk=None) -> QuerySet`** (static): active reservations overlapping `[start,end)`. Rule `start_at<end AND end_at>start`. Powers both form validation and `parking.services.blocked_slot_ids`.

### `reservations/forms.py`
- **`ReservationForm(forms.Form)`** ✅ — Inputs: `vehicle` (limited to `user.vehicles`), `date`, `start_time`, `end_time`; init kwargs `slot,user,exclude_pk`.
  - Behavior/`clean`: builds aware window via `build_window`; rejects past start, duration <15min or >24h, slot under maintenance, and any overlapping active reservation (excludes own pk on modify). Emits `start_at`/`end_at` in cleaned_data.

### `reservations/views.py`
| Function | Guard | Purpose | Side effects |
|---|---|---|---|
| `create(request, slot_id)` | `@customer_required` | book a slot (prefills times from GET) | create Reservation(RESERVED), `log_activity`, redirect detail |
| `detail(request, pk)` | owner/admin (else 403) | show booking + QR | — |
| `history(request)` | `@customer_required` | list own reservations | — |
| `modify(request, pk)` | `@customer_required`, owner | edit window/vehicle (if modifiable) | update, `log_activity` |
| `cancel(request, pk)` | `@customer_required` `@require_POST`, owner | cancel (if cancellable) | status=CANCELLED, `log_activity` |
| `qr(request, pk)` | owner/admin (else 403) | PNG of verification QR | returns `image/png` |
| `verify(request)` | `@admin_required` | validate token, mark arrival | status RESERVED→OCCUPIED, `log_activity` |

- Helper `_owner_or_admin(request, reservation) -> bool`.

### `reservations/urls.py` (`app_name="reservations"`)
- `book/<slot_id>/`, `history/`, `verify/`, `<pk>/`, `<pk>/modify/`, `<pk>/cancel/`, `<pk>/qr/`.

### Integration with `parking`
- `parking.views.slots`/`slots_partial` now pass `can_reserve` (auth customer) + `reserve_query` (carries filter date/time). `_slot_grid.html` renders a **Reserve** button → `reservations:create` for available slots.
- `parking.services.blocked_slot_ids` (lazy `apps.get_model`) now resolves live `Reservation` overlaps → availability is window-aware.

---

## 5C. Payments app — `payments/`

### `payments/models.py`
- **`PaymentStatus(TextChoices)`** ✅ — `PENDING, PAID, FAILED`.
- **`Payment(models.Model)`** ✅ — OneToOne→Reservation (`related_name="payment"`). Fields: `amount_cents`, `currency`(PHP), `status`, `method`(gcash/paymaya/card), `provider`, `checkout_session_id`, `payment_intent_id`, `reference`, `paid_at`. Props: `amount_display`(₱), `is_paid`.
- **`BillingRecord(models.Model)`** ✅ — receipt line: `customer`, `reservation`(SET_NULL), `payment`(SET_NULL), `amount_cents`, `description`, `reference`, `issued_at`. Prop `amount_display`.

### `payments/gateway.py` (PayMongo REST)
- **`is_configured() -> bool`** ✅ — True when `PAYMONGO_SECRET_KEY` set; else app runs in **simulation** mode.
- **`create_checkout_session(payment, success_url, cancel_url) -> (id, url)`** ✅ — POST `/checkout_sessions` (methods gcash/paymaya/card); Basic auth; raises `PayMongoError`.
- **`verify_webhook_signature(request) -> bool`** ✅ — HMAC-SHA256 of `t.body` vs `Paymongo-Signature` (`te`/`li`); returns True if no secret configured (dev).

### `payments/services.py`  (all idempotent)
- **`get_or_create_payment(reservation) -> Payment`** ✅ — PENDING payment; amount/reference from reservation.
- **`mark_paid(payment, *, method, intent_id, session_id, when, request) -> Payment`** ✅ — Behavior: no-op if already PAID; sets PAID+paid_at; **creates one BillingRecord** (guarded); **sends confirmation email**; `log_activity("payment.paid")`.
- **`mark_failed(payment, *, request)`** ✅ — sets FAILED (never downgrades PAID); logs.
- **`send_confirmation_email(reservation, payment)`** ✅ — renders `payments/email/confirmation.txt`; `send_mail(fail_silently=True)`.

### `payments/views.py`
| Function | Guard | Purpose | Side effects |
|---|---|---|---|
| `start(reservation_id)` | `@customer_required`, owner | begin payment | get_or_create_payment; real→checkout redirect; dev→simulate redirect |
| `simulate(pk)` | `@customer_required`, owner, dev-only | stand-in gateway | POST success→`mark_paid`; fail→`mark_failed` |
| `gateway_return()` | `@customer_required` | post-checkout landing | redirect receipt (paid) / detail |
| `webhook()` | `@csrf_exempt @require_POST` | PayMongo events (source of truth) | verify sig; `payment.paid`→mark_paid; `payment.failed`→mark_failed; 200 |
| `receipt(pk)` | owner/admin, paid-only | e-receipt | — |
| `history()` | `@customer_required` | list own payments | — |

- Helpers: `_abs_url(path)`, `_extract_method(checkout_attrs)`.

### `payments/urls.py` (`app_name="payments"`)
- `start/<reservation_id>/`, `simulate/<pk>/`, `return/`, `webhook/`, `receipt/<pk>/`, `history/`.

### Flow integration
- Reservation `detail` view now passes `payment` (reverse OneToOne, caught via `ObjectDoesNotExist`). Template **gates the QR behind `payment.is_paid`**; otherwise shows a **Pay now** CTA → `payments:start`.
- **Simulation mode** (no keys): full book→pay→receipt→email→QR flow works locally; swap to real PayMongo by setting `PAYMONGO_SECRET_KEY`/`PAYMONGO_WEBHOOK_SECRET`.

---

## 5D. Dashboard app — `dashboard/` (admin only)

### `dashboard/services.py` (read-only aggregations)
- **`slot_stats() -> dict`** ✅ — `{total, maintenance, occupied_now, available_now}` (available = total − maintenance − occupied).
- **`reservation_stats() -> dict`** ✅ — zero-filled `{STATUS: count}` for all reservation statuses.
- **`payment_stats() -> dict`** ✅ — `{by_status:{...}, revenue_cents}` (revenue = Σ amount of PAID).
- **`floor_breakdown() -> list`** ✅ — per-floor `{floor, total, maintenance, usable}`.
- **`monitor_slots(floor, vehicle_type) -> list[Slot]`** ✅ — each slot annotated `monitor_status` ∈ {maintenance, occupied, reserved, available} (precedence in that order; occupied/reserved = active reservation covering `now`).
- **`recent_activity(limit=15)`**, **`dashboard_overview()`** ✅ — bundle for home/reports.

### `dashboard/views.py` (all `@admin_required`)
| Function | Purpose | Side effects |
|---|---|---|
| `home` | KPI overview + recent activity | — |
| `monitor` / `monitor_partial` | live slot monitor + 10s-polled fragment | — |
| `reservations_manager` | filter by status/floor | — |
| `reservation_update_status(pk)` (`@require_POST`) | admin status override | set status, `log_activity` |
| `billing` | gateway transactions + billing records, filter by payment status | — |
| `reports` | slots-by-floor, reservation/payment totals, revenue, activity | — |

### `dashboard/urls.py` (`app_name="dashboard"`)
- `""`(home), `monitor/`, `monitor/grid/`, `reservations/`, `reservations/<pk>/status/`, `billing/`, `reports/`.
- `core.home` routes admins here; base-nav "Dashboard" link added for admins.

---

## 6. Data Model Summary

| Model | Key fields | Relations |
|---|---|---|
| `accounts.User` | role, email(unique), name/contact/address | 1—* Vehicle, 1—* ActivityLog |
| `accounts.Vehicle` | plate_number, vehicle_type | *—1 User |
| `parking.Floor` | name, code(unique), is_active, image | 1—* Slot |
| `parking.Slot` | code, slot_type, status | *—1 Floor; 1—* Reservation (PROTECT) |
| `reservations.Reservation` | code(unique), start_at, end_at, status, fee_cents | *—1 User, *—1 Slot, *—1 Vehicle; 1—1 Payment |
| `payments.Payment` | amount_cents, status, method, session/intent ids | 1—1 Reservation; 1—* BillingRecord |
| `payments.BillingRecord` | amount_cents, description, reference, issued_at | *—1 User, *—1 Reservation, *—1 Payment |
| `core.ActivityLog` | action, description, ip, created_at | *—1 User (nullable) |

Migrations applied: `accounts.0001`, `core.0001`, `parking.0001`, `parking.0002_floor_image`, `reservations.0001`, `payments.0001`.

---

## 7. Frontend Assets

- **`templates/base.html`** — shell: PUP-maroon topbar, role-aware nav (incl. Facility), messages, footer. Blocks: `title, head_extra, nav_links, content, body_extra`.
- **`templates/partials/form_fields.html`** — uniform form renderer (labels, help, errors).
- **`templates/404.html`** — themed "wrong turn" page with the **parking-signal** animation (served by Django when `DEBUG=False`).
- **`static/css/main.css`** — PUP palette (maroon + gold), components: buttons, cards, tables, badges, filter-bar, slot-grid, facility cards, hero-photo overlay, avatar, parking-signal, stat tiles. Responsive (grid/flex, mobile-first).
- **`static/js/parking-signal.js`** — dependency-free red/amber/green signal animation (drives `.parking-signal`); used on the 404 page.
- **Real-time mechanism:** vanilla JS in `slots.html`/`dashboard/monitor.html` — `fetch(partial + querystring)` on 10s interval + on filter change; server-rendered fallback works without JS. No external JS/CDN dependency.

### Repurposed legacy assets (`static/img/`)
The original 2020 static site's assets were salvaged, renamed, and wired in:

| Source (deleted) | Now | Used by |
|---|---|---|
| `css/body.jfif` (garage photo) | `static/img/hero-parking.jpg` | landing hero background |
| `images/p1–p4.jfif` | `static/img/areas/area-1…4.jpg` | `Floor.image`, Facility Guide, seed |
| `images/profile.png` | `static/img/default-avatar.png` | profile page avatar |
| Sign In/Up traffic-light JS+CSS | `static/js/parking-signal.js` + CSS | 404 page |
| landing gallery + p1–p4 pages | `templates/parking/facility.html` | Facility Guide |

Dropped (no functional purpose): `images/SM.png` (third-party SM trademark),
`images/bkg_06.jpg` (blank), `css/Sign Up.css` (empty), Eclipse `.project`/`.settings`.

---

## 8. QA / Test Status

- **`manage.py check`:** 0 issues. **`makemigrations --check`:** no changes pending.
- **`manage.py check --deploy`:** 0 issues under `DEBUG=False` + strong `SECRET_KEY` (SSL redirect, secure cookies, HSTS+preload, nosniff).
- **`manage.py test`:** 49 tests passing.
  - `accounts.tests` (6): PBKDF2 hashing, admin role/staff, no self-assign ADMIN, reset email, vehicle add.
  - `parking.tests` (13): availability/maintenance/filters, page/partial/api render, admin toggle, 403 gate, **facility_floors counts, facility page render+photo, seed 4 floors w/ photos, custom 404 uses parking-signal**.
  - `reservations.tests` (13): code/fee, signed-token round-trip + tamper, availability blocking, overlap, book, double-booking rejected, cancel, detail/history render (gated Pay CTA), staff verify→occupied, verify render, owner-only QR, **cross-user detail 403 / cancel 404**.
  - `payments.tests` (9): fee/reference, mark_paid billing+email once (idempotent), simulate start/success/fail, QR hidden→shown after pay, webhook paid idempotent, unknown-reference ignored, **cross-user receipt 403**.
  - `dashboard.tests` (8): slot/payment stats, monitor status precedence, customer denied (403), all admin pages render, reports revenue, admin status override, customer cannot override.
- **Live integration verified:** (0–2) slots API `{total:47, available:47}`, filters, 302 gate; (5) real HTTP admin login → all 6 dashboard pages 200, anon dashboard → 302; (assets) home + facility 200, all 5 migrated static assets 200, facility shows 4 area photos + live availability.

---

## 9. Phase Status

- ✅ **Phase 0–2** — scaffold, accounts/auth, parking + real-time slots.
- ✅ **Phase 3 — Reservations + QR** — booking, overlap validation, unique codes, signed QR PNG, staff verification, history/modify/cancel. `blocked_slot_ids` now live.
- ✅ **Phase 4 — Payments + billing + email** — PayMongo checkout + webhook (simulation fallback when unkeyed), `Payment`/`BillingRecord`, e-receipts, confirmation emails, QR gated behind payment.
- ✅ **Phase 5 — Dashboard + reports** — admin overview KPIs, live monitor (10s poll), reservation manager (status overrides), billing/payment management, reports, recent activity.
- ✅ **Phase 6 — Evaluation & hardening** — cross-user access-control tests, `check --deploy` clean in prod mode, `README.md`, and `docs/ISO-IEC-25010-evaluation.md` mapping features+evidence to the five named quality characteristics.

**All six phases complete.** 45 tests passing; system + deploy checks clean.
