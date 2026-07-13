# AI Documentation Notes

## Document Contract

- **Purpose:** Provide the current machine-readable technical reference for the PUP Online Parking Reservation system.
- **Inputs:** Production Python modules, migrations, templates, configuration, CI workflow, and the QA run completed on 2026-07-13.
- **Outputs:** Module/function inventory, data/control flow, dependencies, side effects, constraints, and verified quality status.
- **Dependencies:** Repository checkout at the time of the documented QA run.
- **Behavior:** Every component uses the literal field labels `Purpose`, `Inputs`, `Outputs`, `Dependencies`, and `Behavior`; obsolete phase notes are intentionally excluded.

## System Architecture

### Modular monolith

- **Purpose:** Deliver public, customer, payment, and administrator workflows in one Django deployment.
- **Inputs:** HTTP requests, environment configuration, database state, PayMongo events, scheduled lifecycle invocations.
- **Outputs:** HTML/JSON/PNG responses, database mutations, audit records, email attempts, external checkout sessions.
- **Dependencies:** Django 6.0.7, SQLite/MySQL, PyMySQL, django-environ, requests, qrcode/Pillow, WhiteNoise.
- **Behavior:** URL router -> auth/role decorator -> view/form -> transactional service -> ORM -> post-commit side effects. Apps are `core`, `accounts`, `parking`, `reservations`, `payments`, and `dashboard`.

### Database and concurrency policy

- **Purpose:** Preserve booking and financial integrity under concurrent requests.
- **Inputs:** Reservation/payment writes and lifecycle/admin/webhook transitions.
- **Outputs:** Serialized mutable-resource decisions and database-enforced invariants.
- **Dependencies:** Django transactions; deployment MySQL row locks; model constraints.
- **Behavior:** Booking/modification locks Slot and Vehicle and repeats overlap checks; reservation/payment writers use Reservation -> Payment lock order. MySQL supplies the deployment `SELECT ... FOR UPDATE` guarantee. SQLite is used for local/hermetic testing and does not provide equivalent row-level serialization. Constraints enforce positive reservation windows, owner/plate uniqueness, floor/slot-code uniqueness, one Payment per Reservation, one canonical BillingRecord per Payment, and one record per PayMongo event ID.

### Reservation state graph

- **Purpose:** Prevent backward or arbitrary reservation state mutation.
- **Inputs:** Current status and requested status.
- **Outputs:** Allowed transition or `ReservationTransitionError`.
- **Dependencies:** `reservations.services.ALLOWED_TRANSITIONS`.
- **Behavior:** `RESERVED -> OCCUPIED|CANCELLED`; `OCCUPIED -> COMPLETED`; `COMPLETED` and `CANCELLED` are terminal. Check-in additionally requires a paid reservation within the arrival window.

### Payment state policy

- **Purpose:** Reconcile a single reservation fee without losing completed financial state.
- **Inputs:** Pending/failed/paid payment, checkout response, webhook delivery, administrator reconciliation.
- **Outputs:** `PENDING`, `FAILED`, or `PAID` state; provider metadata; BillingRecord; audit and notification attempt.
- **Dependencies:** `payments.services`, `payments.gateway`, `PayMongoWebhookEvent`.
- **Behavior:** A paid payment cannot be downgraded. Each pending checkout attempt has a stable UUID idempotency key; a confirmed failed attempt rotates the key. Signed provider events are freshness/mode checked, deduplicated, and matched exactly by session/reference/amount/currency before mutation.

## End-to-End Control Flows

### Booking flow

- **Purpose:** Create one valid reservation and its payment atomically.
- **Inputs:** Authenticated customer, slot ID, owned vehicle ID, start/end datetimes.
- **Outputs:** `Reservation(RESERVED)`, `Payment(PENDING)`, activity record, post-commit creation email attempt.
- **Dependencies:** `ReservationForm`, `create_reservation`, Slot/Vehicle/Reservation/Payment models.
- **Behavior:** Form validates UX rules; service locks resources, repeats active-floor/maintenance/ownership/type/overlap checks, inserts both domain rows, audits, and schedules email after commit.

### Checkout and webhook flow

- **Purpose:** Open one payable checkout attempt and reconcile authoritative provider state.
- **Inputs:** CSRF-protected customer POST; PayMongo signed webhook.
- **Outputs:** Simulator/hosted-checkout redirect; paid payment; canonical receipt; provider-event record.
- **Dependencies:** `payments.views.start`, `create_checkout_session`, `payments.views.webhook`, `mark_paid`.
- **Behavior:** Repeated pending POSTs reuse one idempotency key. Browser return is informational. Webhook HMAC must match configured test/live mode and be fresh; event ID is unique; checkout session, reference, amount, currency, and paid attempt must match locally.

### QR arrival flow

- **Purpose:** Admit a paid customer only during the reservation window.
- **Inputs:** Signed QR token and administrator request.
- **Outputs:** `RESERVED -> OCCUPIED`, verification activity, or literal rejection reason.
- **Dependencies:** `sign_reservation`, `unsign_token`, `check_in_error`, `transition_reservation`.
- **Behavior:** QR download requires owner/admin plus paid active reservation. Verification rejects tampering, unpaid state, wrong status, early arrival outside grace, and expired windows.

### Lifecycle flow

- **Purpose:** Reconcile time-driven states without a user request.
- **Inputs:** Scheduler timestamp, payment grace, optional dry-run.
- **Outputs:** Completed/cancelled counts, status updates, audit rows, cancellation email attempts.
- **Dependencies:** `process_reservations` command and `process_reservation_lifecycle`.
- **Behavior:** Ended OCCUPIED -> COMPLETED; ended RESERVED -> CANCELLED; stale future unpaid RESERVED -> CANCELLED. Conditional updates avoid overwriting concurrent changes. Command is idempotent and should run every minute.

### Paid cancellation flow

- **Purpose:** Preserve visibility when cancellation occurs after payment.
- **Inputs:** Paid reservation cancellation through central transition service.
- **Outputs:** Cancelled status, `reservation.refund_review_required` audit event, cancellation notice.
- **Dependencies:** `transition_reservation`, `send_cancellation_email`, ActivityLog.
- **Behavior:** The application does not issue PayMongo refunds automatically; administrators use the audit marker for the manual refund workflow.

## Configuration and Core

### `config/settings.py`

- **Purpose:** Define environment-driven runtime behavior.
- **Inputs:** `.env` and process environment.
- **Outputs:** Django settings for database, auth, email, payment, static files, security, logging, and lifecycle policy.
- **Dependencies:** django-environ; WhiteNoise; PyMySQL shim in `config.__init__`.
- **Behavior:** Defaults to local SQLite/debug. MySQL enables utf8mb4/strict mode. Production enables HTTPS redirect, secure cookies, HSTS, nosniff, proxy SSL handling, and compressed-manifest static storage. Admin signup and simulator default off.

### `config/settings_test.py`

- **Purpose:** Isolate automated tests from developer/deployment services and data.
- **Inputs:** Base settings.
- **Outputs:** In-memory SQLite, locmem email/cache, plain static storage, test-only simulator, null logging.
- **Dependencies:** `config.settings`.
- **Behavior:** Sets code-owned `TESTING=True`; never uses the tracked SQLite file, SMTP, MySQL, external cache, or real PayMongo.

