import { MapboxOverlay } from '@deck.gl/mapbox';
import { initMap, toggleTheme, getCurrentTheme } from './map.js';
import { loadTrajectoryData, loadPositionsData } from './data/loader.js';
import { arrowToTrips, buildFrameIndex, jsonToTrips, jsonToFrameIndex } from './data/transform.js';
import { createTrajectoryLayers, preprocessTrips } from './layers/trips.js';
import { createGridLayers } from './layers/grid.js';
import { createHexagonLayers } from './layers/hexagon.js';
import { createHeatmapLayers } from './layers/heatmap.js';
import { createQueryLayers, createQueryShipDots } from './layers/path.js';
import { initTimeline, getCurrentTime } from './controls/timeline.js';
import { initQueryControls, enableQueryMode, disableQueryMode, handlePick } from './controls/query.js';
import { updateLegend } from './ui/legends.js';
import { VESSEL_CATEGORIES } from './utils/constants.js';
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

    // 隱藏 loading
    const loading = document.getElementById('loading');
    if (loading) loading.style.display = 'none';

    // 設置 UI
    setupTabs();
    setupFilters();
    setupThemeToggle();
    initQueryControls({
      map,
      onQueryResult: (results) => { queryResults = results; updateLayers(getCurrentTime()); },
      onQueryShipsLoad: (ships) => { queryShips = ships; updateLayers(getCurrentTime()); },
    });
    checkQueryApi();
    updateLegend(currentMode, getCurrentTheme());
  });
}

// === 資料載入 ===
async function loadData() {
  const loadingText = document.querySelector('.loading-text');
  if (loadingText) loadingText.textContent = '載入船舶資料中...';

  // 平行載入
  const [trajResult, posResult] = await Promise.all([
    loadTrajectoryData(),
    loadPositionsData(),
  ]);

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
}

// === 圖層更新（核心）===
function updateLayers(currentTime) {
  if (!deckOverlay) return;

  let layers = [];
  const theme = getCurrentTheme();

  switch (currentMode) {
    case 'trajectory':
      // 軌跡模式每幀都需更新（TripsLayer 用 currentTime 做動畫插值）
      if (tripsData) {
        layers = createTrajectoryLayers(tripsData, currentTime, theme, activeCategories);
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
      // 用 TypedArray 路徑：零物件分配，直接送 GPU
      const flatData = frameIndex.getFramePositionsFlat(frameIdx);
      if (flatData && flatData.count > 0) layers = createHeatmapLayers(flatData, theme);
      break;
    }
    case 'query':
      if (queryResults.length > 0) layers = createQueryLayers(queryResults, theme);
      if (queryShips.length > 0) layers.push(createQueryShipDots(queryShips));
      break;
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

  if (currentMode === 'trajectory' && tripsData) {
    let count = 0;
    for (const trip of tripsData) {
      if (activeCategories) {
        const cat = getCategoryForVessel(trip.vesselType);
        if (!activeCategories.has(cat)) continue;
      }
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

function getCategoryForVessel(vtype) {
  for (const [key, { codes }] of Object.entries(VESSEL_CATEGORIES)) {
    if (codes.includes(vtype)) return key;
  }
  return 'unknown';
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
      const mode = tab.dataset.mode;
      currentMode = mode;
      invalidateFrameCache();
      _lastStatsKey = '';

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
  updateLayers(getCurrentTime());
  updateStats(getCurrentTime());
}

// === 主題切換 ===
function setupThemeToggle() {
  const themeBtn = document.getElementById('theme-toggle');
  if (!themeBtn) return;

  themeBtn.addEventListener('click', () => {
    const theme = toggleTheme();
    themeBtn.textContent = theme === 'day' ? '\u263D' : '\u2600';
    invalidateFrameCache();
    updateLegend(currentMode, theme);
    map.once('style.load', () => {
      if (deckOverlay) {
        map.addControl(deckOverlay);
      }
      updateLayers(getCurrentTime());
    });
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
