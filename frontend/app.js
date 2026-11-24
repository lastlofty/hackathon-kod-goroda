'use strict';

const priorities = {urgent: 'Срочно', review: 'На проверку', normal: 'Без замечаний', unverified: 'Не обследовано'};
// Older installations use the original API adapter and share the default demo cache.
const defaultBackend = typeof workspaceSlug === 'undefined' || (workspaceSlug === 'mgts' && backendBase.origin === 'http://localhost:8080');
const savedKey = defaultBackend
  ? 'mgts-inspection-v1' : `mgts-inspection-v1:${backendBase.origin}:${workspaceSlug}`;
let records = {schemaVersion: 1, datasetId: null, coordinateOrder: 'longitude,latitude',
  coordinateSpace: 'normalized-image-xywh', route: [], frames: [], objects: []};

const state = {view: 'map', selected: records.objects[0]?.id, filter: 'all', overlay: true, pin: false, pinFrame: null, pinBox: null};
const $ = id => document.getElementById(id);
const frameById = id => records.frames.find(frame => frame.id === id);
const visibleObjects = () => records.objects.filter(record =>
  state.filter === 'all' || priorityOf(record) === state.filter
);
const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[char]));
const number = value => value.toFixed(5);
const isValidPoint = point => Array.isArray(point) && Number.isFinite(point[0]) &&
  Math.abs(point[0]) <= 180 && Number.isFinite(point[1]) && Math.abs(point[1]) <= 90;
const formatPoint = point => isValidPoint(point) ? `${number(point[1])}, ${number(point[0])}` : '—';
const displayId = record => record.displayId || record.id;
const newId = () => crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
const priorityOf = record => Object.hasOwn(priorities, record.priority) ? record.priority : 'unverified';
const status = record => `<span class="status ${priorityOf(record)}"><i class="dot"></i>${priorities[priorityOf(record)]}</span>`;
const sourceLink = source => /^https?:\/\//.test(source?.url ?? '')
  ? `<a href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.label || 'Источник')}</a>` : '';
let noticeTimer;

function announce(message) {
  const notice = $('notice');
  notice.textContent = message;
  notice.hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { notice.hidden = true; }, 4400);
}

function persist(message) {
  try {
    localStorage.setItem(savedKey, JSON.stringify(records));
    announce(message);
  } catch {
    announce('Хранилище браузера недоступно или заполнено. Изменения доступны до закрытия вкладки.');
  }
}

function boxHTML(box, selected = false, caption = true) {
  if (!box) return '';
  const classes = ['box', box.source === 'manual' ? 'manual' : '', selected ? 'selected' : '', box.y < .08 ? 'top' : '', box.x > .67 ? 'right' : ''].join(' ');
  return `<div class="${classes}" style="--x:${box.x};--y:${box.y};--w:${box.w};--h:${box.h}">${caption ? `<span class="tag">${escapeHTML(box.label)}</span>` : ''}</div>`;
}

function showRecord(id, move = false) {
  const record = visibleObjects().find(item => item.id === id);
  if (!record) {
    announce('Объект недоступен при текущем фильтре.');
    return;
  }
  if (state.pin) resetPin();
  state.selected = id;
  state.overlay = true;
  renderSelection();
  if (move && isValidPoint(record.point)) {
    drivePlayer?.exit();
    inspectionMap?.panTo(record.point);
  }
}

