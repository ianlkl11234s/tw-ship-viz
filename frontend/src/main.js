import { MapboxOverlay } from '@deck.gl/mapbox';
import { initMap, setTheme, getCurrentTheme } from './map.js';
import { loadTrajectoryData, loadPositionsData } from './data/loader.js';
import { arrowToTrips, buildFrameIndex, jsonToTrips, jsonToFrameIndex } from './data/transform.js';
import { createTrajectoryLayers, preprocessTrips, bakeAllColors } from './layers/trips.js';
import { createGridLayers } from './layers/grid.js';
import { createHexagonLayers } from './layers/hexagon.js';
import { updateNativeHeatmap, hideNativeHeatmap } from './layers/heatmap.js';
import { createQueryLayers, createQueryShipDots } from './layers/path.js';
import { createPortLayers } from './layers/ports.js';
import { initTimeline, getCurrentTime } from './controls/timeline.js';
import { initQueryControls, enableQueryMode, disableQueryMode, handlePick } from './controls/query.js';
import { updateLegend } from './ui/legends.js';
import { VESSEL_CATEGORIES, VESSEL_CODE_TO_CATEGORY } from './utils/constants.js';
import './style.css';

// === 全域狀態 ===
let map = null;
let deckOverlay = null;
let tripsData = null;       // TripsLayer 用
let frameIndex = null;      // 密度/六角/熱力圖用的幀索引
let currentMode = 'trajectory';
let activeCategories = null; // null = 全部，否則 Set<category key>
let metadata = null;         // Arrow metadata
let queryResults = [];       // 查詢模式軌跡結果
let queryShips = [];         // 查詢模式船舶散點
let portFeatures = null;     // 港口 GeoJSON features
let showPorts = true;        // 港口圖層顯示開關

// === 主題與配色 ===
let themeMode = 'auto';           // 'day' | 'night' | 'auto'
let currentColorPalette = 'speed'; // 'speed' | 'blue' | 'warm' | 'neon'

// === 軌跡篩選快取（只在篩選條件變化時重建，不再每幀 .filter()）===
let _filteredTrips = null;

function rebuildFilteredTrips() {
  if (!tripsData) { _filteredTrips = null; return; }
  if (activeCategories) {
    _filteredTrips = tripsData.filter(d => {
      const cat = VESSEL_CODE_TO_CATEGORY[d.vesselType];
      return cat && activeCategories.has(cat);
    });
  } else {
    _filteredTrips = tripsData;
  }
}

// === 幀快取（避免 60fps 下每幀都重建資料和 Layer）===
let _cachedFrameIdx = -1;
let _cachedPositions = null;
let _cachedLayerKey = '';

function invalidateFrameCache() {
  _cachedFrameIdx = -1;
  _cachedPositions = null;
  _cachedLayerKey = '';
}

// === 初始化 ===
async function init() {
  map = initMap('map');

  map.on('load', async () => {
    console.log('[ship-gis] MapLibre 地圖初始化完成');

    // 初始化 deck.gl overlay
    deckOverlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      onClick: (info) => {
        if (currentMode === 'query') handlePick(info);
      },
    });
    map.addControl(deckOverlay);

    // 載入資料
    await loadData();

    // 載入完成：淡出 loading，淡入 UI
    const loading = document.getElementById('loading');
    const appUi = document.getElementById('app-ui');
    if (loading) {
      loading.classList.add('fade-out');
      setTimeout(() => { loading.style.display = 'none'; }, 500);
    }
    if (appUi) appUi.classList.remove('hidden');

    // 設置 UI
    setupTabs();
    setupFilters();
    setupPortToggle();
    setupThemeDropdown();
    setupColorPaletteSelector();
    setupInfoModal();
    initQueryControls({
      map,
      onQueryResult: (results) => { queryResults = results; updateLayers(getCurrentTime()); },
      onQueryShipsLoad: (ships) => { queryShips = ships; updateLayers(getCurrentTime()); },
    });
    checkQueryApi();
    updateLegend(currentMode, getCurrentTheme());

    // zoom 改變時重繪港口圖層（控制標籤顯示密度）
    map.on('zoomend', () => { updateLayers(getCurrentTime()); });
  });
}

