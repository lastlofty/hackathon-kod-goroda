'use strict';

const dgisNightStyle = 'e05ac437-fcc2-4845-ad74-b1de9ce07555';
// Address layers in the 2GIS night style. The house-number group also contains
// building names, so restore its address layers individually.
const dgisAddressLayers = [
  '414608', // Street labels
  '615525', '832861', '717409', '985757', '600950', '701700' // House numbers
];

async function loadDgisDrivingRoute(key, stops) {
  const url = new URL('https://routing.api.2gis.com/routing/7.0.0/global');
  url.searchParams.set('key', key);
  const response = await fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    cache: 'no-store',
    signal: AbortSignal.timeout(10000),
    body: JSON.stringify({
      points: stops.map(([lon, lat], index) => ({
        lon, lat, type: index === 0 || index === stops.length - 1 ? 'stop' : 'pref'
      })),
      transport: 'driving', output: 'detailed', locale: 'ru', route_mode: 'shortest'
    })
  });
  if (!response.ok) throw new Error('Routing API · HTTP ' + response.status);
  const data = await response.json();
  const route = data.result?.[0];
  const points = [];
  for (const maneuver of route?.maneuvers ?? []) {
    if (maneuver.type === 'end' && !maneuver.outcoming_path) continue;
    const segments = maneuver.outcoming_path?.geometry;
    if (!segments?.length) throw new Error('Нет геометрии участка проезда');
    for (const segment of segments) {
      const coords = /^LINESTRING\s*\(([^()]+)\)$/i.exec(segment.selection ?? '')?.[1];
      if (!coords) throw new Error('Некорректная геометрия участка');
      const section = coords.split(',').map(item => item.trim().split(/\s+/).map(Number));
      if (section.length < 2 || !section.every(point => point.length === 2 && isValidPoint(point))) throw new Error('Некорректные координаты маршрута');
      const tail = points.at(-1);
      if (tail && section[0].some((v, i) => Math.abs(v - tail[i]) > 0.00002)) throw new Error('Участки маршрута не соединены');
      for (const point of section) {
        const last = points.at(-1);
        if (!last || last[0] !== point[0] || last[1] !== point[1]) points.push(point);
      }
    }
  }
  if (data.status !== 'OK' || points.length < 2) throw new Error('Нет геометрии маршрута');
  return {points, distance: route.total_distance, duration: route.total_duration};
}

class DgisMapError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

let pendingDgisSdk;
function loadDgisSdk() {
  if (!pendingDgisSdk) pendingDgisSdk = requestDgisSdk().finally(() => { pendingDgisSdk = null; });
  return pendingDgisSdk;
}

async function requestDgisSdk() {
  if (window.mapgl?.Map) return window.mapgl;
  const script = document.createElement('script');
  script.src = 'https://mapgl.2gis.com/api/js/v1';
  try {
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new DgisMapError('sdk-timeout')), 12000);
      const fail = () => {
        clearTimeout(timer);
        reject(new DgisMapError('sdk-request'));
      };
      script.onerror = fail;
      script.onload = () => {
        if (!window.mapgl?.Map) return fail();
        clearTimeout(timer);
        resolve(window.mapgl);
      };
      document.head.append(script);
    });
  } finally {
    script.remove();
  }
}

function waitForDgisTiles(map) {
  return new Promise((resolve, reject) => {
    let styleLoaded = false;
    const timer = setTimeout(() => fail('tiles-timeout'), 18000);
    const cleanup = () => {
      clearTimeout(timer);
      map.off('styleload', styleLoad);
      map.off('styleloaderror', styleError);
      map.off('error', mapError);
      map.off('idle', idle);
    };
    const fail = code => {
      cleanup();
      reject(new DgisMapError(code));
    };
    function styleLoad() {
      try {
        for (const type of ['point', 'labelLine', 'metricPoint', 'oneWayLine']) {
          map.hideLayers({type});
        }
        for (const id of dgisAddressLayers) {
          if (map.hasLayer(id)) map.showLayers({id});
        }
        styleLoaded = true;
      } catch {
        fail('render');
      }
    }
    function styleError() { fail('style'); }
    function mapError(event) {
      if (event.type === 'invalidtilekey') fail('key');
      if (event.type === 'webglcontextlost') fail('render');
    }
    function idle() {
      if (!styleLoaded) return;
      cleanup();
      resolve();
    }
    map.on('styleload', styleLoad);
    map.on('styleloaderror', styleError);
    map.on('error', mapError);
    map.on('idle', idle);
  });
}

