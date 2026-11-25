'use strict';

const reviewNames = {confirmed: 'Подтверждено', unseen: 'Не видно на кадре'};
let queueOnly = false;
let noteTarget;

function currentSurveyRoute() {
  return drivingRoute || records.routes?.find(route => route.id === $('route-select').value) || records.routes?.[0];
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
  const route = currentSurveyRoute();
  const shots = routeRecords(route).filter(record => frameById(record.frame) && isValidPoint(record.point))
    .map(record => ({record, fraction:fractionAlongRoute(record.point, route.points || [])}))
    .sort((a, b) => a.fraction - b.fraction);
  $('seek-ticks').innerHTML = shots.map(({record, fraction}) => {
    const frame = frameById(record.frame);
    return `<button type="button" class="seek-mark" style="left:${100 * fraction}%" data-shot="${escapeHTML(record.id)}" data-fraction="${fraction}" aria-label="Кадр: ${escapeHTML(record.type)}"><span><img src="${escapeHTML(frame.src)}" alt="">${escapeHTML(record.type)}</span></button>`;
  }).join('');
  renderRouteSchematic(route);
  $('route-count').textContent = route ? 'Кадров: ' + shots.length : '';
  $('route-frames').innerHTML = shots.map(({record, fraction}) => {
    const frame = frameById(record.frame);
    return `<button class="film-shot" data-shot="${escapeHTML(record.id)}" data-fraction="${fraction}" aria-pressed="${record.id === state.selected}" title="${escapeHTML(record.type)} · ${escapeHTML(displayId(record))}"><img src="${escapeHTML(frame.src)}" alt=""><span>${escapeHTML(record.type)}</span></button>`;
  }).join('') || '<p class="subtle">Нет привязанных кадров.</p>';
  $('route-report').hidden = !route || state.view !== 'map';
}

function reviewControls(record) {
  const review = record.inspectionReview || {};
  return `<section class="review-controls"><div class="review-heading"><h3>Проверка кадра</h3><span>${escapeHTML(reviewNames[review.decision] || 'Ожидает проверки')}</span></div>
    <div class="review-buttons"><button class="button confirm" data-decision="confirmed">Подтвердить</button><button class="button" data-decision="unseen">Не видно</button><button class="button" data-action="note">${review.note ? 'Править заметку' : 'Отметить проблему'}</button></div>
    ${review.note ? `<p>${escapeHTML(review.note)}</p>` : ''}</section>`;
}

function decideRecord(decision) {
  const record = records.objects.find(item => item.id === state.selected);
  if (!record || !Object.hasOwn(reviewNames, decision)) return;
  drivePlayer?.pause();
  record.inspectionReview = {...record.inspectionReview, decision};
  persist(reviewNames[decision] + ' · ' + displayId(record));
  const group = visibleObjects().filter(item => item.routeId === record.routeId && frameById(item.frame));
  const i = group.indexOf(record);
  const next = [...group.slice(i + 1), ...group.slice(0, i)].find(item => !item.inspectionReview?.decision);
  if (next) showRecord(next.id, true);
  else renderSelection();
}

function openReviewNote() {
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
  const objects = routeRecords(route);
  $('report-title').textContent = route.name;
  $('report-body').innerHTML = `<p>Точек: ${objects.length} · Проверено: ${objects.filter(r => r.inspectionReview?.decision).length} · На проверку: ${objects.filter(needsFollowup).length}</p>` +
    objects.map(r => {
      const frame = frameById(r.frame);
      return `<article>${frame ? `<figure class="frame"><img src="${escapeHTML(frame.src)}" alt="">${frame.boxes.map(b => boxHTML(b)).join('')}</figure>` : ''}<div><strong>${escapeHTML(r.type)}</strong><p>${escapeHTML(r.place || formatPoint(r.point))}</p><p>${escapeHTML(reviewNames[r.inspectionReview?.decision] || 'Ожидает проверки')}</p>${r.inspectionReview?.note ? `<p>${escapeHTML(r.inspectionReview.note)}</p>` : ''}</div></article>`;
    }).join('');
  $('report-dialog').showModal();
}

function exportRouteGeoJSON() {
  const route = currentSurveyRoute();
  if (!route) return;
  const features = routeRecords(route).filter(r => isValidPoint(r.point)).map(r => ({
    type:'Feature', id:r.id, geometry:{type:'Point', coordinates:r.point},
    properties:{routeId:route.id, label:r.type, address:r.place, frame:r.frame, review:r.inspectionReview || null}
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
  const points = routes.flatMap(r => r.points);
  const west = Math.min(...points.map(p => p[0])), north = Math.max(...points.map(p => p[1]));
  const scale = Math.cos(north * Math.PI / 180);
  const project = ([lon, lat]) => [(lon - west) * scale * 90000, (north - lat) * 90000];
  const extent = points.map(project);
  const width = Math.max(...extent.map(p => p[0])), height = Math.max(...extent.map(p => p[1]));
  host.innerHTML = `<svg viewBox="-50 -50 ${width+100} ${height+100}" fill="none">${routes.map(r =>
    `<polyline points="${r.points.map(p => project(p).join(',')).join(' ')}" stroke="${r.id === selected?.id ? 'var(--brand)' : '#758a9e'}" stroke-linejoin="round" stroke-width="4" vector-effect="non-scaling-stroke"/>`).join('')}</svg>`;
}