// === 資料載入 ===
async function loadData() {
  const loadingText = document.querySelector('.loading-text');
  if (loadingText) loadingText.textContent = '載入船舶資料中...';

  // 平行載入
  const [trajResult, posResult, portsResult] = await Promise.all([
    loadTrajectoryData(),
    loadPositionsData(),
    fetch('/data/ports.geojson').then(r => r.json()).catch(() => null),
  ]);

  // 港口資料
  if (portsResult && portsResult.features) {
    portFeatures = portsResult.features;
    console.log(`[ship-gis] 載入 ${portFeatures.length} 座港口`);
  }

  if (loadingText) loadingText.textContent = '處理資料中...';

  // 轉換軌跡資料
  if (trajResult.type === 'arrow') {
    tripsData = arrowToTrips(trajResult.table);
    preprocessTrips(tripsData, trajResult.table);
    metadata = trajResult.metadata;
  } else {
    tripsData = jsonToTrips(trajResult.data);
    metadata = {
      baseTimestamp: new Date(trajResult.data.frames[0].time).getTime() / 1000,
      frameTimes: trajResult.data.frames.map((f, i) => i * 600),
      totalFrames: trajResult.data.frames.length,
    };
  }

  // 轉換位置資料（幀索引）
  if (posResult.type === 'arrow') {
    frameIndex = buildFrameIndex(posResult.table, posResult.metadata.frameTimes);
  } else {
    frameIndex = jsonToFrameIndex(posResult.data);
  }

  // 計算時間範圍
  const frameTimes = metadata.frameTimes || [];
  const minTime = frameTimes.length > 0 ? frameTimes[0] : 0;
  const maxTime = frameTimes.length > 0 ? frameTimes[frameTimes.length - 1] : 0;

  rebuildFilteredTrips();
  console.log(`[ship-gis] 資料載入完成: ${tripsData.length} 艘船軌跡, ${frameTimes.length} 幀, 時間 ${minTime}-${maxTime}s`);

  // 初始化時間軸
  initTimeline({
    minTime,
    maxTime,
    baseTimestamp: metadata.baseTimestamp,
    onTimeChange: handleTimeChange,
  });
}

// === 時間變化回調 ===
function handleTimeChange(currentTime) {
  updateLayers(currentTime);
  updateStats(currentTime);
  updateTimeDisplay(currentTime);
  updateThemeFromTime(currentTime);
}

// === 時間顯示更新 ===
const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

function updateTimeDisplay(currentTime) {
  if (!metadata) return;
  const timeIcon = document.getElementById('timeIcon');
  const timeText = document.getElementById('timeText');
  if (!timeText) return;

  const ts = (metadata.baseTimestamp + currentTime) * 1000;
  const date = new Date(ts);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const w = WEEKDAYS[date.getDay()];
  const hh = String(date.getHours()).padStart(2, '0');
  const mm = String(date.getMinutes()).padStart(2, '0');
  const hour = date.getHours();

  timeText.textContent = `${y}/${m}/${d} (${w}) ${hh}:${mm}`;
  if (timeIcon) timeIcon.textContent = (hour >= 6 && hour < 18) ? '\u2600' : '\u263D';
}

// === 主題自動切換 ===
function updateThemeFromTime(currentTime) {
  if (themeMode !== 'auto' || !metadata) return;
  const ts = (metadata.baseTimestamp + currentTime) * 1000;
  const hour = new Date(ts).getHours();
  const targetTheme = (hour >= 6 && hour < 18) ? 'day' : 'night';
  applyTheme(targetTheme);
}

function applyTheme(theme) {
  const current = getCurrentTheme();
  if (theme === current) return;
  setTheme(theme);
  invalidateFrameCache();
  if (tripsData) bakeAllColors(tripsData, theme, currentColorPalette);
  updateLegend(currentMode, theme);
  map.once('style.load', () => {
    if (deckOverlay) {
      map.addControl(deckOverlay);
    }
    updateLayers(getCurrentTime());
  });
}