### `config.checks._looks_like_placeholder(value) -> bool`

- **Purpose:** Detect copied example markers in deployment secrets.
- **Inputs:** String setting value.
- **Outputs:** Boolean.
- **Dependencies:** `UNSAFE_MARKERS`.
- **Behavior:** Normalizes whitespace/case and checks for `change-me`, `example`, or `xxx`.

### `config.checks.check_privileged_configuration(app_configs, **kwargs) -> list[Error]`

- **Purpose:** Fail deployment validation for unsafe privileged/payment/email/link configuration.
- **Inputs:** Current Django settings.
- **Outputs:** Check errors `parking.E001` through `parking.E006`.
- **Dependencies:** Django system-check registry; `urlparse`.
- **Behavior:** E001 validates enabled admin code; E002 rejects deployment simulation; E003 validates PayMongo values/key mode/webhook tolerance; E004 validates enrollment throttle; E005 requires public HTTPS `SITE_BASE_URL`; E006 requires a delivery-capable email backend and positive timeout.

### `config.urls._development_admin_patterns() -> list[URLPattern]`

- **Purpose:** Keep Django's generic model editor out of production.
- **Inputs:** `settings.DEBUG`.
- **Outputs:** Debug-only `django-admin/` pattern or empty list.
- **Dependencies:** Django admin site.
- **Behavior:** Production uses the controlled dashboard/services; debug admin remains an inspection surface with Reservation/Payment/Billing/Webhook records configured view-only.

### `core.constants.VehicleType`

- **Purpose:** Provide shared vehicle/slot type values.
- **Inputs:** None.
- **Outputs:** `MOTORCYCLE`, `CAR`, `SUV`, `VAN`, `TRUCK` choices.
- **Dependencies:** Django `TextChoices`.
- **Behavior:** Used by Vehicle, Slot, filters, and compatibility checks.

### `core.models.ActivityLog`

- **Purpose:** Persist durable audit evidence for meaningful events.
- **Inputs:** Actor, durable actor label, action, description, IP address.
- **Outputs:** Ordered activity row.
- **Dependencies:** Custom User model.
- **Behavior:** Actor deletion uses `SET_NULL`; `actor_label` remains readable; action and timestamp are indexed.

### `core.models.log_activity(action, description="", actor=None, request=None) -> ActivityLog | None`

- **Purpose:** Write non-fatal audit entries from domain paths.
- **Inputs:** Action, optional description/actor/request.
- **Outputs:** ActivityLog or `None`.
- **Dependencies:** ActivityLog model; middleware-populated `request.client_ip`; logger.
- **Behavior:** Derives authenticated actor, truncates database-bound values, inserts row, and logs/suppresses database exceptions so audit failure does not break the domain request.

### `core.middleware.ActivityLogMiddleware.__call__(request) -> HttpResponse`

- **Purpose:** Attach a client IP for downstream auditing.
- **Inputs:** HttpRequest.
- **Outputs:** Downstream HttpResponse.
- **Dependencies:** `_client_ip`, next middleware/view.
- **Behavior:** Stores first forwarded address or remote address on `request.client_ip`.

### `core.middleware.ActivityLogMiddleware._client_ip(request) -> str | None`

- **Purpose:** Resolve the audit source address.
- **Inputs:** Request metadata.
- **Outputs:** First `X-Forwarded-For` value, `REMOTE_ADDR`, or `None`.
- **Dependencies:** Trusted proxy deployment configuration.
- **Behavior:** Splits a forwarded list on comma and trims the first item.

### `core.context_processors.site(request) -> dict`

- **Purpose:** Expose branding to every template.
- **Inputs:** Request.
- **Outputs:** `site_name` and `site_short_name` context.
- **Dependencies:** Django settings.
- **Behavior:** Read-only.

### `core.views.home(request) -> HttpResponse`

- **Purpose:** Serve the public landing page or dispatch authenticated roles.
- **Inputs:** Request/user.
- **Outputs:** Landing render or redirect.
- **Dependencies:** Dashboard and parking URL namespaces.
- **Behavior:** Admin/staff -> dashboard; customer -> slots; anonymous -> public home; URL-reversal failure falls back to the page.

## Accounts Module

### `accounts.models.CustomUserManager.create_superuser(username, email=None, password=None, **extra) -> User`

- **Purpose:** Keep Django-created superusers aligned with application roles.
- **Inputs:** Standard user credentials/extra fields.
- **Outputs:** Persisted superuser.
- **Dependencies:** Django UserManager; `Roles.ADMIN`.
- **Behavior:** Defaults role to ADMIN, then delegates normal superuser validation/persistence.

### `accounts.models.User`

- **Purpose:** Represent students, employees, visitors, and administrators in one auth table.
- **Inputs:** Django auth fields plus role, names, ID number, contact, address, unique email.
- **Outputs:** Authenticated actor with role properties.
- **Dependencies:** AbstractUser; CustomUserManager.
- **Behavior:** `is_admin_role` accepts ADMIN or staff; `is_customer_role` accepts customer roles; `get_full_name` joins non-empty first/middle/last; string output prefers full name.

### `accounts.models.Vehicle`

- **Purpose:** Represent a customer-owned vehicle used in booking compatibility checks.
- **Inputs:** Owner, plate, vehicle type, optional descriptive fields.
- **Outputs:** Vehicle row/label.
- **Dependencies:** User; VehicleType.
- **Behavior:** Owner+plate is unique; owner deletion cascades; label includes make/model when available.

### `accounts.forms._style(fields) -> None`

- **Purpose:** Apply shared CSS to form widgets.
- **Inputs:** Django field mapping.
- **Outputs:** None; mutates widget attributes.
- **Dependencies:** Django forms.
- **Behavior:** Appends `form-input` without discarding existing classes.

### `accounts.forms.CustomerRegistrationForm.clean_role() -> str`

- **Purpose:** Prevent public self-assignment of ADMIN.
- **Inputs:** Submitted role.
- **Outputs:** Valid customer role.
- **Dependencies:** `CUSTOMER_ROLES`.
- **Behavior:** Raises form validation error for any non-customer role.

### `accounts.forms.AdminRegistrationForm.clean_access_code() -> str`

- **Purpose:** Validate the temporary administrator enrollment secret.
- **Inputs:** Submitted access code and configured server code.
- **Outputs:** Accepted code.
- **Dependencies:** `secrets.compare_digest`; settings.
- **Behavior:** Fails closed when server code is empty and uses constant-time comparison.

### `accounts.forms.AdminRegistrationForm.save(commit=True) -> User`

- **Purpose:** Create a privileged user only through the gated form.
- **Inputs:** Validated registration form.
- **Outputs:** ADMIN/staff User.
- **Dependencies:** Django UserCreationForm.
- **Behavior:** Forces role and staff flag before optional persistence.

### `accounts.forms.VehicleForm.clean_plate_number() -> str`

- **Purpose:** Normalize plate identity before uniqueness validation/persistence.
- **Inputs:** Submitted plate.
- **Outputs:** Trimmed uppercase plate.
- **Dependencies:** Vehicle model form.
- **Behavior:** Deterministic normalization.

### `accounts.decorators._require(test, request, view, args, kwargs) -> HttpResponse`

