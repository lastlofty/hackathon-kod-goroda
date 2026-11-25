# Универсальная основа backend для хакатона

Репозиторий содержит case-agnostic backend: предметные сущности, статусы и поля конкретного ТЗ не зашиты в Python-модели. Новый кейс создаётся как отдельный `workspace`, типы объектов описываются через JSON Schema, а произвольные результаты обработки сохраняются как `findings`.

Основа рассчитана на типичный поток компьютерного зрения или обработки данных:

```text
workspace -> media -> processing job -> findings
          -> entity types -> entities ----^
```

## Почему основу можно адаптировать без переписывания БД

- `workspaces` изолируют данные и настройки разных ТЗ.
- `entity_types.attribute_schema` хранит JSON Schema полей объекта. Backend проверяет `entities.attributes` по этой схеме.
- `entities.attributes` и `entities.geometry` принимают предметные данные без новых колонок.
- `media.kind` не ограничен списком `image/video`: допустимы кадр, документ, телеметрия или иной артефакт.
- `processing_jobs.pipeline`, `status`, `parameters` и `result` не привязаны к Triton, YOLO или конкретной очереди.
- `findings.category`, `label`, `status`, `geometry` и `attributes` подходят для детекции, классификации, OCR, аномалий и ручной разметки.
- Все связи проверяются по `workspace_id`: данные одного ТЗ нельзя случайно связать с другим.

Подробные материалы:

- [ER-схема и назначение таблиц](docs/database.md)
- [Как адаптировать основу под новое ТЗ](docs/adaptation.md)

## Быстрый старт

```bash
docker compose up --build
```

Для локальных настроек создайте файл `.env` по образцу `.env.example`. Секреты храните в локальном файле.

В другом терминале из корня репозитория запустите интерфейс:

```bash
python3 -m http.server 8778 --bind 127.0.0.1 --directory frontend
```