// === 圖層更新（核心）===
function updateLayers(currentTime) {
  if (!deckOverlay) return;

  let layers = [];
  const theme = getCurrentTheme();

  switch (currentMode) {
    case 'trajectory':
      // 軌跡模式每幀更新 currentTime（TripsLayer data 引用不變，只更新 uniform）
      if (_filteredTrips) {
        layers = createTrajectoryLayers(_filteredTrips, currentTime, theme);
      }
      break;
    case 'density':
    case 'hexbin': {
      // 幀快取：資料每 10 分鐘才變一次，同一幀 + 同模式/主題 → 跳過
      const frameIdx = getFrameIdx(currentTime);
      const key = `${currentMode}|${theme}|${frameIdx}`;
      if (key === _cachedLayerKey) return;
      _cachedLayerKey = key;
      const positions = getFramePositions(currentTime);
      if (positions.length > 0) {
        layers = currentMode === 'density'
          ? createGridLayers(positions, theme)
          : createHexagonLayers(positions, theme);
      }
      break;
    }
    case 'heatmap': {
      const frameIdx = getFrameIdx(currentTime);
      const key = `heatmap|${theme}|${frameIdx}`;
      if (key === _cachedLayerKey) return;
      _cachedLayerKey = key;
      // MapLibre 原生 heatmap — 不走 deck.gl，layers 保持空
      updateNativeHeatmap(map, frameIndex, frameIdx, theme);
      break;
    }
    case 'query':
      if (queryResults.length > 0) layers = createQueryLayers(queryResults, theme);
      if (queryShips.length > 0) layers.push(createQueryShipDots(queryShips));
      break;
  }

  // 港口圖層疊加（所有模式共用）
  if (showPorts && portFeatures) {
    const zoom = map ? map.getZoom() : 7;
    layers = layers.concat(createPortLayers(portFeatures, theme, zoom));
  }

  deckOverlay.setProps({ layers });
}

// === 二分搜尋最近幀索引 ===
function getFrameIdx(currentTime) {
  if (!frameIndex) return -1;
  const ft = frameIndex.frameTimes;
  if (ft.length === 0) return -1;
  let lo = 0, hi = ft.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if (ft[mid] < currentTime) lo = mid + 1;
    else hi = mid;
  }
  // lo 是第一個 >= currentTime 的幀，檢查 lo-1 是否更近
  if (lo > 0 && (currentTime - ft[lo - 1]) < (ft[lo] - currentTime)) {
    return lo - 1;
  }
  return lo;
}

// === 取得當前幀的船舶位置（帶快取）===
function getFramePositions(currentTime) {
  const idx = getFrameIdx(currentTime);
  if (idx < 0) return [];
  if (idx === _cachedFrameIdx) return _cachedPositions;
  _cachedFrameIdx = idx;
  _cachedPositions = frameIndex.getFrame(idx);
  return _cachedPositions;
}

// === 統計面板 ===
let _lastStatsKey = '';

function updateStats(currentTime) {
  const statShips = document.getElementById('statShips');
  if (!statShips) return;

  if (currentMode === 'trajectory' && _filteredTrips) {
    let count = 0;
    for (const trip of _filteredTrips) {
      const ts = trip.timestamps;
      if (ts.length > 0 && currentTime >= ts[0] && currentTime <= ts[ts.length - 1]) {
        count++;
      }
    }
    statShips.textContent = count.toLocaleString();
  } else if (frameIndex) {
    // 幀快取：同一幀不重算
    const frameIdx = getFrameIdx(currentTime);
    const key = `stats|${frameIdx}`;
    if (key === _lastStatsKey) return;
    _lastStatsKey = key;
    statShips.textContent = frameIndex.getFrameCount(frameIdx).toLocaleString();
  }
}

// === Tab 模式切換 ===
function setupTabs() {
  const tabs = document.querySelectorAll('.tab-btn');
  const modeTitle = document.getElementById('modeTitle');
  const modeNames = {
    trajectory: '軌跡動畫', density: '密度熱區',
    hexbin: '六角網格', heatmap: '熱力圖', query: '軌跡查詢',
  };

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      const prevMode = currentMode;
      const mode = tab.dataset.mode;
      currentMode = mode;
      invalidateFrameCache();
      _lastStatsKey = '';

      // 離開 heatmap 模式時隱藏原生 MapLibre layer
      if (prevMode === 'heatmap' && mode !== 'heatmap') {
        hideNativeHeatmap(map);
      }

      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      if (modeTitle) modeTitle.textContent = modeNames[mode] || mode;

      // 查詢模式特殊處理
      if (mode === 'query') enableQueryMode();
      else disableQueryMode();

      updateLegend(mode, getCurrentTheme());
      updateLayers(getCurrentTime());
      updateStats(getCurrentTime());
    });
  });
}