- **Purpose:** Apply a role predicate to a view.
- **Inputs:** Predicate, request, target, arguments.
- **Outputs:** Login redirect, 403 exception, or target response.
- **Dependencies:** Django auth redirect and PermissionDenied.
- **Behavior:** Anonymous users redirect to login; authenticated predicate failures raise 403.

### `accounts.decorators.admin_required(view) -> callable`

- **Purpose:** Restrict dashboard/management views to administrators.
- **Inputs:** View callable.
- **Outputs:** Wrapped callable.
- **Dependencies:** `_require`, `User.is_admin_role`.
- **Behavior:** Preserves wrapped metadata and enforces the admin predicate per request.

### `accounts.decorators.customer_required(view) -> callable`

- **Purpose:** Restrict booking/profile vehicle flows to customer roles.
- **Inputs:** View callable.
- **Outputs:** Wrapped callable.
- **Dependencies:** User role properties; core dispatcher.
- **Behavior:** Anonymous -> login; admin -> role workspace; invalid role -> 403; customer -> view.

### `accounts.views.register_customer(request) -> HttpResponse`

- **Purpose:** Self-register and sign in a customer.
- **Inputs:** GET or registration POST.
- **Outputs:** Form render or home redirect.
- **Dependencies:** CustomerRegistrationForm, Django login, ActivityLog.
- **Behavior:** Creates only customer roles and emits `user.registered`.

### `accounts.views.register_admin(request) -> HttpResponse`

- **Purpose:** Support temporary, controlled web enrollment of administrators.
- **Inputs:** Enabled feature flag, source IP, GET/POST, access code/profile credentials.
- **Outputs:** 404, form/429 response, or authenticated admin redirect.
- **Dependencies:** AdminRegistrationForm, ActivityLog, throttle settings.
- **Behavior:** Disabled endpoint returns 404. Incorrect code attempts are persisted by IP; configured attempt/window limits return 429. Credentials/codes are never written to audit text.

### `accounts.views.profile(request) -> HttpResponse`

- **Purpose:** Read/update the authenticated profile.
- **Inputs:** Authenticated GET/POST.
- **Outputs:** Form render or redirect.
- **Dependencies:** ProfileForm, ActivityLog.
- **Behavior:** Valid update emits `profile.updated`.

### `accounts.views.vehicle_list|vehicle_add|vehicle_edit|vehicle_delete(request, pk?) -> HttpResponse`

- **Purpose:** Manage vehicles owned by the signed-in customer.
- **Inputs:** Customer request, optional owned vehicle PK/form payload.
- **Outputs:** List/form/confirmation render or redirect.
- **Dependencies:** customer_required, VehicleForm, owner-scoped ORM queries.
- **Behavior:** Cross-owner IDs return 404; add/remove operations are audited; delete requires POST confirmation.

## Parking Module

### `parking.models.Floor`

- **Purpose:** Represent a named parking level/area.
- **Inputs:** Name, unique code, order, active flag, optional image path.
- **Outputs:** Ordered facility row.
- **Dependencies:** Slot relation.
- **Behavior:** Inactive floors are excluded from customer availability and new bookings.

### `parking.models.Slot`

- **Purpose:** Represent one typed physical parking space.
- **Inputs:** Floor, code, type, physical status.
- **Outputs:** Slot row with `is_open`, `status_badge`, `accommodates` helpers.
- **Dependencies:** Floor, VehicleType, SlotStatus.
- **Behavior:** Floor+code is unique; `accommodates` requires exact vehicle/slot type; maintenance overrides temporal availability.

### `parking.forms.SlotForm.clean_code() -> str`

- **Purpose:** Normalize staff-entered slot codes.
- **Inputs:** Code string.
- **Outputs:** Trimmed uppercase code.
- **Dependencies:** Slot ModelForm.
- **Behavior:** Runs before uniqueness validation/persistence.

### `parking.services.build_window(date=None, start_time=None, end_time=None) -> tuple[datetime | None, datetime | None]`

- **Purpose:** Construct an aware half-open search window.
- **Inputs:** Optional local date/start/end times.
- **Outputs:** Aware `(start, end)` or `(None, None)`.
- **Dependencies:** Django timezone.
- **Behavior:** Incomplete or non-positive input returns no window.

### `parking.services.blocked_slot_ids(start, end) -> set[int]`

- **Purpose:** Find temporally unavailable slots.
- **Inputs:** Search start/end.
- **Outputs:** Slot ID set.
- **Dependencies:** Lazy Reservation model lookup.
- **Behavior:** Uses active statuses and half-open overlap rule `start_at < end AND end_at > start`; missing/incomplete context returns empty set.

### `parking.services.query_slots(*, floor=None, vehicle_type=None) -> QuerySet[Slot]`

- **Purpose:** Build the active-floor slot base query.
- **Inputs:** Optional floor/type.
- **Outputs:** `select_related("floor")` queryset.
- **Dependencies:** Slot/Floor.
- **Behavior:** Applies provided filters without evaluating the queryset.

### `parking.services.slots_with_availability(...) -> tuple[list[Slot], dict]`

- **Purpose:** Combine physical and temporal availability.
- **Inputs:** Floor/type/available filters and optional time window.
- **Outputs:** Materialized slots with transient `available`; summary counts.
- **Dependencies:** `query_slots`, `blocked_slot_ids`.
- **Behavior:** Maintenance or blocked ID makes a slot unavailable; only-available filtering occurs after annotation.

### `parking.services.active_floors() -> QuerySet[Floor]`

- **Purpose:** Provide active facility choices.
- **Inputs:** None.
- **Outputs:** Ordered active Floor queryset.
- **Dependencies:** Floor model ordering.
- **Behavior:** Read-only.

### `parking.services.facility_floors() -> list[dict]`

- **Purpose:** Produce public per-floor live summary cards.
- **Inputs:** Current timestamp/database state.
- **Outputs:** Floor, total, available, occupied-now, maintenance values.
- **Dependencies:** One-second current window and availability service.
- **Behavior:** Computes current blocking reservations without mutating state.

### `parking.views._resolve_filters(request) -> tuple[SlotFilterForm, dict]`

- **Purpose:** Parse customer slot filters and select a default live window.
- **Inputs:** GET parameters.
- **Outputs:** Bound form and service keyword arguments.
- **Dependencies:** SlotFilterForm, `build_window`.
- **Behavior:** When no complete window is supplied, uses a one-second `now` window so an unfiltered page does not label a currently reserved slot available.

### `parking.views._can_reserve(request) -> bool`

- **Purpose:** Decide whether slot cards may expose a reservation action.
- **Inputs:** Request user.
- **Outputs:** Boolean.
- **Dependencies:** User authentication and `is_customer_role`.
- **Behavior:** Anonymous and administrator users cannot receive customer booking controls.

### `parking.views.facility|slots|slots_partial|slots_api(request) -> HttpResponse`

- **Purpose:** Serve public facility, full availability, polling fragment, and JSON snapshot interfaces.
- **Inputs:** Request/GET filters.
- **Outputs:** HTML or JSON.
- **Dependencies:** Parking services and role-aware reserve capability.
- **Behavior:** Read-only; fragment/API share the same availability semantics as the full page.

