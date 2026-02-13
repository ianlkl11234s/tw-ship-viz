import maplibregl from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { MAP_CENTER, MAP_ZOOM, MAP_MIN_ZOOM, MAP_MAX_ZOOM, THEMES } from './utils/constants.js';

let map = null;
let currentTheme = 'day';

export function initMap(containerId = 'map') {
  map = new maplibregl.Map({
    container: containerId,
    style: THEMES[currentTheme].mapStyle,
    center: MAP_CENTER,
    zoom: MAP_ZOOM,
    minZoom: MAP_MIN_ZOOM,
    maxZoom: MAP_MAX_ZOOM,
    attributionControl: true,
  });

  map.addControl(new maplibregl.NavigationControl(), 'top-right');

  return map;
}

export function getMap() {
  return map;
}

export function getCurrentTheme() {
  return currentTheme;
}

export function toggleTheme() {
  currentTheme = currentTheme === 'day' ? 'night' : 'day';
  map.setStyle(THEMES[currentTheme].mapStyle);
  document.body.classList.toggle('dark-theme', currentTheme === 'night');
  return currentTheme;
}
