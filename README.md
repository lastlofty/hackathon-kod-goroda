# Мониторинг инфраструктуры МГТС

Стартовый backend для прототипа кейс-чемпионата «Код города». API хранит объекты инфраструктуры, фото/кадры и результаты автоматических или ручных осмотров.

## Быстрый старт

```bash
cp .env.example .env
docker compose up --build
```

После запуска:

- Swagger UI: <http://localhost:8080/docs>
- OpenAPI: <http://localhost:8080/openapi.json>
- healthcheck: <http://localhost:8080/health>
- PostgreSQL: `localhost:5432`

## Сущности

- `assets` — кабельные колодцы, опоры двойного назначения и другие объекты;
- `media` — фотографии, видео и кадры с координатами;
- `inspections` — статус, дефект, уверенность модели, опасность и рекомендация.

Подробная ER-схема: [docs/database.md](docs/database.md).

## CRUD API

| Сущность | Список / создание | Чтение / изменение / удаление |
|---|---|---|
| Объекты | `GET/POST /api/v1/assets` | `GET/PATCH/DELETE /api/v1/assets/{id}` |
| Медиа | `GET/POST /api/v1/media` | `GET/PATCH/DELETE /api/v1/media/{id}` |
| Осмотры | `GET/POST /api/v1/inspections` | `GET/PATCH/DELETE /api/v1/inspections/{id}` |

Загрузка JPEG, PNG или WebP: `POST /api/v1/media/upload` (`multipart/form-data`).

`GET /api/v1/assets` поддерживает `asset_type` и границы карты `min_lat`, `max_lat`, `min_lon`, `max_lon`. `GET /api/v1/inspections` фильтрует по `asset_id`, `media_id`, `condition`, `reviewed`.

## Локальная разработка

```bash
python -m venv .venv
.venv/Scripts/activate
pip install -r requirements-dev.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8080
```

Тесты используют SQLite и не требуют запущенного PostgreSQL:

```bash
pytest -q
```

## Интеграция с inference

`TRITON_URL` зарезервирован для отдельного Triton-сервиса. Текущий backend не вызывает модель и не имитирует ее ответ. Инференс-сервис может создавать записи в `inspections` через API или отдельный service layer.