### `parking.views.floor_list|floor_add|floor_edit|slot_list|slot_add|slot_edit(request, pk?) -> HttpResponse`

- **Purpose:** Provide controlled administrator inventory management.
- **Inputs:** Admin request, filters, model form data.
- **Outputs:** Management page/form/redirect.
- **Dependencies:** admin_required, FloorForm, SlotForm.
- **Behavior:** Valid mutations persist inventory and produce user feedback.

### `parking.views.slot_toggle(request, pk) -> HttpResponse`

- **Purpose:** Change a slot's physical availability.
- **Inputs:** Admin POST and slot PK.
- **Outputs:** Redirect.
- **Dependencies:** SlotStatus, ActivityLog.
- **Behavior:** Toggles AVAILABLE/MAINTENANCE and emits `slot.status_changed`.

### `parking.management.commands.seed_parking.Command.handle(*args, **options) -> None`

- **Purpose:** Idempotently seed/update the documented facility plan.
- **Inputs:** Current Floor/Slot rows.
- **Outputs:** Four configured floors, missing typed slots, summary text.
- **Dependencies:** Floor/Slot models and static image paths.
- **Behavior:** Uses update/get-or-create patterns; reruns do not duplicate slots.

## Reservations Module

### `reservations.models.Reservation`

- **Purpose:** Store one customer's slot entitlement for a positive time window.
- **Inputs:** Customer, slot, optional vehicle, start/end, status, fee snapshot.
- **Outputs:** Unique reservation code and helper properties.
- **Dependencies:** User, Slot, Vehicle, signing utilities, fee setting.
- **Behavior:** Slot deletion is protected; vehicle deletion sets null; initial save creates a collision-checked code and fee snapshot; database constraint requires `end_at > start_at`.

### `reservations.models.Reservation.overlapping(slot, start, end, exclude_pk=None) -> QuerySet[Reservation]`

- **Purpose:** Query active booking conflicts.
- **Inputs:** Slot, half-open window, optional reservation exclusion.
- **Outputs:** Lazy Reservation queryset.
- **Dependencies:** `ACTIVE_STATUSES`.
- **Behavior:** Uses `start_at < end AND end_at > start`; modification excludes its own PK.

### `reservations.forms.ReservationForm.__init__(*args, slot=None, user=None, exclude_pk=None, **kwargs)`

- **Purpose:** Bind booking context and owner-scoped vehicle choices.
- **Inputs:** Standard form data plus slot/user/exclusion.
- **Outputs:** Configured form instance.
- **Dependencies:** Vehicle relation.
- **Behavior:** A customer cannot submit another user's vehicle through the choice field.

### `reservations.forms.ReservationForm.clean() -> dict`

- **Purpose:** Provide immediate booking validation feedback.
- **Inputs:** Vehicle/date/start/end and bound context.
- **Outputs:** Cleaned values plus aware `start_at`/`end_at`.
- **Dependencies:** `build_window`, Reservation overlap query.
- **Behavior:** Rejects incomplete/past/<15-minute/>24-hour windows, inactive floor, maintenance, wrong vehicle type, and overlaps. Service layer remains authoritative under locks.

### `reservations.services._validate_booking_resources(*, slot, vehicle, customer) -> None`

- **Purpose:** Recheck mutable booking resources inside a transaction.
- **Inputs:** Locked slot/vehicle and customer.
- **Outputs:** None or ValidationError.
- **Dependencies:** Floor activity, Slot status/type, Vehicle ownership.
- **Behavior:** Fails closed for inactive floor, maintenance, wrong owner, or type mismatch.

### `reservations.services._lock_vehicle(*, vehicle_id, customer) -> Vehicle`

- **Purpose:** Acquire the owner-scoped vehicle row for booking decisions.
- **Inputs:** Vehicle PK and customer.
- **Outputs:** Locked Vehicle.
- **Dependencies:** `select_for_update`.
- **Behavior:** Missing/cross-owner vehicle becomes a validation error.

### `reservations.services.create_reservation(...) -> Reservation`

- **Purpose:** Atomically create a conflict-free booking/payment pair.
- **Inputs:** Customer, slot/vehicle IDs, aware start/end, optional request.
- **Outputs:** Reservation.
- **Dependencies:** Slot/Vehicle locks, overlap query, Payment model, ActivityLog, notifications.
- **Behavior:** Validates positive window, locks resources, repeats rules/conflict query, inserts Reservation and PENDING Payment, audits, schedules creation email on commit.

### `reservations.services.modify_reservation(...) -> Reservation`

- **Purpose:** Safely modify a future reserved booking.
- **Inputs:** Reservation/customer/vehicle IDs, new window, optional request.
- **Outputs:** Updated Reservation.
- **Dependencies:** Reservation/Slot/Vehicle locks and overlap/resource validation.
- **Behavior:** Owner-only; requires modifiable status/time; excludes current PK from conflict query; audits successful update.

### `reservations.services.payment_for(reservation) -> Payment | None`

- **Purpose:** Resolve optional legacy reverse one-to-one payment safely.
- **Inputs:** Reservation.
- **Outputs:** Payment or None.
- **Dependencies:** Django related-object exception.
- **Behavior:** New service-created reservations always have a payment; None supports legacy data.

### `reservations.services.check_in_error(reservation, *, at=None) -> str`

- **Purpose:** Centralize paid arrival eligibility.
- **Inputs:** Reservation and optional aware timestamp.
- **Outputs:** Empty string or literal rejection reason.
- **Dependencies:** Payment state and arrival-grace setting.
- **Behavior:** Requires RESERVED, paid, not too early, and not ended.

### `reservations.services.transition_reservation(...) -> Reservation`

- **Purpose:** Apply one authorized state transition under a row lock.
- **Inputs:** Reservation ID, target status, actor/request, cancellation flag, time.
- **Outputs:** Updated Reservation or ReservationTransitionError.
- **Dependencies:** ALLOWED_TRANSITIONS, `check_in_error`, notifications, ActivityLog.
- **Behavior:** Enforces graph; customer cancellation must be future RESERVED; paid check-in must be eligible; audits actor; paid cancellation emits refund-review event; cancellation email is post-commit.

### `reservations.lifecycle.LifecycleSummary.total -> int`

- **Purpose:** Aggregate lifecycle action counts.
- **Inputs:** Completed, ended-cancelled, unpaid-cancelled counts.
- **Outputs:** Integer sum.
- **Dependencies:** Frozen dataclass.
- **Behavior:** Read-only derived property.

### `reservations.lifecycle._configured_payment_grace() -> timedelta | None`

- **Purpose:** Parse unpaid-hold expiry configuration.
- **Inputs:** Grace minutes setting.
- **Outputs:** Timedelta or None.
- **Dependencies:** Django settings.
- **Behavior:** Zero disables unpaid expiry; invalid/negative values raise ValueError so scheduled jobs fail visibly.

### `reservations.lifecycle._normalise_at(at) -> datetime`

- **Purpose:** Establish a deterministic aware processing timestamp.
- **Inputs:** Optional datetime.
- **Outputs:** Aware datetime.
- **Dependencies:** Django timezone.
- **Behavior:** Defaults to now; rejects naive explicit values.

### `reservations.lifecycle._transition_ended(...) -> int`

