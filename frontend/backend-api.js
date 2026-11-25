'use strict';

const backendBase = new URL(document.querySelector('meta[name="mgts-backend-api"]').content, location.href);
const workspaceSlug = document.querySelector('meta[name="mgts-workspace"]').content;
const backendDate = new Intl.DateTimeFormat('ru-RU', {dateStyle: 'short', timeStyle: 'short'});
const findingPriorities = {normal: 'normal', attention: 'review', repair: 'review', critical: 'urgent', new: 'review', review: 'review', urgent: 'urgent'};
let workspaceId;

async function backendRequest(path, options = {}) {
  const response = await fetch(new URL(path, backendBase), {...options, signal: AbortSignal.timeout(8000)});
  if (!response.ok) {
    const error = new Error('API · HTTP ' + response.status);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

async function backendList(resource, filters = {}) {
  const items = [];
  const query = new URLSearchParams({...filters, limit: 500});
  let page;
  do {
    query.set('offset', items.length);
    page = await backendRequest(`/api/v1/${resource}?${query}`);
    items.push(...page);
  } while (page.length === 500);
  return items;
}

async function findWorkspace() {
  const workspaces = await backendList('workspaces');
  return workspaces.find(workspace => workspace.slug === workspaceSlug)?.id;
}

async function ensureWorkspace() {
  if (workspaceId) return workspaceId;
  try {
    const workspace = await backendRequest('/api/v1/workspaces', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slug: workspaceSlug, name: 'Мониторинг МГТС'})
    });
    workspaceId = workspace.id;
  } catch (error) {
    if (error.status !== 409) throw error;
    workspaceId = await findWorkspace();
    if (!workspaceId) throw error;
  }
  return workspaceId;
}

function backendFrame(media) {
  const date = new Date(media.captured_at ?? media.created_at);
  let src;
  try { src = new URL(media.url, backendBase); } catch { return null; }
  if (!['http:', 'https:'].includes(src.protocol)) return null;
  return {
    id: media.id, name: media.original_filename || 'Снимок ' + media.id.slice(0, 8), src: src.href,
    time: Number.isFinite(date.getTime()) ? backendDate.format(date) : '—',
    capturedMs: date.getTime(), cameraPoint: backendPoint(media), routeId: media.attributes?.route_id,
    capturedOn: media.captured_at?.slice(0,10), backend: true, demo: media.source === 'demo', boxes: []
  };
}

function backendPoint(record) {
  if (Number.isFinite(record?.longitude) && Number.isFinite(record?.latitude)) {
    return [record.longitude, record.latitude];
  }
  return null;
}

async function backendBox(finding, frame, label, sizes) {
  const box = finding.geometry;
  if (!box || (box.type && box.type !== 'bbox' && !isPathType(box.type))) return null;
  const width = box?.width ?? box?.w;
  const height = box?.height ?? box?.h;
  if (isPathType(box.type)) {
    if (!Array.isArray(box.points) || !box.points.every(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite))) return null;
  } else if (![box.x, box.y, width, height].every(Number.isFinite) || width <= 0 || height <= 0) return null;
  let imageWidth = 1;
  let imageHeight = 1;
  if (box.coordinate_space !== 'normalized') {
    if (!sizes.has(frame.src)) {
      const image = new Image();
      image.src = frame.src;
      sizes.set(frame.src, Promise.race([
        image.decode().then(() => [image.naturalWidth, image.naturalHeight], () => null),
        new Promise(resolve => setTimeout(() => resolve(null), 2500))
      ]));
    }
    const size = await sizes.get(frame.src);
    if (!size) return null;
    [imageWidth, imageHeight] = size;
  }
  const source = finding.source === 'manual' ? 'manual' : frame.demo ? 'demo' : 'model';
  if (isPathType(box.type)) {
    const points = box.points.map(([x,y]) => [x/imageWidth,y/imageHeight]);
    if (!validPath(box.type,points)) return null;
    return {id:finding.id,label,type:box.type,points,...pathBounds(points),source};
  }
  const x = Math.max(0, box.x / imageWidth);
  const y = Math.max(0, box.y / imageHeight);
  const w = Math.min(1, (box.x + width) / imageWidth) - x;
  const h = Math.min(1, (box.y + height) / imageHeight) - y;
  if (w <= 0 || h <= 0) return null;
  return {id: finding.id, label, x, y, w, h,
    source};
}

function applyAnnotationReview(frame,review) {
  frame.annotationReview = review || null;
  if (!review) return;
  const changes = review.overrides;
  frame.boxes = frame.modelBoxes.filter(box => !Object.hasOwn(changes,box.id));
  for (const [id,shape] of Object.entries(changes)) {
    if (!shape) continue;
    const bounds = isPathType(shape.type) ? pathBounds(shape.points) : {};
    frame.boxes.push({...shape,...bounds,id,source:'manual'});
  }
}

function annotationChange(box) {
  if (!box) return null;
  if (isPathType(box.type)) return {type:box.type,label:box.label,points:box.points};
  const {x,y,w,h,label} = box;
  return {type:'bbox',x,y,w,h,label};
}

