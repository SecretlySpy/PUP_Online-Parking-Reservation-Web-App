# PUP Online Parking Reservation

A role-based web application that lets students, employees, and visitors view
**real-time parking-slot availability**, **reserve slots** for a specific date
and time, and **pay reservation fees online** (GCash / Maya / card), while
administrators manage inventory, reservations, payments, billing, and reports.
Built to replace a manual Google-Forms process for a single campus facility.

Built with **Django 6 + MySQL** (SQLite for zero-setup local dev), **PayMongo**
for payments, and evaluated against **ISO/IEC 25010** (see
[`docs/ISO-IEC-25010-evaluation.md`](docs/ISO-IEC-25010-evaluation.md)).

---

## Features

**Public**
- **Facility Guide** — browse each floor with a photo and **live availability**, deep-linking to the slot search filtered by floor.
- Landing page with a parking-garage hero and a themed **404** page.

**Customer (student / employee / visitor)**
- Role-based registration & login; **PBKDF2** password hashing.
- One-time, token-verified **password reset by email**.
- **Real-time slot availability** with auto-refresh; filter by floor, vehicle/slot
  type, availability, date, and time range.
- **Reserve** a slot for a date/time window (overlap-checked), **modify/cancel**.
- Unique **reservation codes** + **signed QR** for verification on arrival.
- **Online payment** of the reservation fee (GCash / Maya / card via PayMongo).
- **Payment history**, e-receipts, and email booking confirmations.
- Personal profile and **vehicle management**.

**Administrator**
- Separate admin registration (access-code gated) & login.
- **Dashboard** overview KPIs + recent activity feed.
- **Live slot monitor** (auto-refresh) with floor/type filters.
- Slot & floor management; mark slots **available / maintenance**.
- **Reservation manager** — filter by status/floor; set reserved/occupied/completed/cancelled.
- **Billing & payment management** — gateway transactions, paid/pending/failed, billing records.
- **Reports** — slot counts, availability, reservation-status totals, revenue, recent activity.
- Arrival **QR verification** view.

---

## Tech stack

| Concern | Choice |
|---|---|
| Backend | Django 6.0 (Python 3.14) |
| Database | MySQL (target) · SQLite (default local dev) — switch via `DATABASE_URL` |
| MySQL driver | PyMySQL (pure-Python; no C toolchain) |
| Payments | PayMongo REST (checkout sessions + webhooks); built-in simulation when unkeyed |
| Auth/hashing | Django auth, PBKDF2 (pinned) |
| QR | `qrcode` + Pillow, `django.core.signing` |
| Config | `django-environ` (`.env`) |
| Frontend | Django templates + vanilla-JS polling; responsive PUP-branded CSS (no CDN) |

---

## Quick start (local dev — SQLite, no external services)

Requires Python 3.12+ (3.14 used here). Using [`uv`](https://docs.astral.sh/uv/):

```bash
uv venv .venv --python 3.14
uv pip install -r requirements.txt

# optional: cp .env.example .env  (defaults work without it)
.venv/Scripts/python manage.py migrate
.venv/Scripts/python manage.py seed_parking          # demo floors/slots
.venv/Scripts/python manage.py createsuperuser       # an admin account
.venv/Scripts/python manage.py runserver
```

Open http://127.0.0.1:8000. In dev, emails (reset links, confirmations) print to
the console, and payments use a built-in **simulated gateway** (no keys needed).

Plain `pip` works too: `python -m venv .venv && pip install -r requirements.txt`.

---

## Configuration (`.env`)

Copy `.env.example` → `.env`. Key variables:

| Variable | Purpose | Dev default |
|---|---|---|
| `DEBUG` | Debug mode | `True` |
| `SECRET_KEY` | Django secret | insecure dev key |
| `ALLOWED_HOSTS` | Comma list | `*` |
| `DATABASE_URL` | DB connection | SQLite file |
| `EMAIL_*` | SMTP settings | console backend |
| `PAYMONGO_SECRET_KEY` / `PAYMONGO_PUBLIC_KEY` | Gateway keys | empty → simulation |
| `PAYMONGO_WEBHOOK_SECRET` | Webhook signature secret | empty → verification off |
| `RESERVATION_FEE_CENTS` | Fee in centavos | `5000` (₱50) |
| `ADMIN_SIGNUP_CODE` | Gate admin self-registration | empty (open in dev) |

### Switch to MySQL (deployment target)
1. Install MySQL 8 (standalone or XAMPP) and create a database + user.
2. Set in `.env`:
   ```
   DATABASE_URL=mysql://pup_user:pup_pass@127.0.0.1:3306/pup_parking
   ```
3. `python manage.py migrate`. (The PyMySQL shim in `config/__init__.py` makes
   the `mysql` backend work without compiling `mysqlclient`.)

### Enable real PayMongo
Set `PAYMONGO_SECRET_KEY` / `PAYMONGO_PUBLIC_KEY` (test keys during development)
and `PAYMONGO_WEBHOOK_SECRET`. Point a PayMongo webhook at
`/payments/webhook/` (expose locally with a tunnel such as ngrok). With keys set,
the simulated gateway is disabled automatically and real hosted checkout is used.

---

## Running the tests

```bash
python manage.py test          # 45 tests
python manage.py check         # system checks
python manage.py check --deploy   # security posture (clean when DEBUG=False + SECRET_KEY set)
```

---

## Project structure

```
config/          project settings, root urls, PyMySQL shim
core/            shared: base templates, activity log, context processors, constants
accounts/        custom User + roles, auth, password reset, profiles, vehicles
parking/         floors, slots, availability service, real-time slot views + JSON API
reservations/    bookings, overlap validation, codes, signed QR, verification
payments/        PayMongo gateway, payment/billing models, webhook, receipts, emails
dashboard/       admin overview, live monitor, reservation manager, billing, reports
templates/  static/  media/
```

See [`AI Documentation Notes.md`](AI%20Documentation%20Notes.md) for a
module-by-module technical reference.

---

## Delimitations
Web-only (responsive, no native app); online payment via PayMongo only (no online
cash; refunds/disputes handled manually per gateway policy); QR for verification
only (no hardware scanning); no barrier/CCTV/IoT integration — statuses set via
the app; single campus facility; email features require a configured SMTP service.