- **Purpose:** Process one ended source-status category.
- **Inputs:** Timestamp, source/target statuses, action, dry-run.
- **Outputs:** Count.
- **Dependencies:** Conditional ORM updates, ActivityLog, notifications.
- **Behavior:** Dry-run only counts. Applied mode locks/conditionally updates without overwriting concurrent state and schedules cancellation email where relevant.

### `reservations.lifecycle._expire_unpaid_holds(...) -> int`

- **Purpose:** Cancel old unpaid future holds.
- **Inputs:** Timestamp, grace, dry-run.
- **Outputs:** Count.
- **Dependencies:** Reservation -> Payment lock order.
- **Behavior:** Requires future RESERVED, age beyond grace, and non-paid Payment; rechecks under locks, cancels, audits, notifies.

### `reservations.lifecycle.process_reservation_lifecycle(...) -> LifecycleSummary`

- **Purpose:** Run all due time-driven transitions.
- **Inputs:** Optional timestamp, dry-run, optional grace override.
- **Outputs:** LifecycleSummary.
- **Dependencies:** Lifecycle helpers.
- **Behavior:** Processes occupied completion, ended reserved cancellation, then unpaid expiry in stable order.

### `reservations.notifications._send_reservation_email(...) -> None`

- **Purpose:** Render/send a reservation message without breaking domain work.
- **Inputs:** Reservation, subject, template, optional context.
- **Outputs:** Best-effort email attempt.
- **Dependencies:** Django template/email and site settings.
- **Behavior:** Skips missing recipient; uses `fail_silently=True`.

### `reservations.notifications.send_reservation_created_email|send_cancellation_email(...) -> None`

- **Purpose:** Supply booking/payment and cancellation/refund guidance.
- **Inputs:** Reservation and cancellation actor label where applicable.
- **Outputs:** Email attempt.
- **Dependencies:** Shared sender and email templates.
- **Behavior:** Cancellation context includes paid/refund-review state.

### `reservations.utils.make_reservation_code() -> str`

- **Purpose:** Generate human-readable reservation identifiers.
- **Inputs:** Cryptographic randomness.
- **Outputs:** `PUP-` plus six uppercase hex characters.
- **Dependencies:** `secrets`.
- **Behavior:** Model save retries collisions before failing.

### `reservations.utils.sign_reservation|unsign_token(token, max_age=None)`

- **Purpose:** Create/verify tamper-evident QR payloads.
- **Inputs:** Reservation or token/optional age.
- **Outputs:** Signed string or verified `{id, code}`/None.
- **Dependencies:** Django signing with reservation-specific salt.
- **Behavior:** Invalid or expired signatures return None rather than raising into views.

### `reservations.utils.qr_png_bytes(data) -> bytes`

- **Purpose:** Render a signed verification URL as PNG.
- **Inputs:** String payload.
- **Outputs:** PNG bytes.
- **Dependencies:** qrcode and Pillow.
- **Behavior:** Generates in memory; no media-file persistence.

### `reservations.utils.verification_url(reservation) -> str`

- **Purpose:** Build the absolute QR target.
- **Inputs:** Reservation.
- **Outputs:** `SITE_BASE_URL` + verify route + signed token.
- **Dependencies:** URL reversing and signing.
- **Behavior:** Deployment check requires a public HTTPS base URL.

### `reservations.views.create|modify|cancel(request, ...) -> HttpResponse`

- **Purpose:** Expose customer booking mutation flows.
- **Inputs:** Owner-scoped customer request and form/PK data.
- **Outputs:** Form/detail redirect and messages.
- **Dependencies:** ReservationForm and transactional reservation services.
- **Behavior:** Views never directly implement overlap/state mutation; conflicts become form/user messages; cancellation requires POST.

### `reservations.views._owner_or_admin(request, reservation) -> bool`

- **Purpose:** Apply detail/QR object access policy.
- **Inputs:** Request and Reservation.
- **Outputs:** Boolean.
- **Dependencies:** Customer foreign key and `is_admin_role`.
- **Behavior:** Accepts the reservation owner or an authenticated application administrator.

### `reservations.views.detail|history(request, pk?) -> HttpResponse`

- **Purpose:** Show owner/admin detail and paginated customer history.
- **Inputs:** Authenticated request and optional PK/page.
- **Outputs:** HTML.
- **Dependencies:** Owner/admin policy; Paginator.
- **Behavior:** History uses 20 rows/page; cross-owner detail raises 403.

### `reservations.views.qr(request, pk) -> HttpResponse`

- **Purpose:** Return a usable arrival QR only for valid entitlement.
- **Inputs:** Owner/admin request and reservation PK.
- **Outputs:** `image/png` or 403.
- **Dependencies:** `payment_for`, `verification_url`, `qr_png_bytes`.
- **Behavior:** Requires active status and paid Payment.

### `reservations.views.verify(request) -> HttpResponse`

- **Purpose:** Let staff inspect and apply QR arrival verification.
- **Inputs:** Admin GET/POST and signed token.
- **Outputs:** Verification page/redirect.
- **Dependencies:** Token utilities and transition service.
- **Behavior:** Valid token must match row code; POST transitions eligible reservation to OCCUPIED and emits `reservation.verified`.

### `reservations.management.commands.process_reservations.Command`

- **Purpose:** Expose lifecycle processing to an external scheduler/operator.
- **Inputs:** `--dry-run`, optional ISO-8601 `--at`.
- **Outputs:** Parseable completed/ended-cancelled/unpaid-cancelled/total counts.
- **Dependencies:** Lifecycle service and Django command framework.
- **Behavior:** Naive `--at` is localized; invalid input/config becomes CommandError; dry-run does not mutate/log/email.

### `reservations.management.commands.process_reservations.Command._parse_at(raw_value) -> datetime`

- **Purpose:** Parse deterministic scheduler/operator timestamps.
- **Inputs:** Optional ISO-8601 string.
- **Outputs:** Aware datetime.
- **Dependencies:** Django `parse_datetime` and current timezone.
- **Behavior:** Missing value returns now; naive values are localized; malformed values raise CommandError.

## Payments Module

### `payments.models.Payment`

- **Purpose:** Store the one gateway fee transaction for a Reservation.
- **Inputs:** Reservation, amount/currency, status, provider identifiers, UUID attempt key, notification timestamps.
- **Outputs:** Payment state and display helpers.
- **Dependencies:** Reservation one-to-one relation.
- **Behavior:** Repeated pending checkout requests reuse the UUID; failed retry rotates it. Notification timestamps reserve at-most-once dispatch attempts and are not proof of SMTP delivery.

### `payments.models.PayMongoWebhookEvent`

- **Purpose:** Provide cross-process event deduplication and financial audit evidence.
- **Inputs:** Unique provider event ID/type/mode, optional Payment, outcome/detail.
- **Outputs:** Immutable provider-delivery record.
- **Dependencies:** Payment foreign key.
- **Behavior:** Unique event ID ensures one financial side-effect transaction per provider event; outcome is PROCESSED, IGNORED, or REJECTED.

### `payments.models.BillingRecord`