async function loadLegacyInspection() {
  workspaceId = await findWorkspace();
  if (!workspaceId) return {frames: [], objects: []};
  const filters = {workspace_id: workspaceId};
  const [types, entities, media, findings] = await Promise.all(
    ['entity-types', 'entities', 'media', 'findings'].map(resource => backendList(resource, filters))
  );
  return buildBackendInspection(types, entities, media, findings);
}

async function buildBackendInspection(types, entities, media, findings) {
  const frames = media.filter(item => item.content_type?.startsWith('image/') ||
    ['image', 'photo', 'frame'].includes(item.kind)).map(backendFrame).filter(Boolean);
  const frameById = new Map(frames.map(frame => [frame.id, frame]));
  const mediaById = new Map(media.map(item => [item.id, item]));
  const entityById = new Map(entities.map(entity => [entity.id, entity]));
  const typeNames = new Map(types.map(type => [type.id, type.name]));
  const latest = new Map();
  const captures = new Map();
  const sizes = new Map();
  for (const frame of frames) frame.inference = [];
  for (const finding of findings) {
    frameById.get(finding.media_id)?.inference.push(finding);
    if (finding.entity_id && frameById.has(finding.media_id)) {
      if (!captures.has(finding.entity_id)) captures.set(finding.entity_id, new Set());
      captures.get(finding.entity_id).add(finding.media_id);
    }
    if (finding.entity_id && !latest.has(finding.entity_id)) latest.set(finding.entity_id, finding);
  }
  function label(entity, finding) {
    return entity?.name || typeNames.get(entity?.entity_type_id) || finding?.label || finding?.category || 'Объект';
  }
  const boxes = await Promise.all(findings.map(finding => {
    const frame = frameById.get(finding.media_id);
    if (frame) return backendBox(finding, frame, finding.label || label(entityById.get(finding.entity_id), finding), sizes);
  }));
  boxes.forEach((box, index) => {
    if (!box) return;
    const finding = findings[index];
    const frame = frameById.get(finding.media_id);
    frame.boxes.push(box);
    (frame.findingsByBox ??= {})[box.id] = {
      recordId: finding.entity_id || finding.id,
      confidence: Number.isFinite(finding.score) ? Math.round(finding.score * 100) : null
    };
  });

  for (const frame of frames) {
    const media = mediaById.get(frame.id);
    frame.modelBoxes = frame.boxes;
    frame.sharedAnnotations = Object.hasOwn(media,'annotation_review');
    applyAnnotationReview(frame,media.annotation_review);
  }

  function objectRecord(entity, finding) {
    const id = entity?.id || finding.id;
    const frame = frameById.get(finding?.media_id);
    const point = backendPoint(entity);
    return {
      id, displayId: entity?.external_id || id.slice(0, 8), type: label(entity, finding),
      issue: finding?.label || finding?.category,
      priority: findingPriorities[finding?.status] || 'unverified',
      confidence: finding?.score != null ? Math.round(finding.score * 100) : null,
      recommendation: finding?.recommendation, reviewed: finding?.reviewed, severity: finding?.severity,
      routeId: entity?.attributes?.route_id || mediaById.get(finding?.media_id)?.attributes?.route_id,
      place: entity?.attributes?.address || mediaById.get(finding?.media_id)?.attributes?.address, point: point || backendPoint(mediaById.get(finding?.media_id)),
      pointKind: point ? 'asset' : 'observation', frame: frame?.id, captureFrames:[...(captures.get(id) || [])],
      box: frame?.boxes.find(box => box.id === finding.id)?.id, origin: 'backend'
    };
  }
  const objects = [
    ...entities.map(entity => objectRecord(entity, latest.get(entity.id))),
    ...findings.filter(finding => !finding.entity_id).map(finding => objectRecord(null, finding))
  ];
  const mappedFrames = new Set(objects.filter(record => {
    const gps = backendPoint(mediaById.get(record.frame));
    return gps && record.point?.[0] === gps[0] && record.point?.[1] === gps[1];
  }).map(record => record.frame));
  const represented = new Set(objects.map(record => record.frame));
  for (const frame of frames) {
    const media = mediaById.get(frame.id);
    const point = backendPoint(media);
    if (mappedFrames.has(frame.id) || (!point && represented.has(frame.id))) continue;
    objects.push({id: 'media:' + frame.id, displayId: frame.id.slice(0, 8), frame: frame.id, type: 'Кадр проезда',
      priority: 'unverified', origin: 'backend', point, pointKind: 'observation',
      routeId: media.attributes?.route_id, place: media.attributes?.address});
  }
  return {frames, objects};
}

async function uploadBackendPhoto(file) {
  const body = new FormData();
  body.set('workspace_id', await ensureWorkspace());
  body.set('file', file);
  body.set('source', 'operator');
  const frame = backendFrame(await backendRequest('/api/v1/media/upload', {method: 'POST', body}));
  frame.modelBoxes = [];
  frame.sharedAnnotations = supportsAnnotationRevisions;
  return frame;
}