function renderSelection() {
  const visible = visibleObjects();
  const record = visible.find(item => item.id === state.selected) || visible[0];
  state.selected = record?.id;
  const index = visible.indexOf(record);
  $('position').textContent = record ? `${index + 1} / ${visible.length}` : '0 / 0';
  document.querySelectorAll('[data-action="prev"],[data-action="next"]').forEach(button => { button.disabled = visible.length < 2; });
  if (!record) {
    $('inspector-content').innerHTML = '<p class="empty">По фильтру ничего не найдено.</p>';
    renderMarkers();
    return;
  }
  const frame = frameById(record.frame);
  const box = frame?.boxes.find(item => item.id === record.box);
  const point = formatPoint(record.point);
  const source = sourceLink(record.source);
  const figure = frame ? `<div class="frame-panel">
    <figure class="frame"><img src="${escapeHTML(frame.src)}" alt="Кадр объекта ${escapeHTML(record.id)}">${state.overlay ? boxHTML(box) + frame.boxes.filter(item => item.source === 'manual' && item.id !== record.box).map(item => boxHTML(item)).join('') : ''}</figure>
    <div class="frame-tools"><div class="frame-toggle"><button data-action="original" aria-pressed="${!state.overlay}">Исходник</button><button data-action="overlay" aria-pressed="${state.overlay}">Разметка</button></div><button class="button" data-frame="${escapeHTML(frame.id)}">Править рамки ↗</button></div>
  </div>` : '<p class="empty">К этому объекту кадр не привязан.</p>';
  $('inspector-content').innerHTML = `<div class="record-head"><div class="record-id"><span class="mono">${escapeHTML(displayId(record))}</span>${status(record)}</div><h2>${escapeHTML(record.type)}</h2>${record.place ? `<p class="subtle">${escapeHTML(record.place)}</p>` : ''}</div>
    ${figure}<div class="record-data"><dl><div><dt>Признак</dt><dd>${escapeHTML(record.issue ?? 'Нет данных о состоянии')}</dd></div>
    <div><dt>Уверенность модели</dt><dd>${!frame?.demo && Number.isFinite(record.confidence) ? record.confidence + '%' : '—'}</dd></div>
    <div><dt>${record.pointKind === 'asset' ? 'Координаты объекта' : record.pointKind === 'manual' ? 'Точка оператора' : 'Место наблюдения'}</dt><dd class="mono">${point}</dd></div>
    ${source ? `<div><dt>Источник координат</dt><dd>${source}</dd></div>` : ''}
    ${record.recommendation ? `<div><dt>Рекомендация</dt><dd>${escapeHTML(record.recommendation)}</dd></div>` : ''}
    <div><dt>Съёмка</dt><dd>${escapeHTML(frame?.time || '—')}</dd></div></dl>
    <div class="point-tools"><button class="button" data-action="move-point">${isValidPoint(record.point) ? 'Переместить точку' : 'Поставить на карту'}</button>
    ${isValidPoint(record.point) ? '<button class="button" data-action="delete-point">Удалить точку</button>' : ''}</div>
    ${frame ? `<p class="subtle mono">${escapeHTML(frame.name)}</p>` : ''}</div>`;
  renderMarkers();
}

function renderTotals() {
  const review = records.objects.filter(record => record.priority === 'review' || record.priority === 'urgent').length;
  const urgent = records.objects.filter(record => record.priority === 'urgent').length;
  $('totals').innerHTML = `<span class="total"><b>${records.objects.length}</b> объектов</span><span class="total"><b>${review}</b> к проверке</span><span class="total danger"><b>${urgent}</b> срочно</span>`;
}

