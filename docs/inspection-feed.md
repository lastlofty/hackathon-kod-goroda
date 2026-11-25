# Кадры обследования

Фронт при открытии загружает `GET /api/v1/inspection/frames?workspace=mgts`. Параметр workspace — slug проекта. Ответ содержит массивы frames, entities, types и standalone_findings. Каждая запись frames содержит поля MediaRead и массив findings с полными записями FindingRead. Картинку браузер получает по url. Относительные URL отсчитываются от адреса API.

Ниже показаны основные поля одного кадра. Результат без обнаружений содержит пустой массив findings.

```json
{
  "id": "a292c002-2336-463a-8ceb-8cb8be128007",
  "url": "/uploads/example.jpg",
  "latitude": 55.76566,
  "longitude": 37.60712,
  "attributes": {"route_id": "tverskoy"},
  "findings": [{
    "id": "e94c3101-ea20-4cec-97a3-e59a78eeb677",
    "media_id": "a292c002-2336-463a-8ceb-8cb8be128007",
    "category": "pole",
    "label": "Опора освещения",
    "score": 0.94,
    "geometry": {"type": "bbox", "coordinate_space": "normalized", "x": 0.2, "y": 0.1, "width": 0.12, "height": 0.7}
  }]
}
```

Чтобы передать реальные результаты, обработчик создаёт кадр через `POST /api/v1/media` (либо загружает файл через `POST /api/v1/media/upload`). Для каждого обнаружения он передаёт `POST /api/v1/findings` с workspace_id, media_id, category и данными модели. Координаты места съёмки задаются полями latitude и longitude у кадра. Координаты рамки отсчитываются от левого верхнего угла. Пиксельные размеры поддерживаются с coordinate_space равным pixel. Необязательный attributes.route_id связывает кадр с существующим маршрутом интерфейса.

`GET /api/v1/inspection/stream?workspace=mgts` отдаёт text/event-stream. Первое событие batch содержит актуальный снимок целиком. Далее changes передаёт upsert с изменёнными записями по коллекциям и remove с удалёнными ID. При изменении обнаружений сервер передаёт соответствующий кадр целиком. Сейчас сервер сверяет состояние базы раз в две секунды. После обрыва EventSource переподключается и получает новый batch. Поток передаёт актуальное состояние для просмотра, промежуточные версии за интервал опроса могут объединиться.
