# healthcare_hub

## Run locally on Windows

Use Python 3.12 and create a virtual environment inside the project:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py check
python manage.py runserver
```

The development server is available at <http://127.0.0.1:8000/>. The Django
admin login is at <http://127.0.0.1:8000/admin/login/>.

Copy `.env.example` to `.env` and set the PostgreSQL, SQL Server, and
Betterlife database values for your environment before using endpoints that
access those databases.
