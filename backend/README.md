# Backend — Keitaro Wrapper

FastAPI + SQLAlchemy + SQLite, миграции Alembic.
Все команды ниже выполняются из этой папки (`backend/`).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Заполните KEITARO_API_KEY в .env
alembic upgrade head
uvicorn app.main:app --host 127.0.0.1 --port 8011
```

Проверки:

```bash
pytest -q
alembic check
```

Swagger: <http://127.0.0.1:8011/docs>.
База `keitaro.db`, `.env` и `.venv/` хранятся здесь и не включаются в Git.
Правила работы редактора и интеграции описаны в [общем README](../README.md).
