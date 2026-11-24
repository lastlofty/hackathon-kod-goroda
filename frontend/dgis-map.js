'use strict';

const dgisLightStyle = 'c080bb6a-8134-4993-93a1-5b4d8c36a59b';
// Group IDs in the standard light style. Street and house-number layers stay visible.
const dgisPlaceLayers = [
  '563870', '444318', '367319', '233125', '309294', '913433', // Businesses and landmarks
  '5946', '661538', '826173', 'traffic light', 'porch', 'porch under house', 'gate', 'barrier',
  '764094', '805874', '758882', // Transit lines, landmarks and stops
  '711817', '366803', '272603', '682782', '740815', '159784', '632416', '43556', // Metro stations
  '77098', '364776', '73948', '501891', '924721', '135503', '227', '44814' // Metro exits
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
  if (data.status !== 'OK' || points.length < 2) throw new Error('2ГИС не вернул геометрию маршрута');
  return {points, distance: route.total_distance, duration: route.total_duration};
}

class DgisMapError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

async function loadDgisSdk() {
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
        for (const id of dgisPlaceLayers) {
          if (map.hasLayer(id)) map.hideLayers({id});
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

async function initDgisMap({container, key, route, points = [], markerButton, onSelect, onPoint}) {
  const api = await loadDgisSdk();
  const focus = route.length > 1 ? route : points;
  const center = focus[Math.floor(focus.length / 2)] ?? [0, 0];
  let map;
  let vehicle;
  let overview;
  const fitPoints = (coordinates, duration = 250) => {
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
  };

  try {
    map = new api.Map(container, {
      key,
      style: dgisLightStyle,
      center,
      zoom: focus.length ? 15 : 1,
      maxZoom: 19,
      maxPitch: 60,
      lang: 'ru',
      loopWorld: true,
      graphicsPreset: 'normal',
      enableTrackResize: true,
      zoomControl: false,
      floorControl: false,
      disableRotationByUserInteraction: true,
      disablePitchByUserInteraction: true
    });
    await waitForDgisTiles(map);
    fitPoints(focus, 0);
    map.on('click', event => {
      if (event.lngLat) onPoint(event.lngLat);
    });
    if (route.length > 1) {
      const line = {coordinates: route, renderingMode: '2d', interactive: false};
      new api.Polyline(map, {...line, width: 9, color: '#ffffff', zIndex: 1});
      new api.Polyline(map, {...line, width: 5, color: '#1967a5', zIndex: 2});
      for (const [text, coordinates] of [['Старт', route[0]], ['Финиш', route.at(-1)]]) {
        const label = document.createElement('span');
        label.className = 'route-endpoint';
        label.textContent = text;
        new api.HtmlMarker(map, {coordinates, html: label, anchor: [0, 20], interactive: false});
      }
    }
  } catch (error) {
    map?.destroy();
    throw error instanceof DgisMapError ? error : new DgisMapError('render');
  }

  const markers = new Map();
  return {
    fitPoints,
    startDrive(point) {
      overview = {center: map.getCenter().slice(), zoom: map.getZoom(), rotation: map.getRotation(), pitch: map.getPitch()};
      const model = document.createElement('div');
      model.className = 'route-car';
      model.setAttribute('aria-label', 'Машина');
      vehicle = new api.HtmlMarker(map, {coordinates: point, html: model, anchor: [10, 15], zIndex: 20});
      map.setZoom(17.6, {duration: 0});
      map.setPitch(52, {duration: 0});
    },
    updateDrive(point, heading) {
      vehicle?.setCoordinates(point);
      map.setCenter(point, {duration: 0});
      map.setRotation(-heading, {duration: 0});
    },
    endDrive() {
      vehicle?.destroy();
      vehicle = null;
      map.setPitch(overview.pitch, {duration: 0});
      map.setRotation(overview.rotation, {duration: 0});
      map.setZoom(overview.zoom, {duration: 0});
      map.setCenter(overview.center, {duration: 0});
      overview = null;
    },
    panTo: point => map.setCenter(point, {duration: 250}),
    zoom: direction => map.setZoom(Math.min(map.getMaxZoom(), Math.max(map.getMinZoom(), map.getZoom() + direction)), {duration: 200}),
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