// Keep the driving line in the same screen plane as the car marker. Insert it
// between the map canvas and the HTML markers so the car stays on top.
function drawRouteLine(map, route, color) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:hidden';
  svg.setAttribute('aria-hidden', 'true');
  const lines = ['#18232e', 'var(--brand)', 'transparent'].map((color, i) => {
    const path = document.createElementNS(ns, 'path');
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', [9, 5, 20][i]);
    path.setAttribute('stroke-linejoin', 'round');
    path.setAttribute('stroke-linecap', 'round');
    svg.append(path);
    return path;
  });
  svg.classList.add('survey-route-line');
  const canvas = map.getCanvas();
  const last = color && Array.from(canvas.parentNode.children).filter(el=>el.classList.contains('survey-route-line')).at(-1);
  (last || canvas).after(svg);
  if (color) {
    lines[1].setAttribute('stroke', color);
    lines[1].setAttribute('stroke-width', '7');
  }

  function draw() {
    const [width, height] = map.getSize();
    if (!width || !height) return;
    // Clip at the near edge before projecting. With a tilted camera, a point
    // behind the viewer can otherwise project back across the visible street.
    const left = map.unproject([0, height + 10]);
    const right = map.unproject([width, height + 10]);
    const side = ([x, y]) => (right[0] - left[0]) * (y - left[1]) - (right[1] - left[1]) * (x - left[0]);
    const sign = Math.sign(side(map.getCenter()));
    const commands = [];
    const vertex = (command, point) => {
      const [x, y] = map.project(point);
      commands.push(command + x.toFixed(2) + ' ' + y.toFixed(2));
    };
    let previous = route[0];
    let from = side(previous) * sign;
    if (from >= 0) vertex('M', previous);
    for (let i = 1; i < route.length; i++) {
      const point = route[i];
      const to = side(point) * sign;
      if ((from >= 0) !== (to >= 0)) {
        const t = from / (from - to);
        vertex(from < 0 ? 'M' : 'L', previous.map((v, i) => v + t * (point[i] - v)));
      }
      if (to >= 0) vertex('L', point);
      previous = point;
      from = to;
    }
    const d = commands.join(' ');
    for (const line of lines) line.setAttribute('d', d);
  }

  map.on('move', draw);
  map.on('resize', draw);
  draw();
  return {
    destroy() {
      map.off('move',draw);
      map.off('resize',draw);
      svg.remove();
    },
    contains: point => lines[2].isPointInStroke(new DOMPoint(point[0], point[1])),
    style(active, hovered, driving) {
      svg.style.visibility = driving && !active ? 'hidden' : 'visible';
      lines[1].setAttribute('stroke', hovered ? '#82deea' : active ? 'var(--brand)' : '#97aabd');
      lines[1].setAttribute('stroke-width', hovered ? 7 : active ? 5 : 4);
    }
  };
}

function fitDgisPoints(map, coordinates, duration = 250) {
  if (!coordinates.length) return;
  if (coordinates.length === 1) {
    map.setCenter(coordinates[0], {duration});
    map.setZoom(17, {duration});
    return;
  }
  const lngs = coordinates.map(([lng]) => lng);
  const lats = coordinates.map(([, lat]) => lat);
  map.fitBounds({
    southWest: [Math.min(...lngs), Math.min(...lats)],
    northEast: [Math.max(...lngs), Math.max(...lats)]
  }, {
    padding: {top: 60, right: 30, bottom: 60, left: 30},
    maxZoom: 17,
    animation: {duration}
  });
}

