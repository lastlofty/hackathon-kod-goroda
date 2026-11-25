'use strict';

const reviewNames = {confirmed: 'Подтверждено', unseen: 'Не видно на кадре'};
let queueOnly = false;
let noteTarget;

const reviewMarks = {
  pending: ['○', 'Ожидает проверки'],
  confirmed: ['✓', 'Подтверждено'],
  unseen: ['◌', 'Не видно на кадре'],
  flagged: ['⚑', 'Отмечена проблема']
};

function reviewState(record) {
  const review = record.inspectionReview;
  if (review?.note) return 'flagged';
  return Object.hasOwn(reviewNames, review?.decision) ? review.decision : 'pending';
}

function recordChange(action, record, frame) {
  (records.changes ??= []).push({
    time: new Date().toISOString(), action, recordId: record?.id, frameId: frame?.id || record?.frame,
    label: record ? displayId(record) + ' · ' + record.type : frame.name
  });
}

let historyObject = '';
function historyLog() {
  const changes = records.changes || [];
  if (!changes.length) return '<section class="change-log"><h2>Журнал правок</h2><p class="subtle">Здесь появятся изменения точек, рамок и решения по кадрам.</p></section>';
  const objects = new Map(changes.filter(change => change.recordId).map(change => [change.recordId, change.label]));
  const options = [...objects].map(([id, label]) => `<option value="${escapeHTML(id)}" ${id === historyObject ? 'selected' : ''}>${escapeHTML(label)}</option>`).join('');
  const rows = changes.filter(change => !historyObject || change.recordId === historyObject).slice().reverse().map(change => {
    const exists = records.objects.some(record => record.id === change.recordId);
    const label = escapeHTML(change.label);
    return `<tr><td class="mono">${new Date(change.time).toLocaleString('ru-RU', {dateStyle:'short',timeStyle:'short'})}</td><td>${exists ? `<button class="table-link" data-record="${escapeHTML(change.recordId)}">${label}</button>` : label}</td><td>${escapeHTML(change.action)}</td></tr>`;
  }).join('');
  return `<section class="change-log"><div class="change-head"><h2>Журнал правок</h2><select aria-label="Объект в журнале" id="history-object"><option value="">Все объекты</option>${options}</select></div><div class="table-shell"><table><thead><tr><th>Когда</th><th>Объект или кадр</th><th>Изменение</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

async function copyRecordLink() {
  const record = records.objects.find(r => r.id === state.selected);
  if (!record) return;
  const params = new URLSearchParams({point:record.id});
  const routeId = record.routeId || currentSurveyRoute()?.id;
  if (routeId) params.set('route', routeId);
  if (record.frame) params.set('frame', record.frame);
  const url = new URL(location.pathname, location.origin);
  url.hash = params.toString();
  try {
    await navigator.clipboard.writeText(url.href);
    announce('Ссылка на объект скопирована.');
  } catch {
    window.prompt('Скопируйте ссылку на объект', url.href);
  }
}

function openRecordLink() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.has('point')) return;
  const record = records.objects.find(r => r.id === params.get('point'));
  if (!record) {
    announce('Объект из ссылки отсутствует в этом наборе данных.');
    return;
  }
  openSurveyRecord(record, params.get('route'));
  if (params.has('frame') && params.get('frame') !== record.frame) announce('У объекта изменился привязанный кадр.');
}

function openSurveyRecord(record, preferredRoute) {
  if (liveSurvey.active) setLiveMode(false);
  if (!matchesClass(record)) selectedClass = '';
  const routeId = record.routeId || preferredRoute;
  const route = drivingRoutes.find(r => r.id === routeId);
  state.filter = $('priority-filter').value = 'all';
  if (state.view !== 'map') switchView('map');
  if (route && inspectionMap && drivingRoute !== route) activateRoute(route, false);
  else if ([...$('route-select').options].some(option => option.value === routeId)) {
    $('route-select').value = routeId;
    renderDeck();
  }
  renderDeck();
  showRecord(record.id, true);
}

function reviewShortcut(event) {
  if (event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.altKey ||
      event.metaKey || event.shiftKey || state.view !== 'map' || state.pin || document.querySelector('dialog[open]') ||
      event.target.closest('input, textarea, select, [contenteditable]:not([contenteditable="false"])')) return;
  const record = records.objects.find(r => r.id === state.selected);
  if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
    if (state.filter === 'retake') { event.preventDefault(); step(event.key === 'ArrowRight' ? 1 : -1); return; }
    const shots = [...$('route-frames').querySelectorAll('[data-shot]')];
    if (!shots.length) return;
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    const index = shots.findIndex(shot => shot.dataset.shot === state.selected);
    const next = index < 0 ? (direction > 0 ? 0 : shots.length - 1) : (index + direction + shots.length) % shots.length;
    event.preventDefault();
    shots[next].click();
    if (event.target.closest('[data-shot]')) shots[next].focus({preventScroll:true});
  } else if (record && frameById(record.frame)) {
    if (event.code === 'KeyE' || event.key.toLowerCase() === 'e') {
      event.preventDefault();
      openEditor(record.frame, record.box);
    } else if (event.key === 'Enter') {
      const control = event.target.closest('button, a, summary, [role="button"]');
      if (control && control.dataset.shot !== record.id) return;
      event.preventDefault();
      decideRecord('confirmed');
    }
  }
}

function currentSurveyRoute() {
  return (inspectionMap && drivingRoute) || records.routes?.find(route => route.id === $('route-select').value) || records.routes?.[0];
}

function routeRecords(route) {
  return route ? records.objects.filter(record => record.routeId === route.id) : [];
}

// Locate a roadside object along the polyline, including between routing vertices.
function fractionAlongRoute(point, path) {
  const scale = Math.cos(point[1] * Math.PI / 180);
  let length = 0, best = Infinity, offset = 0;
  for (let i = 1; i < path.length; i++) {
    const a = path[i - 1], b = path[i];
    const dx = (b[0] - a[0]) * scale, dy = b[1] - a[1];
    const segment = Math.hypot(dx, dy);
    if (!segment) continue;
    const px = (point[0] - a[0]) * scale, py = point[1] - a[1];
    const t = Math.max(0, Math.min(1, (px * dx + py * dy) / (segment * segment)));
    const distance = Math.hypot(px - t * dx, py - t * dy);
    if (distance < best) { best = distance; offset = length + t * segment; }
    length += segment;
  }
  return length ? offset / length : 0;
}

function renderDeck() {
  buildClassFilters();
  syncLiveSelection();
  const route = currentSurveyRoute();
  renderLiveStatus();
  const frames = new Map(records.frames.map(frame => [frame.id, frame]));
  const positions = new Map();
  const captures = new Map();
  for (const record of routeRecords(route)) {
    const frame = frames.get(record.frame);
    if (!frame) continue;
    const point = frame.cameraPoint || record.point;
    if (!isValidPoint(point)) continue;
    const fraction = fractionAlongRoute(point, route.points || []);
    positions.set(record.id, fraction);
    if ((!liveSurvey.active || isLiveFrame(frame)) && (isValidPoint(frame.cameraPoint) || record.pointKind === 'observation')) {
      captures.set(frame.id, {fraction});
    }
  }
  routeCoverage(route, [...captures.values()]);
  const shots = [];
  const used = new Set();
  for (const record of visibleObjects()) {
    const frame = frames.get(record.frame);
    if (!frame || used.has(frame.id)) continue;
    if (!liveSurvey.active && !selectedClass && !positions.has(record.id)) continue;
    used.add(frame.id);
    shots.push({record, frame, fraction: positions.get(record.id)});
  }
  if (liveSurvey.active) shots.sort((a,b) => (b.frame.capturedMs || 0) - (a.frame.capturedMs || 0));
  else shots.sort((a,b) => (a.fraction ?? Infinity) - (b.fraction ?? Infinity));
  $('deck-title').textContent = liveSurvey.active ? 'Кадры эфира' : selectedClass ? 'Кадры выбранного класса' : 'Кадры маршрута';
  $('seek-ticks').innerHTML = shots.filter(shot => shot.fraction !== undefined && !liveSurvey.active).map(({record, fraction}) => {
    const frame = frameById(record.frame);
    const state = reviewState(record);
    const [symbol, label] = reviewMarks[state];
    return `<button type="button" class="seek-mark" data-review="${state}" data-symbol="${symbol}" style="left:${100 * fraction}%" data-shot="${escapeHTML(record.id)}" data-fraction="${fraction}" aria-label="${escapeHTML(displayId(record))} · ${escapeHTML(recordLabel(record))} · ${label}"><span><img src="${escapeHTML(frame.src)}" alt="">${escapeHTML(recordLabel(record))} · ${label}</span></button>`;
  }).join('');
  updateSections(route);
  renderRouteSchematic(route);
  const pendingFrames = new Set(shots.filter(({record}) => reviewState(record) === 'pending').map(({record}) => record.frame));
  $('route-count').textContent = route || liveSurvey.active ? `Проверено ${shots.length - pendingFrames.size} из ${shots.length}` : '';
  $('route-frames').innerHTML = shots.map(({record, fraction}) => {
    const frame = frameById(record.frame);
    const review = reviewState(record);
    const [symbol, label] = reviewMarks[review];
    return `<button class="film-shot" data-review="${review}" data-symbol="${symbol}" data-shot="${escapeHTML(record.id)}" ${fraction === undefined ? '' : `data-fraction="${fraction}"`} aria-pressed="${record.id === state.selected}" title="${escapeHTML(recordLabel(record))} · ${escapeHTML(displayId(record))} · ${label}" aria-label="${escapeHTML(displayId(record))} · ${escapeHTML(recordLabel(record))} · ${label}"><img src="${escapeHTML(frame.src)}" alt=""><span>${escapeHTML(recordLabel(record))}</span></button>`;
  }).join('') || '<p class="subtle">Нет привязанных кадров.</p>';
  $('route-report').hidden = !route || state.view !== 'map';
}

function reviewControls(record) {
  const review = record.inspectionReview || {};
  return `<section class="review-controls"><div class="review-heading"><h3>Проверка кадра</h3><span>${escapeHTML(reviewMarks[reviewState(record)][1])}</span></div>
    <div class="review-buttons"><button class="button confirm" data-decision="confirmed" aria-keyshortcuts="Enter" title="Подтвердить (Enter)">Подтвердить</button><button class="button" data-decision="unseen">Не видно</button><button class="button" data-action="note">${review.note ? 'Править заметку' : 'Отметить проблему'}</button></div>
    ${review.note ? `<p>${escapeHTML(review.note)}</p>` : ''}</section>`;
}

function decideRecord(decision) {
  const record = records.objects.find(item => item.id === state.selected);
  if (!record || !Object.hasOwn(reviewNames, decision)) return;
  drivePlayer?.pause();
  if (record.inspectionReview?.decision !== decision) recordChange(reviewNames[decision], record);
  record.inspectionReview = {...record.inspectionReview, decision};
  renderDeck();
  persist(reviewNames[decision] + ' · ' + displayId(record));
  const group = visibleObjects().filter(item => item.routeId === record.routeId && frameById(item.frame));
  const i = group.indexOf(record);
  const next = [...group.slice(i + 1), ...group.slice(0, i)].find(item => reviewState(item) === 'pending');
  if (next) showRecord(next.id, true);
  else renderSelection();
}

function openReviewNote() {
  holdLive();
  const record = records.objects.find(item => item.id === state.selected);
  if (!record) return;
  drivePlayer?.pause();
  noteTarget = {record, routeId:currentSurveyRoute()?.id, carPoint:drivePlayer?.position()};
  $('note-object').textContent = displayId(record) + ' · ' + record.type;
  $('note-text').value = record.inspectionReview?.note || '';
  $('review-note').showModal();
}

function needsFollowup(record) {
  const review = record.inspectionReview;
  return Boolean(review?.note || review?.decision === 'unseen' || (review?.decision !== 'confirmed' &&
    (['urgent','review'].includes(record.priority) || (Number.isFinite(record.confidence) && record.confidence < 70))));
}

function reportRoute() {
  const route = currentSurveyRoute();
  if (!route) return;
  drivePlayer?.pause();
  $('problems-only').checked = state.filter === 'retake';
  updateRouteReport();
  $('report-dialog').showModal();
}

function updateRouteReport() {
  const route = currentSurveyRoute();
  const issuesOnly = $('problems-only').checked;
  const stops = orderedStops(route);
  if (issuesOnly && state.filter === 'retake') stops.push(...retakeStops().filter(r => !r.routeId));
  const objects = stops.filter(r => !issuesOnly || retakeReason(r) || needsFollowup(r) || ['urgent','review'].includes(priorityOf(r)));
  $('report-title').textContent = (issuesOnly ? 'Лист выезда · ' : '') + route.name;
  document.querySelector('[data-action="route-geojson"]').hidden = issuesOnly;
  $('report-body').innerHTML = `<p>Точек: ${objects.length} · Проверено: ${objects.filter(r => reviewState(r) !== 'pending').length} · На проверку: ${objects.filter(needsFollowup).length}</p>` +
    objects.map(r => {
      const frame = frameById(r.frame);
      const boxes = frame ? reportBoxes(frame) : [];
      const box = boxes.find(b => b.id === r.box);
      const reason = retakeReason(r) || r.issue || (needsFollowup(r) ? 'Требуется проверка' : '');
      return `<article>${issuesOnly && box ? cropHTML(frame, box) : frame ? `<figure class="frame"><img src="${escapeHTML(frame.src)}" alt="">${boxes.map(b => boxHTML(b)).join('')}</figure>` : ''}<div><strong>${escapeHTML(displayId(r))} · ${escapeHTML(recordLabel(r))}</strong>${!r.routeId ? '<p>Вне маршрута</p>' : ''}<p class="stop-address">${escapeHTML(r.place || formatPoint(r.point))}</p><p>${escapeHTML(reviewMarks[reviewState(r)][1])}</p>${issuesOnly && reason ? `<p>${escapeHTML(reason)}</p>` : ''}${r.inspectionReview?.note ? `<p>${escapeHTML(r.inspectionReview.note)}</p>` : ''}${reviewSummary(frame).map(line => `<p>${escapeHTML(line)}</p>`).join('')}</div></article>`;
    }).join('');
  $('report-body').querySelectorAll('article').forEach((article,index) => {
    const record = objects[index];
    if (!record.place && isValidPoint(record.point)) showPointAddress(record, article.querySelector('.stop-address'), formatPoint(record.point));
  });
  if (!objects.length) $('report-body').innerHTML = '<p>На этом маршруте нет точек для выезда.</p>';
}

function exportRouteGeoJSON() {
  const route = currentSurveyRoute();
  if (!route) return;
  const features = routeRecords(route).filter(r => isValidPoint(r.point)).map(r => ({
    type:'Feature', id:r.id, geometry:{type:'Point', coordinates:r.point},
    properties:{routeId:route.id, label:recordLabel(r), address:r.place, frame:r.frame, review:r.inspectionReview || null, boxReviews:reviewSummary(frameById(r.frame))}
  }));
  if (route.points?.length > 1) features.unshift({type:'Feature', geometry:{type:'LineString', coordinates:route.points}, properties:{name:route.name, routeId:route.id}});
  download(JSON.stringify({type:'FeatureCollection', features}, null, 2), 'application/geo+json', route.id + '.geojson');
}

// The saved tracks also give a geographic overview before 2GIS finishes loading.
function renderRouteSchematic(selected) {
  const host = $('route-schematic');
  const routes = (records.routes || []).filter(r => r.points?.length > 1);
  host.hidden = Boolean(inspectionMap) || !routes.length;
  if (host.hidden) return;
  const stops = (state.filter === 'retake' ? retakeStops().filter(matchesClass) : visibleObjects())
    .filter(record => isValidPoint(record.point));
  const points = routes.flatMap(r => r.points).concat(stops.map(record => record.point));
  const west = Math.min(...points.map(p => p[0])), north = Math.max(...points.map(p => p[1]));
  const scale = Math.cos(north * Math.PI / 180);
  const project = ([lon, lat]) => [(lon - west) * scale * 90000, (north - lat) * 90000];
  const extent = points.map(project);
  const width = Math.max(...extent.map(p => p[0])), height = Math.max(...extent.map(p => p[1]));
  host.innerHTML = `<svg viewBox="-50 -50 ${width+100} ${height+100}" fill="none">${routes.map(r =>
    `<polyline points="${r.points.map(p => project(p).join(',')).join(' ')}" stroke="${r.id === selected?.id ? 'var(--brand)' : '#758a9e'}" stroke-linejoin="round" stroke-width="4" vector-effect="non-scaling-stroke"/>`).join('')}${sectionView.parts.map(p =>
      `<polyline data-section="${p.index}" points="${p.path.map(v=>project(v).join(',')).join(' ')}" stroke="${sectionColors[p.priority]}" stroke-width="${sectionView.index===p.index ? 9:7}" vector-effect="non-scaling-stroke" style="pointer-events:stroke;cursor:pointer"><title>${sectionRange(p)} · ${sectionName(p.priority)}</title></polyline>`).join('')}${stops.map(record => {
      const [x,y] = project(record.point);
      return `<circle cx="${x}" cy="${y}" r="7" fill="var(--brand)" stroke="white" vector-effect="non-scaling-stroke"/>`;
    }).join('')}</svg>`;
}