- **Purpose:** Preserve the canonical receipt snapshot for a paid Payment.
- **Inputs:** Customer, reservation, payment, amount, description, reference.
- **Outputs:** Ordered billing row.
- **Dependencies:** Payment/User/Reservation relations.
- **Behavior:** Unique Payment constraint prevents duplicate canonical receipts; records are view-only through Django admin.

### `payments.gateway.is_configured() -> bool`

- **Purpose:** Detect real gateway configuration.
- **Inputs:** PayMongo secret key.
- **Outputs:** Boolean.
- **Dependencies:** Settings.
- **Behavior:** Presence alone selects real mode; deploy checks additionally validate prefix/mode.

### `payments.gateway.is_simulation_enabled() -> bool`

- **Purpose:** Restrict payment mutation simulation to deliberate non-production use.
- **Inputs:** DEBUG/TESTING sentinel, simulation flag, gateway-key presence.
- **Outputs:** Boolean.
- **Dependencies:** Settings.
- **Behavior:** True only when debug/test runtime and explicit flag are active and real key is absent.

### `payments.gateway.expected_livemode() -> bool | None`

- **Purpose:** Bind webhook signature/event mode to configured key type.
- **Inputs:** `sk_test_`/`sk_live_` secret or simulator.
- **Outputs:** False/True/None.
- **Dependencies:** `is_simulation_enabled`.
- **Behavior:** Unknown key prefix returns None and webhook verification fails closed.

### `payments.gateway._auth_header() -> dict`

- **Purpose:** Build PayMongo Basic authentication headers.
- **Inputs:** Secret key.
- **Outputs:** Authorization/content-type mapping.
- **Dependencies:** base64.
- **Behavior:** Secret is username with empty password; never logged.

### `payments.gateway.create_checkout_session(payment, success_url, cancel_url) -> tuple[str, str]`

- **Purpose:** Create/retrieve one hosted checkout for the current local attempt.
- **Inputs:** Payment and absolute return/cancel URLs.
- **Outputs:** Provider session ID and checkout URL.
- **Dependencies:** requests, PayMongo REST, payment UUID idempotency key.
- **Behavior:** Sends GCash/Maya/card line item with exact local amount/currency/reference and `Idempotency-Key`; network/schema failures become PayMongoError.

### `payments.gateway.verify_webhook_signature(request) -> bool`

- **Purpose:** Authenticate provider deliveries and limit replay.
- **Inputs:** Raw body, Paymongo-Signature, webhook secret, expected mode, tolerance.
- **Outputs:** Boolean.
- **Dependencies:** HMAC-SHA256, constant-time comparison, system time.
- **Behavior:** Chooses only `te` or `li` for configured mode; requires timestamp within positive tolerance; unsigned requests are accepted only in explicit simulation.

### `payments.services.get_or_create_payment(reservation) -> Payment`

- **Purpose:** Return the one payment and repair legacy missing rows.
- **Inputs:** Reservation.
- **Outputs:** Existing/new PENDING Payment.
- **Dependencies:** Payment one-to-one constraint.
- **Behavior:** New reservations normally receive Payment inside booking transaction.

### `payments.services.prepare_payment(reservation, *, request=None) -> Payment`

- **Purpose:** Validate and lock checkout eligibility.
- **Inputs:** Owner reservation and optional request.
- **Outputs:** Locked-state Payment after transaction.
- **Dependencies:** Reservation -> Payment locks, current time, ActivityLog.
- **Behavior:** Requires unexpired RESERVED. FAILED -> PENDING clears failure marker/provider IDs, rotates UUID, and audits retry; repeated PENDING calls preserve UUID.

### `payments.services._billing_defaults(payment, reservation) -> dict`

- **Purpose:** Build immutable canonical receipt values.
- **Inputs:** Payment and Reservation.
- **Outputs:** BillingRecord defaults mapping.
- **Dependencies:** Customer and slot relations.
- **Behavior:** Snapshots amount/description/reference at payment reconciliation.

### `payments.services.mark_paid(...) -> Payment`

- **Purpose:** Reconcile completed financial state idempotently.
- **Inputs:** Payment; method/intent/session/time; optional explicit actor/request.
- **Outputs:** PAID Payment and canonical BillingRecord.
- **Dependencies:** Reservation -> Payment locks, unique billing constraint, ActivityLog, on-commit email.
- **Behavior:** Never clears existing useful provider IDs; creates/repairs receipt; reserves confirmation notification once; attributes manual actions to admin; cancelled reservation uses `payment.paid_refund_review`.

### `payments.services.mark_failed(payment, *, actor=None, request=None) -> Payment`

- **Purpose:** Reconcile failure without downgrading paid state.
- **Inputs:** Payment and optional actor/request.
- **Outputs:** FAILED or unchanged PAID Payment.
- **Dependencies:** Reservation -> Payment locks, ActivityLog, failure email.
- **Behavior:** First failure is audited; notification attempt is reserved once and scheduled on commit.

### `payments.services.mark_pending(payment, *, actor=None, request=None) -> Payment`

- **Purpose:** Provide controlled administrator reopening of a non-paid row.
- **Inputs:** Payment and administrator/request.
- **Outputs:** PENDING Payment.
- **Dependencies:** Reservation -> Payment locks and ActivityLog.
- **Behavior:** PAID raises PaymentTransitionError; clears failure-notification marker and attributes audit to provided actor.

### `payments.services.send_confirmation_email|send_payment_failed_email(...) -> None`

- **Purpose:** Notify the customer about payment outcome and next action.
- **Inputs:** Reservation/Payment.
- **Outputs:** Best-effort email attempt.
- **Dependencies:** Django email/templates and site settings.
- **Behavior:** Skips missing email and uses fail-silent sending; calling transaction reserves attempt timestamp before scheduling.

### `payments.views.start(request, reservation_id) -> HttpResponse`

- **Purpose:** Begin checkout without a side-effecting GET.
- **Inputs:** CSRF-protected customer POST and owned reservation ID.
- **Outputs:** Simulator/PayMongo redirect or safe error redirect.
- **Dependencies:** `prepare_payment`, gateway client.
- **Behavior:** GET returns 405; paid/ineligible reservations do not reopen; missing real configuration fails visibly; provider session ID is stored after idempotent creation.

### `payments.views._abs_url(path) -> str`

- **Purpose:** Convert reversed application paths into PayMongo-compatible absolute URLs.
- **Inputs:** Root-relative path.
- **Outputs:** Absolute URL string.
- **Dependencies:** `SITE_BASE_URL`.
- **Behavior:** Concatenates the deploy-validated canonical base URL and path.

### `payments.views.simulate(request, pk) -> HttpResponse`

- **Purpose:** Exercise success/failure locally without a provider.
- **Inputs:** Explicit simulator setting, owner request, POST action.
- **Outputs:** Simulator page or receipt/detail redirect.
- **Dependencies:** `is_simulation_enabled`, mark_paid/mark_failed.
- **Behavior:** Non-simulator access raises 403; audit actor is the customer.

### `payments.views.gateway_return(request) -> HttpResponse`

- **Purpose:** Give customer feedback after hosted checkout.
- **Inputs:** Owner payment PK query parameter.
- **Outputs:** Receipt redirect if reconciled; otherwise detail with pending message.
- **Dependencies:** Webhook-owned state.
- **Behavior:** Browser return never proves or mutates payment success.

### `payments.views.webhook(request) -> JsonResponse`

