# Схема базы данных

Схема покрывает минимальный цикл: медиафайл поступает в систему, модель находит объект, а результат анализа сохраняется как осмотр.

```mermaid
erDiagram
    ASSETS ||--o{ INSPECTIONS : "имеет историю"
    MEDIA ||--o{ INSPECTIONS : "служит источником"

    ASSETS {
        uuid id PK
        string external_id UK
        string asset_type
        string name
        text description
        float latitude
        float longitude
        string address
        timestamptz created_at
        timestamptz updated_at
    }

    MEDIA {
        uuid id PK
        string media_type
        text url
        string original_filename
        string content_type
        timestamptz captured_at
        float latitude
        float longitude
        string source
        timestamptz created_at
        timestamptz updated_at
    }

    INSPECTIONS {
        uuid id PK
        uuid asset_id FK
        uuid media_id FK
        timestamptz observed_at
        string condition
        string defect_type
        float confidence
        int severity
        text recommendation
        json bbox
        string model_name
        string model_version
        boolean reviewed
        timestamptz created_at
        timestamptz updated_at
    }
```

## Справочные значения

- `asset_type`: `cable_well`, `dual_purpose_support`, `other`.
- `condition`: `normal`, `attention`, `repair`, `critical`.
- `confidence`: уверенность модели от 0 до 1.
- `severity`: оценка опасности от 0 до 100, не вероятность.
- `bbox`: координаты области детекции, например `{"x": 10, "y": 20, "width": 100, "height": 80}`.

PostGIS на старте не нужен: для MVP карта получает объекты по прямоугольнику из `min_lat`, `max_lat`, `min_lon`, `max_lon`. Если появятся поиск по радиусу или маршруты, координаты можно мигрировать в `geography(Point, 4326)`.