// === 船舶類型篩選 ===
function setupFilters() {
  const container = document.getElementById('filterChecks');
  const toggleBtn = document.getElementById('filterToggle');
  if (!container) return;

  for (const [key, { label }] of Object.entries(VESSEL_CATEGORIES)) {
    const labelEl = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.value = key;
    checkbox.addEventListener('change', onFilterChange);
    labelEl.appendChild(checkbox);
    labelEl.appendChild(document.createTextNode(label));
    container.appendChild(labelEl);
  }

  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const cbs = container.querySelectorAll('input[type="checkbox"]');
      const allChecked = Array.from(cbs).every(cb => cb.checked);
      cbs.forEach(cb => { cb.checked = !allChecked; });
      toggleBtn.textContent = allChecked ? '全選' : '取消全選';
      onFilterChange();
    });
  }
}

function onFilterChange() {
  const cbs = document.querySelectorAll('#filterChecks input[type="checkbox"]');
  const checked = Array.from(cbs).filter(cb => cb.checked).map(cb => cb.value);
  activeCategories = (checked.length === Object.keys(VESSEL_CATEGORIES).length)
    ? null
    : new Set(checked);
  rebuildFilteredTrips(); // 只在篩選條件變化時重建，後續每幀用同一引用
  updateLayers(getCurrentTime());
  updateStats(getCurrentTime());
}

// === 港口圖層切換 ===
function setupPortToggle() {
  const cb = document.getElementById('portToggle');
  if (!cb) return;
  cb.addEventListener('change', () => {
    showPorts = cb.checked;
    updateLayers(getCurrentTime());
  });
}

// === 通用下拉選單工具 ===
function setupDropdown(btnId, menuId, onSelect) {
  const btn = document.getElementById(btnId);
  const menu = document.getElementById(menuId);
  if (!btn || !menu) return;

  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    // 關閉其他開啟的下拉
    document.querySelectorAll('.dropdown-menu.show').forEach(m => {
      if (m !== menu) m.classList.remove('show');
    });
    menu.classList.toggle('show');
  });

  menu.addEventListener('click', (e) => e.stopPropagation());

  const items = menu.querySelectorAll('.dropdown-item');
  items.forEach(item => {
    item.addEventListener('click', () => {
      items.forEach(i => i.classList.remove('active'));
      item.classList.add('active');
      menu.classList.remove('show');
      onSelect(item);
    });
  });
}

// === 主題下拉選單 ===
function setupThemeDropdown() {
  setupDropdown('themeDropdownBtn', 'themeMenu', (item) => {
    const mode = item.dataset.theme;
    const label = document.getElementById('themeLabel');
    if (label) label.textContent = item.textContent;
    setThemeMode(mode);
  });

  // 點擊外部關閉所有下拉
  document.addEventListener('click', () => {
    document.querySelectorAll('.dropdown-menu.show').forEach(m => m.classList.remove('show'));
  });
}

function setThemeMode(mode) {
  themeMode = mode;
  if (mode === 'auto') {
    updateThemeFromTime(getCurrentTime());
  } else {
    applyTheme(mode);
  }
}

// === 軌跡配色選擇器（下拉）===
function setupColorPaletteSelector() {
  setupDropdown('paletteDropdownBtn', 'paletteMenu', (item) => {
    currentColorPalette = item.dataset.palette;
    const label = document.getElementById('paletteLabel');
    if (label) label.textContent = item.textContent;
    const theme = getCurrentTheme();
    if (tripsData) {
      bakeAllColors(tripsData, theme, currentColorPalette);
      updateLayers(getCurrentTime());
    }
  });
}

// === Info Modal ===
function setupInfoModal() {
  const modal = document.getElementById('infoModal');
  const openBtn = document.getElementById('infoBtn');
  const closeBtn = document.getElementById('modalClose');
  if (!modal) return;

  if (openBtn) {
    openBtn.addEventListener('click', () => modal.classList.add('show'));
  }
  if (closeBtn) {
    closeBtn.addEventListener('click', () => modal.classList.remove('show'));
  }
  // overlay click 關閉
  modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.classList.remove('show');
  });
  // ESC 關閉
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') modal.classList.remove('show');
  });
}

// === 查詢 API 檢測 ===
async function checkQueryApi() {
  try {
    const res = await fetch('/api/ships/latest', { method: 'HEAD' });
    if (res.ok) {
      const queryTab = document.getElementById('query-tab');
      if (queryTab) queryTab.style.display = '';
    }
  } catch { /* API 不可用 */ }
}

// === 啟動 ===
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