- **Purpose:** Authenticate, deduplicate, validate, and reconcile a PayMongo event.
- **Inputs:** CSRF-exempt provider POST with signed JSON envelope.
- **Outputs:** Unauthorized/bad request or duplicate/ignored/rejected/processed JSON.
- **Dependencies:** Gateway signature verification, PayMongoWebhookEvent, Payment, `mark_paid`.
- **Behavior:** Validates ID/type/mode, persists unique delivery in atomic transaction, accepts exact checkout-paid event only, rejects unknown/ambiguous sessions and financial mismatches, then marks paid.

### `payments.views._validated_checkout_payment(resource) -> dict`

- **Purpose:** Extract the minimum safe paid-attempt fields.
- **Inputs:** Webhook checkout resource.
- **Outputs:** Normalized session/reference/amount/currency/method/intent/error mapping.
- **Dependencies:** Expected PayMongo checkout-session shape.
- **Behavior:** Requires checkout type, reference, payment list, and a paid attempt; malformed inputs return literal error.

### `payments.views._payment_mismatch(payment, checkout) -> str`

- **Purpose:** Compare provider financial facts with local immutable facts.
- **Inputs:** Payment and normalized checkout mapping.
- **Outputs:** Empty string or first mismatch reason.
- **Dependencies:** Session/reference/amount/currency fields.
- **Behavior:** Amount must be exact integer centavos; currency comparison is case-insensitive.

### `payments.views._finish_webhook(delivery, outcome, detail) -> JsonResponse`

- **Purpose:** Persist terminal provider-event outcome and acknowledge it.
- **Inputs:** Event record, outcome, detail.
- **Outputs:** JSON response.
- **Dependencies:** PayMongoWebhookEvent and logger.
- **Behavior:** Truncates detail, saves payment/outcome/detail, logs rejected events.

### `payments.views.receipt|history(request, pk?) -> HttpResponse`

- **Purpose:** Serve paid receipt and paginated customer payment history.
- **Inputs:** Authenticated request, optional payment PK/page.
- **Outputs:** HTML or redirect/403.
- **Dependencies:** Owner/admin policy and Paginator.
- **Behavior:** Receipt requires PAID; history is owner-scoped and 20 rows/page.

## Dashboard Module

### `dashboard.services._counts_by(model, field, choices) -> dict`

- **Purpose:** Produce zero-filled choice counts.
- **Inputs:** Model, field name, choice pairs.
- **Outputs:** Mapping for every choice value.
- **Dependencies:** ORM Count.
- **Behavior:** Missing database groups remain zero.

### `dashboard.services.slot_stats() -> dict`

- **Purpose:** Compute current slot KPIs without double counting.
- **Inputs:** Slot state and reservations covering now.
- **Outputs:** Total, maintenance, `occupied_now`, available_now.
- **Dependencies:** Distinct blocking slot IDs.
- **Behavior:** `occupied_now` counts distinct currently RESERVED or OCCUPIED slots excluding maintenance; maintenance takes precedence despite the historical key name.

### `dashboard.services.reservation_stats|payment_stats() -> dict`

- **Purpose:** Count reservation/payment states and paid revenue.
- **Inputs:** Current tables.
- **Outputs:** Zero-filled status counts and revenue cents.
- **Dependencies:** ORM aggregation.
- **Behavior:** Revenue includes PAID payments only.

### `dashboard.services.floor_breakdown() -> list[dict]`

- **Purpose:** Report inventory distribution by floor.
- **Inputs:** Floor/Slot state.
- **Outputs:** Floor total, maintenance, usable values.
- **Dependencies:** Conditional Count.
- **Behavior:** Read-only aggregation.

### `dashboard.services.monitor_slots(floor=None, vehicle_type=None) -> list[Slot]`

- **Purpose:** Annotate current live status for the admin grid.
- **Inputs:** Optional floor/type and current reservations.
- **Outputs:** Slots with transient `monitor_status`.
- **Dependencies:** Slot/Reservation queries.
- **Behavior:** Precedence is maintenance -> occupied -> reserved -> available.

### `dashboard.services.recent_activity(limit=15) -> QuerySet[ActivityLog]`

- **Purpose:** Retrieve recent audit evidence.
- **Inputs:** Limit.
- **Outputs:** Sliced ordered queryset.
- **Dependencies:** ActivityLog ordering.
- **Behavior:** Read-only.

### `dashboard.services.dashboard_overview() -> dict`

- **Purpose:** Assemble shared home/report context.
- **Inputs:** Current database state.
- **Outputs:** KPI/count/revenue/floor/activity context.
- **Dependencies:** Dashboard service functions.
- **Behavior:** Formats paid revenue for display without mutating data.

### `dashboard.views._page_context(request, queryset, page_parameter, page_size) -> tuple[Page, str]`

- **Purpose:** Paginate one dataset while retaining other filters/page controls.
- **Inputs:** Request, queryset, page parameter, size.
- **Outputs:** Page and encoded query suffix.
- **Dependencies:** Django Paginator/QueryDict.
- **Behavior:** Removes only its own page parameter from retained query data.

### `dashboard.views._customer_queryset() -> QuerySet[User]`

- **Purpose:** Define the safe customer-management population.
- **Inputs:** User table.
- **Outputs:** Customer-role, non-staff, non-superuser queryset.
- **Dependencies:** Roles/CUSTOMER_ROLES.
- **Behavior:** Privileged/non-customer accounts are excluded before PK lookup/actions.

### `dashboard.views.home|monitor|monitor_partial(request) -> HttpResponse`

- **Purpose:** Serve admin overview and live monitor/full fragment.
- **Inputs:** Admin request and optional filters.
- **Outputs:** HTML.
- **Dependencies:** admin_required and dashboard services.
- **Behavior:** Monitor fragment supports dependency-free polling without changing state.

### `dashboard.views._monitor_filters(request) -> tuple[Floor | None, str | None, str | None]`

- **Purpose:** Normalize live-monitor floor/type filters and retained query text.
- **Inputs:** Admin GET parameters.
- **Outputs:** Resolved floor, valid vehicle type, encoded query string.
- **Dependencies:** Floor and VehicleType choices.
- **Behavior:** Invalid filter values become no filter instead of reaching ORM mutation paths.

### `dashboard.views.reservations_manager(request) -> HttpResponse`

- **Purpose:** Search/filter/paginate reservations with safe next actions.
- **Inputs:** Admin GET status/floor/search/page.
- **Outputs:** 50-row page.
- **Dependencies:** ALLOWED_TRANSITIONS and related-object loading.
- **Behavior:** Each row exposes only transitions currently allowed by the domain graph.

### `dashboard.views.reservation_update_status(request, pk) -> HttpResponse`

- **Purpose:** Apply admin reservation transitions through central policy.
- **Inputs:** Admin POST, reservation PK, target status.
- **Outputs:** Redirect/message.
- **Dependencies:** `transition_reservation`.
- **Behavior:** Invalid/forbidden transitions do not mutate; actor is administrator.

### `dashboard.views.billing(request) -> HttpResponse`

- **Purpose:** Show payment transactions and canonical billing records.
- **Inputs:** Admin filters plus independent payment/billing page parameters.
- **Outputs:** Two 50-row paginated datasets.
- **Dependencies:** Payment/BillingRecord ORM.
- **Behavior:** Preserves filter/query parameters across each paginator.

