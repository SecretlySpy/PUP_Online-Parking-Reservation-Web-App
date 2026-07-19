# Tech Stack Setup Guide

## Complete Tech Stack List

| Component | Technology | Version | Description |
| :--- | :--- | :--- | :--- |
| **Language** | Python | 3.10+ | Core programming language |
| **Framework** | Django | 6.0.7 | Web framework |
| **Package Manager**| `pip` or `uv` | Latest | Python dependency management |
| **Local Database** | SQLite | Built-in | Zero-setup development database |
| **Prod Database** | MySQL | 8.0+ | Production database (via PyMySQL) |

**Key Libraries:**
*   `django-environ==0.14.0`: Environment variable configuration
*   `PyMySQL==1.2.0`: Pure-Python MySQL driver
*   `qrcode[pil]==8.2` & `Pillow==12.3.0`: QR generation for reservations
*   `requests==2.34.2`: HTTP client for PayMongo REST calls
*   `whitenoise==6.11.0`: Static asset serving in production
*   `reportlab==5.0.0`: Server-side PDF receipt generation

---

## Setup Instructions

### Architecture Overview

```mermaid
flowchart LR
    Dev[Developer Machine] -->|Clone| Git[Repository]
    Git -->|Install| Venv[Virtual Environment]
    Venv -->|python manage.py runserver| LocalApp[Local Server]
    LocalApp -->|Reads/Writes| SQLite[(SQLite db.sqlite3)]
```

### 1. macOS Setup

```bash
# 1. Ensure Python 3 is installed (via Homebrew)
brew install python3

# 2. Clone the repository and navigate to it
git clone <repository-url>
cd PUP_Online-Parking-Reservation-Web-App

# 3. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Setup environment variables (using defaults for local dev)
cp .env.example .env

# 6. Apply database migrations
python manage.py migrate

# 7. Start the development server
python manage.py runserver
```

### 2. Windows Setup

```powershell
# 1. Ensure Python is installed from python.org (Check 'Add Python to PATH')

# 2. Clone the repository and navigate to it
git clone <repository-url>
cd PUP_Online-Parking-Reservation-Web-App

# 3. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Setup environment variables (using defaults for local dev)
copy .env.example .env

# 6. Apply database migrations
python manage.py migrate

# 7. Start the development server
python manage.py runserver
```

### 3. Linux Setup (Ubuntu/Debian)

```bash
# 1. Install Python 3 and venv package
sudo apt update
sudo apt install python3 python3-venv python3-pip

# 2. Clone the repository and navigate to it
git clone <repository-url>
cd PUP_Online-Parking-Reservation-Web-App

# 3. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Setup environment variables (using defaults for local dev)
cp .env.example .env

# 6. Apply database migrations
python manage.py migrate

# 7. Start the development server
python manage.py runserver
```

---

## Production / Staging Environment Differences

```mermaid
graph TD
    App[Django 6.0.7 App] -->|DATABASE_URL| Env(Environment Variables)
    Env -->|sqlite:///db.sqlite3| LocalDB[(Local SQLite)]
    Env -->|mysql://user:pass@host/db| ProdDB[(Production MySQL)]
```

*   **Database:** Local development relies on the automatically created `db.sqlite3`. Production environments must define the `DATABASE_URL` pointing to a MySQL instance.
*   **Static Files:** `whitenoise` serves static files in production, ensuring they are compressed and fingerprinted.

---

## Common Troubleshooting Tips

*   **Missing `.env` file:** 
    *   *Issue:* The app fails to start or complains about missing configurations.
    *   *Fix:* Make sure to copy `.env.example` to `.env` in the root directory.
*   **Virtual Environment not activated:**
    *   *Issue:* `pip install` installs packages globally, or `python manage.py` complains about missing modules (e.g., `ModuleNotFoundError: No module named 'django'`).
    *   *Fix:* Always ensure you activate your virtual environment before running commands. You should see `(.venv)` in your terminal prompt.
*   **Database connection issues (Production):**
    *   *Issue:* Cannot connect to MySQL.
    *   *Fix:* Verify that the `DATABASE_URL` in your `.env` file is formatted correctly: `mysql://username:password@hostname:port/databasename`.
*   **PayMongo errors / Webhooks failing:**
    *   *Issue:* Payments fail in simulation or webhooks reject.
    *   *Fix:* Ensure `PAYMONGO_SECRET_KEY`, `PAYMONGO_PUBLIC_KEY`, and `PAYMONGO_WEBHOOK_SECRET` are properly set in your environment if you are testing real payments. Set `PAYMENT_SIMULATION_ENABLED=True` in `.env` if you are testing locally without network requests.
*   **Port 8000 already in use:**
    *   *Issue:* `python manage.py runserver` fails stating port 8000 is occupied.
    *   *Fix:* Run the server on a different port: `python manage.py runserver 8080`.
