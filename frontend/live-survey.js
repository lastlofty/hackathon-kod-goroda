'use strict';

const liveSurvey = {active: false, heldFrame: null, baseline: new Set(), centered: null};
let selectedClass = '';
let recordClasses = new Map();
let liveFrameIds = new Set();

function className(label) {
  const value = (label || '').trim();
  if (/опор[аы]|фонар|^pole$|^lighting$/i.test(value)) return 'Опоры';
  if (/шкаф|^cabinet$/i.test(value)) return 'Шкафы';
  if (/колод|люк|^manhole$/i.test(value)) return 'Колодцы';
  if (/светофор|^traffic light$/i.test(value)) return 'Светофоры';
  if (/остановк|^bus stop$/i.test(value)) return 'Остановки';
  return value;
}

function isLiveFrame(frame) {
  return Boolean(frame?.backend && !frame.demo);
}

function matchesClass(record) {
  return !selectedClass || recordClasses.get(record.id)?.has(selectedClass);
}

function buildClassFilters() {
  const counts = new Map();
  recordClasses = new Map();
  const frames = new Map(records.frames.map(frame => [frame.id, frame]));
  liveFrameIds = new Set(records.frames.filter(isLiveFrame).map(frame => frame.id));
  const linkedBoxes = new Set(records.objects.filter(r => r.box).map(r => r.frame + '/' + r.box));
  const representative = new Map(records.objects.filter(r => r.frame).map(r => [r.frame, r.id]));
  const eligible = new Set(statusObjects().map(record => record.id));
  for (const record of records.objects) {
    const frame = frames.get(record.frame);
    if (liveSurvey.active && !isLiveFrame(frame)) continue;
    const labels = new Set();
    recordClasses.set(record.id, labels);
    function add(label, key) {
      const name = className(label);
      if (!name) return;
      labels.add(name);
      if (!eligible.has(record.id)) return;
      if (!counts.has(name)) counts.set(name, new Set());
      counts.get(name).add(key);
    }
    // Attribute each detection to its own point. A camera position can represent the entire frame.
    const detectionId = record.box || (record.origin === 'backend' && frame?.inference?.find(f => f.id === record.id)?.id);
    const boxes = frame?.boxes.filter(box => !detectionId || box.id === detectionId ||
      (representative.get(frame.id) === record.id && !linkedBoxes.has(frame.id + '/' + box.id)));
    for (const box of boxes || []) {
      if (boxVerdict(frame,box.id)?.decision !== 'rejected') add(checkedLabel(frame,box), frame.id + '/' + box.id);
    }
    for (const finding of frame?.inference || []) {
      if ((!detectionId || finding.id === detectionId) && !finding.geometry) add(finding.label || finding.category, frame.id + '/' + finding.id);
    }
    if (!boxes?.length && !labels.size && record.type !== 'Кадр проезда') add(record.type, record.id);
  }
  if (selectedClass && !counts.has(selectedClass)) counts.set(selectedClass, new Set());
  const html = ['<button type="button" data-survey-class="" aria-pressed="' + !selectedClass + '">Все классы</button>'];
  for (const [label, ids] of [...counts].sort(([a], [b]) => a.localeCompare(b, 'ru'))) {
    html.push(`<button type="button" data-survey-class="${escapeHTML(label)}" aria-pressed="${selectedClass === label}">${escapeHTML(label)} <span>${ids.size}</span></button>`);
  }
  const host = $('class-filters');
  if (host.innerHTML !== html.join('')) host.innerHTML = html.join('');
}

function latestLiveRecord() {
  const byFrame = new Map(visibleObjects().map(record => [record.frame, record]));
  let latest = null;
  for (const frame of records.frames) {
    if (!byFrame.has(frame.id)) continue;
    if (!latest || (frame.capturedMs || 0) > (latest.capturedMs || 0) ||
        (frame.capturedMs === latest.capturedMs && frame.id > latest.id)) latest = frame;
  }
  return byFrame.get(latest?.id);
}

function renderLiveStatus() {
  const {active, heldFrame, baseline} = liveSurvey;
  $('live-toggle').setAttribute('aria-pressed', String(active));
  $('live-event').hidden = !active || !isLiveFrame(frameById(records.objects.find(r=>r.id===state.selected)?.frame));
  $('live-return').hidden = !active || !heldFrame;
  $('live-status').hidden = !active;
  if (!active) return;
  if (heldFrame) {
    const arrivals = new Set(visibleObjects().map(r => r.frame).filter(id => id && !baseline.has(id)));
    $('live-return').textContent = 'К последнему кадру' + (arrivals.size ? ' · +' + arrivals.size : '');
  }
  const connected = inspectionStream?.readyState === 1;
  $('live-status').textContent = connected ? (heldFrame ? 'Просмотр кадра' : latestLiveRecord() ? 'В эфире' : 'Ожидание кадров') :
    inspectionStream?.readyState === 0 ? 'Подключение к потоку…' : 'Поток недоступен';
}