### `dashboard.views.payment_update_status(request, pk) -> HttpResponse`

- **Purpose:** Provide controlled manual financial reconciliation.
- **Inputs:** Admin POST and target PENDING/FAILED/PAID.
- **Outputs:** Redirect/message and service-driven state.
- **Dependencies:** mark_paid/mark_failed/mark_pending.
- **Behavior:** PAID rows are immutable; services create receipt/notifications/audit; administrator is explicit actor.

### `dashboard.views.customers(request) -> HttpResponse`

- **Purpose:** Search/filter/paginate customer accounts.
- **Inputs:** Query, role, active state, page.
- **Outputs:** 50-row annotated customer page.
- **Dependencies:** `_customer_queryset`, ORM Q/Count.
- **Behavior:** Searches username/email/names/ID/contact and includes reservation/vehicle counts.

### `dashboard.views.customer_detail(request, pk) -> HttpResponse`

- **Purpose:** Show one safe customer profile and operational history.
- **Inputs:** Admin request, customer PK, independent history page parameters.
- **Outputs:** Profile/vehicles/counts/paid total and two 20-row pages.
- **Dependencies:** Safe customer queryset, Reservation/Payment ORM.
- **Behavior:** Privileged targets return 404; revenue is PAID-only.

### `dashboard.views.customer_toggle_active(request, pk) -> HttpResponse`

- **Purpose:** Activate/deactivate a customer without affecting privileged accounts.
- **Inputs:** Admin POST, customer PK, optional explicit `is_active`.
- **Outputs:** Redirect/message.
- **Dependencies:** User row lock and ActivityLog.
- **Behavior:** Rejects invalid values, self-deactivation, admin/non-customer targets; idempotent explicit state; actual change is audited.

### `dashboard.views.reports(request) -> HttpResponse`

- **Purpose:** Present aggregated operational evidence.
- **Inputs:** Admin request.
- **Outputs:** Report HTML.
- **Dependencies:** `dashboard_overview`.
- **Behavior:** Read-only.

## Presentation and Operations

### Templates and static assets

- **Purpose:** Provide responsive role-aware UI and notification/error content.
- **Inputs:** Django context, forms, page objects, messages.
- **Outputs:** HTML/text email; CSS/JavaScript/images.
- **Dependencies:** Base template, shared form/pagination fragments, WhiteNoise in production.
- **Behavior:** Customer histories use shared pagination; dashboard supports multi-paginator query retention; payment start uses CSRF POST form; custom 400/403/404/500 templates are standalone-safe; polling fetches slot fragments without external JS/CDN.

### `.github/workflows/ci.yml`

- **Purpose:** Reproduce the release gate from a clean Windows checkout.
- **Inputs:** Push/pull request on Python 3.13.
- **Outputs:** Pass/fail job.
- **Dependencies:** requirements.txt and temporary safe deployment environment.
- **Behavior:** Installs pinned dependencies, runs pip compatibility, Django checks, migration drift check, hermetic 104-test suite, production `check --deploy`, and collectstatic.

### Production lifecycle scheduler

- **Purpose:** Ensure time-driven state changes occur continuously.
- **Inputs:** External scheduler invocation every minute.
- **Outputs:** Applied lifecycle summary and operational logs.
- **Dependencies:** Hosting scheduler/cron/task runner; `process_reservations` command.
- **Behavior:** Scheduler definition is deployment-platform responsibility; repository supplies the idempotent command and dry-run mode.

## Data Model Relationships

### Relationship map

- **Purpose:** State ownership/deletion semantics literally.
- **Inputs:** Django model definitions.
- **Outputs:** Relationship reference.
- **Dependencies:** Database foreign keys/constraints.
- **Behavior:** User 1-many Vehicle (cascade); User 1-many Reservation (cascade); Floor 1-many Slot (cascade); Slot 1-many Reservation (protect); Vehicle 1-many Reservation (set null); Reservation 1-1 Payment (cascade); Payment 1-0..1 canonical BillingRecord (payment set null on deletion); Payment 1-many PayMongoWebhookEvent (set null); User 1-many ActivityLog (actor set null, label retained).

### Migration inventory

- **Purpose:** Record schema state required by current code.
- **Inputs:** Migration files.
- **Outputs:** Required migration list.
- **Dependencies:** Django migration executor.
- **Behavior:** Includes initial app migrations; `parking.0002_floor_image`; `reservations.0002_reservation_window_constraint`; `payments.0002_payment_notification_guards`; `payments.0003_payment_checkout_idempotency_and_webhook_events`.

## QA Evidence

### Automated gate result

- **Purpose:** Record objective evidence for this documentation snapshot.
- **Inputs:** Fresh in-memory test DB and production-safe temporary environment.
- **Outputs:** Verified status.
- **Dependencies:** `.venv` Python 3.14.4; pinned requirements.
- **Behavior:** `manage.py test --settings=config.settings_test`: 104/104 passed in 124.285s. `check`: 0 issues. `makemigrations --check --dry-run`: no changes. `compileall`: passed. `uv pip check`: all 15 installed packages compatible. `git diff --check`: no whitespace errors (Windows CRLF notices only). `check --deploy`: 0 issues with safe values. `collectstatic`: 138 assets present and 365 post-processed.

### Tested risk areas

- **Purpose:** Identify what the regression suite proves.
- **Inputs:** 104 automated tests.
- **Outputs:** Coverage statement.
- **Dependencies:** Django TestCase/SimpleTestCase and hermetic settings.
- **Behavior:** Covers role/access boundaries, password hashing/reset, admin enrollment fail-closed/throttling, vehicle ownership, live availability, database window constraint, atomic service behavior, transition/check-in/QR policy, lifecycle/dry-run, simulator fail-closed, checkout POST/idempotency, webhook mode/freshness/dedupe/financial validation, notification guards, receipt uniqueness, customer/billing dashboard actions, generic-admin safety, custom errors, pagination, CI/deployment settings.

## Known Operational Boundaries

### Email dispatch

- **Purpose:** Clarify delivery semantics.
- **Inputs:** Post-commit notification callbacks.
- **Outputs:** At-most-once dispatch attempts.
- **Dependencies:** Configured email backend and `EMAIL_TIMEOUT`.
- **Behavior:** Notification timestamps reserve attempts before fail-silent send and do not prove provider delivery. SMTP monitoring/retry is an operations responsibility; webhook retries remain financially idempotent.

### Refunds

- **Purpose:** Clarify financial scope.
- **Inputs:** Paid cancellation.
- **Outputs:** Audit review marker and customer guidance.
- **Dependencies:** Manual administrator/PayMongo refund process.
- **Behavior:** No automatic refund API call or refund-state model is implemented.

### Media and infrastructure

- **Purpose:** Clarify deployment ownership.
- **Inputs:** User uploads, MySQL, SMTP, scheduler, HTTPS proxy.
- **Outputs:** Required external services.
- **Dependencies:** Hosting platform.
- **Behavior:** WhiteNoise serves static assets only; production media requires separate storage/serving. Concurrency claims assume MySQL. Scheduler and SMTP must be provisioned externally.
