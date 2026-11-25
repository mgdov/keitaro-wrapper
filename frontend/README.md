# Frontend — Keitaro Wrapper

Next.js + React + TypeScript. Все команды выполняются из этой папки (`frontend/`).

```bash
npm ci
BACKEND_URL=http://127.0.0.1:8011 npm run dev -- --port 3011
```

Откройте <http://127.0.0.1:3011>. Backend запускается отдельно из `../backend/`.
API-ключ Keitaro задаётся только в окружении backend.

Проверки и production-сборка:

```bash
npm run typecheck
BACKEND_URL=http://127.0.0.1:8011 npm run build
BACKEND_URL=http://127.0.0.1:8011 npm run start -- --port 3011
```

Одинаковый BACKEND_URL нужен при build и start, поскольку адрес прокси включается
в сборку Next.js. Общая документация — [README](../README.md).