Откройте [карту и реестр МГТС](http://localhost:8778/). Для карты и проезда введите в настройках интерфейса ключ 2ГИС с доступом к Map Tiles API и Routing API. Серверный ключ геокодера задаётся отдельно через `DGIS_API_KEY` в локальном `.env`. Фотографии загружаются в рабочую область `mgts`, правки точек и рамок сохраняются в браузере и доступны для экспорта в JSON.

После запуска:

- Swagger UI: <http://localhost:8080/docs>
- OpenAPI: <http://localhost:8080/openapi.json>
- healthcheck: <http://localhost:8080/health>
- PostgreSQL: `localhost:5432`

При старте контейнер backend автоматически выполняет `alembic upgrade head`.

> Схема была обобщена до появления реального кейса, поэтому первоначальная миграция `0001_initial` заменена. Если вы запускали предыдущую версию репозитория, удалите тестовый Docker volume командой `docker compose down -v`, затем поднимите проект заново. Применять это к базе с нужными данными нельзя.

## Сущности

| Сущность | Назначение | Гибкие поля |
|---|---|---|
| `workspace` | Отдельное ТЗ/кейс | `settings` |
| `entity_type` | Настраиваемый тип предметного объекта | `attribute_schema` |
| `entity` | Объект предметной области | `attributes`, `geometry` |
| `media` | Входной файл или ссылка на источник | `kind`, `attributes` |
| `processing_job` | Запуск модели, импорта или другой обработки | `pipeline`, `parameters`, `result`, `status` |
| `finding` | Результат модели или ручной проверки | `category`, `label`, `status`, `geometry`, `attributes` |

Координаты у `entity` и `media` необязательны. Они оставлены отдельными колонками для простого фильтра карты; сложная геометрия хранится в JSON-поле `geometry`.

## CRUD API

Префикс всех предметных маршрутов: `/api/v1`.

| Сущность | Список / создание | Чтение / изменение / удаление |
|---|---|---|
| Кейсы | `GET/POST /workspaces` | `GET/PATCH/DELETE /workspaces/{id}` |
| Типы объектов | `GET/POST /entity-types` | `GET/PATCH/DELETE /entity-types/{id}` |
| Объекты | `GET/POST /entities` | `GET/PATCH/DELETE /entities/{id}` |
| Медиа | `GET/POST /media` | `GET/PATCH/DELETE /media/{id}` |
| Задачи обработки | `GET/POST /jobs` | `GET/PATCH/DELETE /jobs/{id}` |
| Результаты | `GET/POST /findings` | `GET/PATCH/DELETE /findings/{id}` |

Загрузка JPEG, PNG или WebP: `POST /api/v1/media/upload` (`multipart/form-data`). Обязательное поле формы — `workspace_id`.

Списки поддерживают пагинацию `offset`/`limit` и предметные фильтры. Полный контракт с типами и допустимыми параметрами всегда доступен в Swagger.

## Минимальная настройка нового ТЗ

### 1. Создать workspace

```http
POST /api/v1/workspaces
Content-Type: application/json

{
  "slug": "new-case",
  "name": "Новый кейс",
  "settings": {
    "finding_statuses": ["new", "confirmed", "rejected"],
    "default_pipeline": "detector-v1"
  }
}
```

### 2. Описать тип объекта

```http
POST /api/v1/entity-types
Content-Type: application/json

{
  "workspace_id": "<workspace UUID>",
  "code": "target_object",
  "name": "Целевой объект",
  "attribute_schema": {
    "type": "object",
    "properties": {
      "serial": {"type": "string"},
      "priority": {"type": "integer", "minimum": 0}
    },
    "required": ["serial"],
    "additionalProperties": true
  }
}
```

### 3. Создать объект с полями нового ТЗ

```http
POST /api/v1/entities
Content-Type: application/json

{
  "workspace_id": "<workspace UUID>",
  "entity_type_id": "<entity type UUID>",
  "external_id": "OBJECT-001",
  "attributes": {
    "serial": "A-123",
    "priority": 10
  }
}
```

Если обязательного `serial` нет или `priority` имеет неверный тип, API вернёт `422`. Python-код и миграция для этих полей не меняются.

## Интеграция обработки

`TRITON_URL` зарезервирован в настройках, но backend намеренно не вызывает выдуманную модель. Реальный worker или inference-сервис работает по следующему контракту:

1. Получает или создаёт `media`.
2. Создаёт `processing_job` со своим именем pipeline и параметрами.
3. Пишет один или несколько `findings`, связывая их с `job_id`, `media_id` и при необходимости `entity_id`.
4. Обновляет задачу до фактического статуса и сохраняет краткий `result` либо `error_message`.

Так worker можно заменить с Triton на обычный FastAPI-сервис, очередь Celery, скрипт или внешний API без изменения предметной схемы.

## Интеграция с 2ГИС

Backend подключён к официальному Geocoder API 2ГИС через отдельный adapter `app/integrations/dgis.py`. Ключ и параметры соединения читаются из переменных окружения:

```env
DGIS_API_KEY=<API key>
DGIS_BASE_URL=https://catalog.api.2gis.com
DGIS_LOCALE=ru_RU
DGIS_TIMEOUT_SECONDS=30
```

Доступны два маршрута:

| Операция | Маршрут | Основные параметры |
|---|---|---|
| Адрес → координаты | `GET /api/v1/geocoding/search` | `q`, `page_size`, `region_id` |
| Координаты → адрес | `GET /api/v1/geocoding/reverse` | `lat`, `lon`, `radius`, `type`, `page_size` |

Прямое геокодирование:

```http
GET /api/v1/geocoding/search?q=Москва,%20Авиамоторная%20улица,%208с39&page_size=5
```

Обратное геокодирование с поиском ближайшего здания в радиусе 100 метров:

```http
GET /api/v1/geocoding/reverse?lat=55.75&lon=37.61&radius=100&type=building
```

Ответ backend имеет стабильную оболочку, а элементы остаются в формате провайдера:

```json
{
  "provider": "2gis",
  "total": 1,
  "items": []
}
```

Backend ограничивает `radius` диапазоном 0–2000 метров, как требует Geocoder API для обратного поиска без текстового запроса. Таймаут, сетевые ошибки и ошибки ключа не раскрывают значение ключа клиенту.

Интеграция необязательна: если пакет `httpx2` отсутствует или не импортируется, приложение всё равно запускается, остальные маршруты работают, а геокодинг отвечает `503`. Это покрыто тестом `tests/test_dependency_isolation.py`; проверка зависимостей и сценарий подмены описаны в [docs/dependency-hardening.md](docs/dependency-hardening.md).

## Структура проекта

```text
app/
  api/         # HTTP-маршруты и сериализация ответов
  core/        # настройки приложения
  db/          # engine, Session и SQLAlchemy Base
  integrations/ # клиенты 2ГИС и будущих внешних сервисов
  models/      # таблицы и связи
  schemas/     # входные и выходные Pydantic-контракты
  services/    # проверка ссылок и JSON Schema
migrations/    # Alembic
tests/         # API-тесты на SQLite
docs/          # схема БД и инструкция адаптации
```

Правило расширения: предметную логику помещаем в `services`, интеграции — в отдельные адаптеры/worker, а API не обращается к модели машинного обучения напрямую.

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

Проверка совпадения ORM и миграций:

```bash
alembic check
```

## Осознанно не реализовано

Пока нет реального ТЗ, в основу не добавлены аутентификация, роли, S3/MinIO, очередь задач, конкретный inference-клиент и PostGIS. Их нельзя корректно спроектировать без требований к пользователям, нагрузке, формату данных и инфраструктуре. Локальная загрузка файлов подходит для разработки, но не является production-хранилищем.