async function createDgisStreetMap(api, container, key, center, zoom, controls = {}) {
  const map = new api.Map(container, {
    key, style: dgisNightStyle, defaultBackgroundColor: '#17212c', center, zoom,
    maxZoom: 19, maxPitch: 60, lang: 'ru', loopWorld: true, graphicsPreset: 'normal',
    enableTrackResize: true, zoomControl: false, floorControl: false, ...controls
  });
  try {
    await waitForDgisTiles(map);
    return map;
  } catch (error) {
    map.destroy();
    throw error;
  }
}

async function initDgisMap({container, key, route, routes = [], points = [], markerButton, onSelect, onPoint, onRouteSelect, onRouteHover, canPickRoute}) {
  const api = await loadDgisSdk();
  const choices = routes.length ? routes : (route.length > 1 ? [{points: route}] : []);
  const focus = choices.length ? choices.flatMap(choice => choice.points) : points;
  const center = focus[Math.floor(focus.length / 2)] ?? [0, 0];
  let map;
  let vehicle;
  let carIcon;
  let driveGestures;
  const lines = new Map();
  let sectionLines = [];
  let sectionSignature = '';
  let onSection;
  function sectionAt(point) {
    return point && !vehicle && canPickRoute() && sectionLines.find(s=>s.line.contains(point));
  }
  let selected = choices[0];
  let hovered;
  let targetZoom;
  let overview;

  function styleRoutes() {
    for (const [choice, line] of lines) line.style(choice === selected, choice === hovered, Boolean(vehicle));
  }

  function hover(choice) {
    if (hovered === choice) return;
    hovered = choice;
    container.style.cursor = choice ? 'pointer' : '';
    onRouteHover?.(choice);
    styleRoutes();
  }

  function routeAt(point) {
    if (!point || vehicle || choices.length < 2 || !canPickRoute()) return;
    return choices.find(choice => lines.get(choice)?.contains(point));
  }

  function selectRoute(choice) {
    selected = choice;
    hover(undefined);
    styleRoutes();
  }

  function setDriveZoom(value, duration) {
    targetZoom = Math.min(map.getMaxZoom(), Math.max(map.getMinZoom(), value));
    map.setZoom(targetZoom, {duration});
  }

  function enableDriveGestures() {
    driveGestures = new AbortController();
    const options = {signal: driveGestures.signal, passive: false, capture: true};
    let pinchDistance = 0;
    // Native pointer-anchored zoom also pans the map, competing with follow mode.
    map.blockInteraction();
    container.addEventListener('wheel', event => {
      event.preventDefault();
      const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? container.clientHeight : 1;
      const delta = -event.deltaY * unit * (event.ctrlKey ? 0.012 : 0.003);
      setDriveZoom(targetZoom + Math.max(-1, Math.min(1, delta)), 140);
    }, options);
    container.addEventListener('dblclick', event => {
      event.preventDefault();
      setDriveZoom(targetZoom + (event.shiftKey ? -1 : 1), 180);
    }, options);
    function pinch(event) {
      if (event.touches.length !== 2) {
        pinchDistance = 0;
        return;
      }
      event.preventDefault();
      const [a, b] = event.touches;
      const span = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY);
      if (span && pinchDistance && event.type === 'touchmove') {
        setDriveZoom(targetZoom + Math.log2(span / pinchDistance), 0);
      }
      pinchDistance = span;
    }
    for (const type of ['touchstart', 'touchmove', 'touchend', 'touchcancel']) {
      container.addEventListener(type, pinch, options);
    }
  }
  const fitPoints = (coordinates, duration) => fitDgisPoints(map, coordinates, duration);

  try {
    map = await createDgisStreetMap(api, container, key, center, focus.length ? 15 : 1);
    fitPoints(focus, 0);
    for (const choice of choices) lines.set(choice, drawRouteLine(map, choice.points));
    styleRoutes();
    map.on('mousemove', event => {
      hover(routeAt(event.point));
      if (sectionLines.length) container.style.cursor = sectionAt(event.point) || hovered ? 'pointer' : '';
    });
    container.addEventListener('pointerleave', () => hover(undefined));
    map.on('movestart', () => hover(undefined));
    map.on('click', event => {
      const section = sectionAt(event.point);
      if (section) { onSection(section.index); return; }
      const choice = routeAt(event.point);
      if (choice) onRouteSelect(choice);
      else if (event.lngLat) onPoint(event.lngLat);
    });
  } catch (error) {
    map?.destroy();
    throw error instanceof DgisMapError ? error : new DgisMapError('render');
  }

  const markers = new Map();
  return {
    fitPoints,
    selectRoute,
    setSections(parts, select) {
      onSection = select;
      const signature = JSON.stringify(parts.map(p=>[p.path,p.priority]));
      if (signature === sectionSignature) return;
      sectionSignature = signature;
      for (const part of sectionLines) part.line.destroy();
      sectionLines = parts.map(p=>({index:p.index,line:drawRouteLine(map,p.path,sectionColors[p.priority])}));
    },
    startDrive(point) {
      overview = {center: map.getCenter().slice(), zoom: map.getZoom(), rotation: map.getRotation(), pitch: map.getPitch()};
      carIcon = document.createElement('div');
      carIcon.className = 'route-car';
      carIcon.setAttribute('aria-label', 'Машина');
      vehicle = new api.HtmlMarker(map, {coordinates: point, html: carIcon, anchor: [10, 15], zIndex: 20, disableRounding: true});
      enableDriveGestures();
      setDriveZoom(17.6, 0);
      map.setPitch(52, {duration: 0});
      hover(undefined);
      styleRoutes();
    },
    updateDrive(point, heading, deltaMs) {
      vehicle?.setCoordinates(point);
      map.setCenter(point, {duration: 0});
      const rotation = map.getRotation();
      const turn = ((-heading - rotation + 540) % 360) - 180;
      const blend = deltaMs === undefined ? 1 : -Math.expm1(-deltaMs / 160);
      const cameraRotation = rotation + turn * blend;
      map.setRotation(cameraRotation, {duration: 0});
      carIcon.style.rotate = (heading + cameraRotation) + 'deg';
    },
    endDrive() {
      driveGestures.abort();
      map.unblockInteraction();
      vehicle?.destroy();
      vehicle = null;
      styleRoutes();
      carIcon = null;
      map.setPitch(overview.pitch, {duration: 0});
      map.setRotation(overview.rotation, {duration: 0});
      map.setZoom(overview.zoom, {duration: 0});
      map.setCenter(overview.center, {duration: 0});
      overview = null;
    },
    panTo: point => map.setCenter(point, {duration: 250}),
    zoom(direction) {
      if (vehicle) setDriveZoom(targetZoom + direction, 180);
      else map.setZoom(Math.min(map.getMaxZoom(), Math.max(map.getMinZoom(), map.getZoom() + direction)), {duration: 200});
    },
    setMarkers(records, selected) {
      const visible = new Set(records.map(record => record.id));
      for (const [id, entry] of markers) {
        if (!visible.has(id)) {
          entry.marker.destroy();
          markers.delete(id);
        }
      }
      for (const record of records) {
        let entry = markers.get(record.id);
        if (!entry) {
          const button = markerButton(record);
          button.classList.add('dgis-marker');
          button.addEventListener('click', event => {
            event.stopPropagation();
            onSelect(record.id);
          });
          const marker = new api.HtmlMarker(map, {
            coordinates: record.point,
            html: button,
            anchor: [7, 7],
            interactive: true,
            preventMapInteractions: true
          });
          entry = {marker, button, selected: null, point: record.point};
          markers.set(record.id, entry);
        }
        if (entry.point[0] !== record.point[0] || entry.point[1] !== record.point[1]) {
          entry.marker.setCoordinates(record.point);
          entry.point = record.point;
        }
        const isSelected = selected === record.id;
        if (entry.selected !== isSelected) {
          entry.button.setAttribute('aria-pressed', String(isSelected));
          entry.marker.setZIndex(isSelected ? 10 : 0);
          entry.selected = isSelected;
        }
      }
    }
  };
}
