# Схема базы данных

## Связи

```mermaid
erDiagram
    WORKSPACES ||--o{ ENTITY_TYPES : configures
    WORKSPACES ||--o{ ENTITIES : owns
    WORKSPACES ||--o{ MEDIA : owns
    WORKSPACES ||--o{ PROCESSING_JOBS : owns
    WORKSPACES ||--o{ FINDINGS : owns
    ENTITY_TYPES o|--o{ ENTITIES : validates
    MEDIA o|--o{ PROCESSING_JOBS : processed_by
    ENTITIES o|--o{ FINDINGS : describes
    MEDIA o|--o{ FINDINGS : source_for
    PROCESSING_JOBS o|--o{ FINDINGS : produces

    WORKSPACES {
        uuid id PK
        string slug UK
        string name
        text description
        json settings
    }

    ENTITY_TYPES {
        uuid id PK
        uuid workspace_id FK
        string code
        string name
        json attribute_schema
        boolean active
    }

    ENTITIES {
        uuid id PK
        uuid workspace_id FK
        uuid entity_type_id FK
        string external_id
        string name
        json attributes
        json geometry
        float latitude
        float longitude
    }

    MEDIA {
        uuid id PK
        uuid workspace_id FK
        string kind
        text url
        string content_type
        timestamptz captured_at
        json attributes
    }

    PROCESSING_JOBS {
        uuid id PK
        uuid workspace_id FK
        uuid media_id FK
        string pipeline
        string status
        json parameters
        json result
        text error_message
    }

    FINDINGS {
        uuid id PK
        uuid workspace_id FK
        uuid entity_id FK
        uuid media_id FK
        uuid job_id FK
        string category
        string label
        string status
        float score
        float severity
        json geometry
        json attributes
        boolean reviewed
    }
```

## Инварианты

- `workspace.slug` уникален во всей системе.
- `entity_type.code` уникален внутри workspace.
- `entity.external_id` уникален внутри workspace; `NULL` разрешён.
- `finding.score` равен `NULL` или находится в диапазоне от 0 до 1.
- Связанные entity type, entity, media и job должны относиться к тому же workspace. Это проверяет service layer до записи.
- `entity.attributes` проверяется по JSON Schema выбранного `entity_type`.
- Координаты передаются только парой: latitude вместе с longitude.

## Удаление

- Удаление workspace каскадно удаляет принадлежащие ему данные.
- Удаление entity type оставляет entity, но устанавливает `entity_type_id = NULL`.
- Удаление entity, media или job не удаляет finding, а обнуляет соответствующую ссылку. Результат остаётся для аудита.

## Геоданные

Для начальной карты используются индексированные `latitude` и `longitude`. Произвольная точка, bbox, polygon или координаты изображения могут храниться в `geometry`. PostGIS следует добавлять только при подтверждённой необходимости радиусного поиска, пространственных пересечений или маршрутизации.