function holdLive(frameId = records.objects.find(r => r.id === state.selected)?.frame) {
  if (!liveSurvey.active || !frameId) return;
  if (!liveSurvey.heldFrame) liveSurvey.baseline = new Set(records.frames.filter(isLiveFrame).map(f => f.id));
  liveSurvey.heldFrame = frameId;
  renderLiveStatus();
}

function syncLiveSelection() {
  if (!liveSurvey.active) return;
  const visible = visibleObjects();
  const held = liveSurvey.heldFrame;
  const current = visible.find(r => r.id === state.selected);
  const record = held ? (current?.frame === held ? current : visible.find(r => r.frame === held)) : latestLiveRecord();
  if (held && !record) liveSurvey.heldFrame = null;
  const target = record || latestLiveRecord();
  state.selected = target?.id;
  if (target && !liveSurvey.heldFrame) {
    const frame = frameById(target.frame);
    const routeId = frame?.routeId || target.routeId;
    if (routeId && currentSurveyRoute()?.id !== routeId) {
      const choice = drivingRoutes.find(route => route.id === routeId);
      if (inspectionMap && choice) activateRoute(choice, false);
      else if (records.routes?.some(route => route.id === routeId)) $('route-select').value = routeId;
    }
    const point = frame?.cameraPoint || target.point;
    const location = target.frame + '/' + point;
    if (inspectionMap && isValidPoint(point) && location !== liveSurvey.centered) {
      inspectionMap.panTo(point);
      liveSurvey.centered = location;
    }
  }
}

function setLiveMode(active) {
  if (active) {
    sectionView.enabled = sectionView.showList = false;
    drivePlayer?.exit();
    resetPin();
  }
  liveSurvey.active = active;
  liveSurvey.heldFrame = liveSurvey.centered = null;
  liveSurvey.baseline.clear();
  state.focusBox = null;
  if (active && state.filter === 'retake') state.filter = $('priority-filter').value = 'all';
  renderDeck();
  renderSelection();
}

function routeCoverage(route, shots) {
  const host = $('coverage');
  host.hidden = !route?.points?.length || state.filter === 'retake' || (liveSurvey.active && !shots.length);
  if (host.hidden) return;
  const length = route.distance;
  if (!(length > 0)) { host.hidden = true; return; }
  const fractions = [...new Set(shots.map(shot => shot.fraction))].sort((a,b) => a-b);
  const intervals = [0, ...fractions, 1];
  const bands = [];
  for (let i = 1; i < intervals.length; i++) {
    const a = intervals[i-1], b = intervals[i], metres = Math.round((b-a)*length);
    if (metres < 1) continue;
    const place = !fractions.length ? 'Участок без привязанных снимков' : i === 1 ? 'От старта до первого кадра' :
      i === intervals.length - 1 ? 'От последнего кадра до финиша' : 'Между соседними кадрами';
    const label = place + ' · ' + metres + ' м';
    bands.push(`<button type="button" class="coverage-gap${metres >= 100 ? ' long' : ''}" style="left:${a*100}%;width:${(b-a)*100}%" data-gap="${label}" title="${label}" aria-label="${label}"></button>`);
  }
  const ticks = fractions.map(value => `<i style="left:${value*100}%"></i>`);
  $('coverage-track').innerHTML = bands.concat(ticks).join('');
  $('coverage-detail').textContent = 'Интервалы от 100 м выделены';
}

function bindSurveyTools() {
  $('live-toggle').onclick = () => setLiveMode(!liveSurvey.active);
  $('live-return').onclick = () => setLiveMode(true);
  $('class-filters').onclick = event => {
    const button = event.target.closest('[data-survey-class]');
    if (!button) return;
    selectedClass = button.dataset.surveyClass;
    state.focusBox = null;
    renderDeck();
    renderSelection();
    [...$('class-filters').children].find(el => el.dataset.surveyClass === selectedClass)?.focus({preventScroll:true});
  };
  const describe = event => {
    if (event.target.dataset.gap) $('coverage-detail').textContent = event.target.dataset.gap;
  };
  for (const type of ['pointerover','focusin','click']) $('coverage-track').addEventListener(type, describe);
}