function renderList() {
  const exportButton = '<button class="table-link" data-action="export-json">Скачать JSON</button>';
  if (state.view === 'registry') {
    const rows = records.objects.map(record => `<tr><td class="mono">${escapeHTML(displayId(record))}</td><td>${escapeHTML(record.type)}</td><td>${escapeHTML(record.issue ?? '—')}</td><td>${status(record)}</td><td>${escapeHTML(record.place || formatPoint(record.point))}</td><td><button class="table-link" data-record="${escapeHTML(record.id)}">${isValidPoint(record.point) ? 'На карте ↗' : 'Карточка ↗'}</button></td></tr>`).join('');
    $('list-view').innerHTML = `<div class="table-shell"><table><thead><tr><th>ID</th><th>Объект</th><th>Признак</th><th>Статус</th><th>Место</th><th>Просмотр</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    return;
  }
  const rows = records.frames.map(frame => `<tr><td><span class="file-cell"><img src="${escapeHTML(frame.src)}" alt="">${escapeHTML(frame.name)}</span></td><td class="mono">${escapeHTML(frame.time)}</td><td>${frame.boxes.length}</td><td>${records.objects.filter(record => record.frame === frame.id).length}</td><td><button class="table-link" data-frame="${escapeHTML(frame.id)}">Открыть кадр ↗</button></td><td><button class="table-link" data-place="${escapeHTML(frame.id)}">Поставить точку</button></td></tr>`).join('');
  $('list-view').innerHTML = `<div class="table-shell"><table><thead><tr><th>Снимок</th><th>Дата</th><th>Рамки</th><th>Точки</th><th>Разметка</th><th>Местоположение</th></tr></thead><tbody>${rows}</tbody></table></div><p style="margin-top:9px">${exportButton}</p>`;
}

function switchView(view) {
  if (view !== 'map') drivePlayer?.exit();
  state.view = view;
  $('map-view').hidden = view !== 'map';
  $('list-view').hidden = view === 'map';
  const pageTitle = $('page-title');
  pageTitle.textContent = {registry: 'Реестр объектов', history: 'История снимков'}[view] ?? '';
  pageTitle.hidden = view === 'map';
  document.querySelectorAll('[data-view]').forEach(button => button.setAttribute('aria-pressed', button.dataset.view === view));
  if (view === 'map') {
    renderSelection();
  } else {
    resetPin();
    renderList();
  }
}

let inspectionMap;
let drivePlayer;
let drivingRoute;
let routeUnavailable = false;
let backendConnected = false;
let mapError;
let mapLoading = false;
const mapKeyStorage = 'mgts-dgis-map-tiles-key';
const mapErrorMessages = {
  'sdk-request': 'Не загрузился MapGL 2ГИС',
  'sdk-timeout': 'Истекло время загрузки MapGL 2ГИС',
  'tiles-timeout': 'Тайлы 2ГИС не загрузились',
  key: '2ГИС отклонил ключ Map Tiles API',
  style: 'Не загрузился стиль карты 2ГИС',
  render: 'Ошибка при запуске карты 2ГИС'
};

function savedMapKey() {
  try {
    const key = localStorage.getItem(mapKeyStorage);
    if (key) return key;
  } catch {}

  let sessionKey;
  try {
    sessionKey = sessionStorage.getItem(mapKeyStorage);
  } catch {}
  if (!sessionKey) return '';

  try {
    localStorage.setItem(mapKeyStorage, sessionKey);
    sessionStorage.removeItem(mapKeyStorage);
  } catch {}
  return sessionKey;
}

function openMapSettings() {
  $('map-key-input').value = savedMapKey();
  $('map-key-reset').hidden = !$('map-key-input').value;
  $('map-settings-note').textContent = {
    key: 'Проверьте доступ к Map Tiles API и срок действия ключа в Менеджере Платформы.',
    'tiles-timeout': 'Проверьте доступ ключа к Map Tiles API и попробуйте снова.',
    render: 'Для карты нужен браузер с доступным WebGL.'
  }[mapError] ?? 'Подойдёт демо-ключ 2ГИС с доступом к Map Tiles API.';
  $('map-settings').showModal();
}

function changeMapKey(key) {
  try {
    if (key) localStorage.setItem(mapKeyStorage, key);
    else localStorage.removeItem(mapKeyStorage);
  } catch {
    $('map-settings-note').textContent = 'Не удалось сохранить ключ. Проверьте настройки хранилища браузера.';
    return;
  }
  try {
    sessionStorage.removeItem(mapKeyStorage);
  } catch {}
  location.reload();
}

function displayedRoute() {
  if (routeUnavailable) return [];
  return drivingRoute?.points ?? records.route;
}

function setMapStatus() {
  const statusElement = $('map-status');
  const connected = Boolean(inspectionMap);
  const message = state.pin ? (state.moveId ? 'Выберите новое место точки. Esc — отмена.' : 'Нажмите на карту, чтобы сохранить точку.') :
    mapLoading ? 'Загрузка 2ГИС…' :
    mapError ? mapErrorMessages[mapError] : connected ? (routeUnavailable ? '2ГИС не построил автомобильный маршрут.' : '') :
    'Подключите 2ГИС, чтобы открыть маршрут и точки.';
  statusElement.textContent = message;
  statusElement.hidden = !message;
  $('pin-button').setAttribute('aria-pressed', state.pin);
  $('pin-button').hidden = !connected;
  const hasRoute = displayedRoute().length > 1;
  $('fit-button').hidden = !connected || !hasRoute && !records.objects.some(record => isValidPoint(record.point));
  $('fit-button').textContent = hasRoute ? 'Весь маршрут' : 'Все точки';
  $('provider-zoom').hidden = !connected;
  $('map').classList.toggle('map-active', connected);
  $('map').classList.toggle('placing-point', state.pin);
  $('map-provider').textContent = connected ? '2ГИС' : 'Подключить 2ГИС';
}

function createMarkerButton(record) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'map-mark ' + priorityOf(record);
  button.setAttribute('aria-label', displayId(record) + ' · ' + record.type);
  button.dataset.record = record.id;
  button.title = displayId(record) + ' · ' + (record.issue ?? record.type);
  return button;
}

function renderMarkers() {
  inspectionMap?.setMarkers(visibleObjects().filter(record => isValidPoint(record.point)), state.selected);
}

async function startMap() {
  const key = savedMapKey() || document.querySelector('meta[name="mgts-dgis-api-key"]').content.trim();
  if (!key) {
    setMapStatus();
    return;
  }
  mapLoading = true;
  setMapStatus();
  try {
    if (Array.isArray(records.drivingStops) && records.drivingStops.length > 1) {
      try {
        drivingRoute = await loadDgisDrivingRoute(key, records.drivingStops);
        records.route = drivingRoute.points;
        records.routeSource = {kind: 'driving', label: 'Маршрут 2ГИС', distance: drivingRoute.distance, duration: drivingRoute.duration};
      } catch {
        records.route = [];
        delete records.routeSource;
        routeUnavailable = true;
      }
    }
    inspectionMap = await initDgisMap({
      container: $('map'), key, route: displayedRoute(),
      points: records.objects.map(record => record.point).filter(isValidPoint),
      markerButton: createMarkerButton,
      onSelect: id => {
        const record = records.objects.find(item => item.id === id);
        if (state.pin && isValidPoint(record?.point)) addPoint(record.point);
        else showRecord(id);
      },
      onPoint: point => { if (state.pin) addPoint(point); }
    });
    if (drivingRoute) {
      drivePlayer = createDrivePlayer(inspectionMap, drivingRoute, resetPin);
      $('route-credit').textContent = 'Маршрут 2ГИС';
    } else if (displayedRoute().length > 1 && records.routeSource) {
      $('route-credit').innerHTML = sourceLink(records.routeSource);
    }
  } catch (error) {
    mapError = error instanceof DgisMapError ? error.code : 'render';
  }
  mapLoading = false;
  setMapStatus();
  renderMarkers();
}

function resetPin() {
  state.pin = false;
  state.pinFrame = null;
  state.pinBox = null;
  state.moveId = null;
  setMapStatus();
}

function startPin(frameId = null, boxId = null, moveId = null) {
  if (!inspectionMap) {
    switchView('map');
    openMapSettings();
    return;
  }
  switchView('map');
  drivePlayer?.exit();
  state.pin = true;
  state.moveId = moveId;
  state.pinFrame = frameId;
  state.pinBox = boxId;
  setMapStatus();
}

function addPoint([longitude, latitude]) {
  // A repeated world tile can report a longitude outside the canonical range.
  const lng = Math.abs(longitude) > 180 ? ((longitude + 180) % 360 + 360) % 360 - 180 : longitude;
  const point = [lng, latitude];
  if (!isValidPoint(point)) {
    announce('Не удалось определить координаты точки.');
    return;
  }
  const coordinates = point.map(value => Number(number(value)));
  if (state.moveId) {
    const record = records.objects.find(item => item.id === state.moveId);
    resetPin();
    if (record) {
      setOperatorPoint(record, coordinates);
      showRecord(record.id);
      persist('Положение точки сохранено в этом браузере.');
    }
    return;
  }
  const frame = frameById(state.pinFrame);
  const box = frame?.boxes.find(item => item.id === state.pinBox) || frame?.boxes[0];
  const id = 'РУЧ-' + newId().slice(0,6).toUpperCase();
  records.objects.push({id, type: box?.label || 'Ручная отметка', issue:'Назначено на ручную проверку', priority:'review', place:'', origin:'manual', frame:frame?.id, box:box?.id, point:coordinates, pointKind:'manual'});
  resetPin();
  state.filter = $('priority-filter').value = 'all';
  showRecord(id);
  renderTotals();
  persist('Точка добавлена в реестр.');
}

function setOperatorPoint(record, point) {
  record.point = point;
  record.pointEdited = true;
  record.pointKind = 'manual';
  record.place = '';
  delete record.source;
}

function deletePoint() {
  const record = records.objects.find(item => item.id === state.selected);
  if (!record || !isValidPoint(record.point)) return;
  const manual = record.origin === 'manual';
  const question = manual ? 'Удалить ручную отметку из карты и реестра?' : 'Удалить точку с карты? Карточка объекта и рамки останутся в реестре.';
  if (!window.confirm(displayId(record) + ' · ' + question)) return;
  resetPin();
  if (manual) records.objects = records.objects.filter(item => item !== record);
  else setOperatorPoint(record, null);
  renderSelection();
  renderTotals();
  persist('Точка удалена в этом браузере.');
}

const editor = {frame: null, boxes: [], selected: null, mode: 'draw', drag: null};

function openEditor(id) {
  const frame = frameById(id);
  if (!frame) return;
  editor.frame = frame;
  editor.boxes = frame.boxes.map(box => ({...box}));
  editor.selected = null;
  editor.mode = 'draw';
  editor.drag = null;
  $('editor-filename').textContent = frame.name;
  $('edit-photo').src = frame.src;
  $('editor-hint').textContent = 'Протяните от одного угла рамки до противоположного.';
  renderEditor();
  $('annotator').showModal();
}

function renderEditor() {
  const selected = editor.boxes.find(box => box.id === editor.selected);
  $('edit-boxes').innerHTML = editor.boxes.map(box => boxHTML(box, box.id === editor.selected)).join('');
  $('boxes-list').innerHTML = editor.boxes.length ? editor.boxes.map(box => `<button class="box-row" data-box="${escapeHTML(box.id)}" aria-pressed="${box.id === editor.selected}"><span>${escapeHTML(box.label)}</span><span class="subtle">${box.source === 'manual' ? 'Вручную' : box.source === 'demo' ? 'Демо' : 'Модель'}</span></button>`).join('') : '<p class="subtle">Пока нет рамок.</p>';
  document.querySelector('[data-action="delete-box"]').disabled = !selected;
  document.querySelector('[data-action="redraw"]').disabled = !selected;
  document.querySelector('[data-action="redraw"]').setAttribute('aria-pressed', editor.mode === 'redraw');
  document.querySelector('[data-action="draw"]').setAttribute('aria-pressed', editor.mode === 'draw');
}

function photoPoint(event) {
  const bounds = $('editor-image').getBoundingClientRect();
  const clamp = value => Math.min(1, Math.max(0,value));
  return [clamp((event.clientX - bounds.left) / bounds.width),clamp((event.clientY - bounds.top) / bounds.height)];
}

function rectangle(start,end) {
  return {x: Math.min(start[0],end[0]), y:Math.min(start[1],end[1]), w:Math.abs(end[0]-start[0]), h:Math.abs(end[1]-start[1])};
}

const canvas = $('editor-image');
canvas.addEventListener('pointerdown', event => {
  if (event.button !== 0 || editor.drag || !$('edit-photo').naturalWidth) return;
  editor.drag = {id:event.pointerId, start:photoPoint(event)};
  canvas.setPointerCapture(event.pointerId);
});
canvas.addEventListener('pointermove', event => {
  if (editor.drag?.id !== event.pointerId) return;
  const box = {...rectangle(editor.drag.start,photoPoint(event)), source:'manual', label:$('box-type').value};
  $('edit-boxes').innerHTML = editor.boxes.filter(item => editor.mode !== 'redraw' || item.id !== editor.selected).map(item => boxHTML(item,item.id === editor.selected)).join('') + boxHTML(box,false,false);
});
canvas.addEventListener('pointerup', event => {
  if (editor.drag?.id !== event.pointerId) return;
  const bounds = rectangle(editor.drag.start,photoPoint(event));
  editor.drag = null;
  if (bounds.w < .008 || bounds.h < .008) { renderEditor(); return; }
  const box = {id: editor.mode === 'redraw' ? editor.selected : newId(), label:$('box-type').value, source:'manual', ...bounds};
  if (editor.mode === 'redraw') editor.boxes = editor.boxes.map(item => item.id === box.id ? box : item);
  else editor.boxes.push(box);
  editor.selected = box.id;
  editor.mode = 'draw';
  renderEditor();
});
canvas.addEventListener('pointercancel', () => { editor.drag = null; renderEditor(); });

function openBoxJSON() {
  $('box-json-text').value = JSON.stringify(editor.boxes, null, 2);
  $('box-json-file').value = '';
  $('box-json-error').textContent = '';
  $('box-json-dialog').showModal();
}

function validatedBoxes(text) {
  let boxes;
  try { boxes = JSON.parse(text); }
  catch { throw new Error('Не удалось прочитать JSON. Проверьте скобки, кавычки и запятые.'); }
  if (Array.isArray(boxes?.frames)) {
    const frame = boxes.frames.find(item => item?.id === editor.frame.id);
    if (!frame) throw new Error('В этом файле нет разметки выбранного кадра.');
    boxes = frame.boxes;
  }
  if (!Array.isArray(boxes)) throw new Error('Ожидается массив рамок. Для пустого кадра укажите [].');
  const ids = new Set();
  const previous = new Map(editor.boxes.map(box => [box.id, box]));
  return boxes.map((box, index) => {
    const row = 'Рамка ' + (index + 1) + '. ';
    if (typeof box?.label !== 'string' || !box.label.trim()) throw new Error(row + 'Введите название класса в label.');
    const id = box.id ?? newId();
    if (typeof id !== 'string' || !id.trim() || ids.has(id)) throw new Error(row + 'Нужен уникальный текстовый id.');
    ids.add(id);
    const {x, y, w, h} = box;
    if (![x,y,w,h].every(Number.isFinite) || x < 0 || y < 0 || w <= 0 || h <= 0 ||
        x + w > 1 + 1e-10 || y + h > 1 + 1e-10) throw new Error(row + 'Прямоугольник должен целиком помещаться в снимке.');
    const label = box.label.trim();
    const old = previous.get(id);
    const unchanged = old && old.label === label && old.x === x && old.y === y && old.w === w && old.h === h;
    return {id, label, x, y, w, h, source: unchanged ? old.source : 'manual'};
  });
}

function applyBoxJSON() {
  try {
    editor.boxes = validatedBoxes($('box-json-text').value);
    editor.selected = null;
    editor.mode = 'draw';
    renderEditor();
    $('box-json-dialog').close();
    $('editor-hint').textContent = 'Проверьте рамки на снимке и нажмите «Сохранить».';
  } catch (error) {
    $('box-json-error').textContent = error.message;
  }
}

$('box-json-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    const text = await file.text();
    validatedBoxes(text);
    $('box-json-text').value = text;
    $('box-json-error').textContent = '';
  } catch (error) {
    $('box-json-error').textContent = error.message;
  }
});

function updateBoxReference(record, frame) {
  const box = frame.boxes.find(item => item.id === record.box);
  if (!box) delete record.box;
  else if (box.source === 'manual') {
    if (record.type !== box.label) record.issue = 'Класс уточнён вручную';
    record.type = box.label;
    delete record.confidence;
  }
}

function saveBoxes() {
  const frame = editor.frame;
  frame.boxes = editor.boxes;
  if (frame.backend) frame.localEdits = true;
  for (const record of records.objects) {
    if (record.frame === frame.id && record.box) updateBoxReference(record, frame);
  }
  $('annotator').close();
  if (state.view === 'map') renderSelection();
  else renderList();
  persist('Рамки сохранены в этом браузере.');
}

async function imagePreview(file) {
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    const scale = Math.min(1, 1280 / Math.max(image.naturalWidth, image.naturalHeight));
    const resized = document.createElement('canvas');
    resized.width = Math.round(image.naturalWidth * scale);
    resized.height = Math.round(image.naturalHeight * scale);
    resized.getContext('2d').drawImage(image,0,0,resized.width,resized.height);
    return resized.toDataURL('image/jpeg',.83);
  } finally {
    URL.revokeObjectURL(url);
  }
}

$('upload-form').addEventListener('submit', async event => {
  event.preventDefault();
  const input = $('file');
  const file = input.files[0];
  const submit = event.currentTarget.querySelector('[type="submit"]');
  if (!file || submit.disabled) return;
  submit.disabled = true;
  $('upload-message').textContent = 'Читаем снимок…';
  try {
    if (file.size > 25 * 1024 * 1024) throw new Error('Выберите снимок до 25 МБ.');
    const frame = backendConnected ? await uploadBackendPhoto(file) : {
      id: newId(), name: file.name, src: await imagePreview(file),
      time: 'Добавлено ' + new Date().toLocaleString('ru-RU', {dateStyle:'short',timeStyle:'short'}), boxes: []
    };
    records.frames.unshift(frame);
    input.value = '';
    $('upload-dialog').close();
    switchView('history');
    persist(backendConnected ? 'Фото загружено в бэкенд.' : 'Снимок добавлен для ручной разметки.');
    openEditor(frame.id);
  } catch (error) {
    $('upload-message').textContent = error.message === 'Выберите снимок до 25 МБ.' ? error.message :
      backendConnected ? 'Не удалось загрузить фото в бэкенд.' : 'Не удалось открыть изображение. Попробуйте JPEG, PNG или WebP.';
  } finally {
    submit.disabled = false;
  }
});

function download(content,type,name) {
  const url = URL.createObjectURL(new Blob([content],{type}));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = name;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function exportCSV() {
  const rows = [['ID','Объект','Признак','Статус','Место','Широта','Долгота','Источник']];
  for (const r of records.objects) rows.push([displayId(r),r.type,r.issue ?? '',priorities[priorityOf(r)],r.place,r.point?.[1] ?? '',r.point?.[0] ?? '',r.source?.url ?? '']);
  const text = rows.map(row => row.map(value => '"' + String(value).replaceAll('"','""') + '"').join(';')).join('\r\n');
  download('\ufeff' + text,'text/csv;charset=utf-8','mgts-objects.csv');
}

function exportJSON() {
  download(JSON.stringify(records,null,2),'application/json','mgts-annotations.json');
}

function step(direction) {
  const visible = visibleObjects();
  if (!visible.length) return;
  const index = visible.findIndex(record => record.id === state.selected);
  showRecord(visible[(index + direction + visible.length) % visible.length].id, true);
}

const actions = {
  fit: () => {
    drivePlayer?.exit();
    const route = displayedRoute();
    inspectionMap?.fitPoints(route.length > 1 ? route : records.objects.map(record => record.point).filter(isValidPoint));
  },
  pin: () => state.pin ? resetPin() : startPin(), prev: () => step(-1), next: () => step(1),
  'map-settings': openMapSettings,
  'close-map-settings': () => $('map-settings').close(),
  'reset-map-key': () => changeMapKey(''),
  'zoom-in': () => inspectionMap?.zoom(1),
  'zoom-out': () => inspectionMap?.zoom(-1),
  original: () => { state.overlay = false; renderSelection(); document.querySelector('[data-action="original"]')?.focus({preventScroll:true}); },
  overlay: () => { state.overlay = true; renderSelection(); document.querySelector('[data-action="overlay"]')?.focus({preventScroll:true}); },
  'close-editor': () => $('annotator').close(),
  draw: () => { editor.mode = 'draw'; renderEditor(); },
  redraw: () => { editor.mode = 'redraw'; renderEditor(); $('editor-hint').textContent = 'Протяните новую рамку для выбранного объекта.'; },
  'delete-box': () => { editor.boxes = editor.boxes.filter(box => box.id !== editor.selected); editor.selected = null; editor.mode = 'draw'; renderEditor(); },
  'save-boxes': saveBoxes,
  'move-point': () => startPin(null, null, state.selected),
  'delete-point': deletePoint,
  'box-json': openBoxJSON,
  'close-json': () => $('box-json-dialog').close(),
  'apply-json': applyBoxJSON,
  'export-boxes': () => {
    try {
      const boxes = validatedBoxes($('box-json-text').value);
      $('box-json-text').value = JSON.stringify(boxes, null, 2);
      $('box-json-error').textContent = '';
      download($('box-json-text').value, 'application/json', editor.frame.id + '-boxes.json');
    } catch (error) {
      $('box-json-error').textContent = error.message;
    }
  },
  upload: () => { $('upload-message').textContent = 'Снимок откроется для ручной разметки.'; $('upload-dialog').showModal(); },
  'close-upload': () => $('upload-dialog').close(), export: exportCSV, 'export-json': exportJSON
};

document.addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button) return;
  const data = button.dataset;
  if (data.view) switchView(data.view);
  if (data.action) actions[data.action]?.();
  if (data.record) {
    if (state.view !== 'map') {
      state.filter = $('priority-filter').value = 'all';
      switchView('map');
    }
    showRecord(data.record, true);
  }
  if (data.frame) openEditor(data.frame);
  if (data.place) startPin(data.place);
  if (data.box) {
    editor.selected = data.box;
    const label = editor.boxes.find(box => box.id === data.box)?.label;
    const type = $('box-type');
    type.value = [...type.options].some(option => option.value === label) ? label : 'Другое';
    renderEditor();
    [...$('boxes-list').querySelectorAll('button')].find(item => item.dataset.box === data.box)?.focus({preventScroll:true});
  }
});
$('priority-filter').addEventListener('change', event => { state.filter = event.target.value; renderSelection(); });
$('map-settings-form').addEventListener('submit', event => {
  event.preventDefault();
  const key = $('map-key-input').value.trim();
  if (key) changeMapKey(key);
  else $('map-settings-note').textContent = 'Введите ключ Map Tiles API.';
});
document.addEventListener('keydown', event => { if (event.key === 'Escape' && state.pin) resetPin(); });
function savedInspection() {
  try {
    const saved = JSON.parse(localStorage.getItem(savedKey));
    return Array.isArray(saved?.frames) && Array.isArray(saved?.objects) ? saved : null;
  } catch {
    return null;
  }
}

function mergeInspection(dataset, saved) {
  if (!saved) return dataset;
  if (saved.datasetId && saved.datasetId !== dataset.datasetId) return dataset;
  if (saved.datasetId) return {...dataset, frames: saved.frames, objects: saved.objects};

  const demoFrames = new Map(dataset.frames.filter(frame => frame.demo).map(frame => [frame.id, frame]));
  const existing = new Set(saved.frames.map(frame => frame.id));
  const frames = saved.frames.map(frame => {
    const demo = demoFrames.get(frame.id);
    if (!demo) return frame;
    return {...demo, boxes: frame.boxes.map(box => box.source === 'model' ? {...box, source: 'demo'} : box)};
  }).concat(dataset.frames.filter(frame => !existing.has(frame.id)));
  const manual = saved.objects.filter(record => record.origin === 'manual');
  return {...dataset, frames, objects: [...dataset.objects, ...manual]};
}

async function loadInspection() {
  try {
    const url = document.querySelector('meta[name="mgts-inspection-data"]').content;
    const response = await fetch(url);
    if (!response.ok) throw new Error('Inspection data unavailable');
    const data = await response.json();
    if (data.schemaVersion !== 1 || typeof data.datasetId !== 'string' ||
      !Array.isArray(data.frames) || !Array.isArray(data.objects)) throw new Error('Invalid inspection data');
    const route = Array.isArray(data.route) ? data.route.filter(isValidPoint) : [];
    records = mergeInspection({...records, ...data, route}, savedInspection());
  } catch {
    const saved = savedInspection();
    if (saved?.datasetId && saved.schemaVersion === 1) records = saved;
    announce('Не удалось загрузить JSON обследования.');
  }
  try {
    const backend = await loadBackendInspection();
    const editedFrames = new Map(records.frames.filter(frame => frame.backend && frame.localEdits).map(frame => [frame.id, frame]));
    records.frames = [...backend.frames.map(frame => {
      const edited = editedFrames.get(frame.id);
      return edited ? {...frame, boxes: edited.boxes, localEdits: true} : frame;
    }), ...records.frames.filter(frame => !frame.backend)];
    const savedObjects = new Map(records.objects.filter(item => item.origin === 'backend').map(item => [item.id, item]));
    for (const record of backend.objects) {
      const saved = savedObjects.get(record.id);
      if (saved?.pointEdited) setOperatorPoint(record, saved.point);
      const frame = frameById(record.frame);
      if (frame?.localEdits && record.box) updateBoxReference(record, frame);
    }
    records.objects = [...backend.objects, ...records.objects.filter(record => record.origin !== 'backend')];
    backendConnected = true;
    $('data-mode').textContent = 'Локальный API · демоданные';
  } catch {
    $('data-mode').textContent = 'Демоданные · API недоступен';
  }
  document.querySelector('[data-action="upload"]').disabled = false;
  renderTotals();
  renderSelection();
  if (state.view !== 'map') renderList();
  startMap();
}

loadInspection();
