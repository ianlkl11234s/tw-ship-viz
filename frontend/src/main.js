import { MapboxOverlay } from '@deck.gl/mapbox';
import { initMap, toggleTheme, getCurrentTheme, getMap } from './map.js';
import { loadArrowData } from './data/loader.js';
import {
  transformTrajectoryArrow, transformPositionsArrow,
  transformTrajectoryJson, transformPositionsJson,
} from './data/transform.js';
import { createTripsLayers } from './layers/trips.js';
import { createGridLayers } from './layers/grid.js';
import { createHexagonLayers } from './layers/hexagon.js';
import { createHeatmapLayers } from './layers/heatmap.js';
import { createQueryLayers, createQueryShipDots } from './layers/path.js';
import { initTimeline, setMode, getCurrentTime, destroyTimeline } from './controls/timeline.js';
import { initQueryControls, enableQueryMode, disableQueryMode, handlePick } from './controls/query.js';
import { updateLegend } from './ui/legends.js';
import { VESSEL_CATEGORIES } from './utils/constants.js';
import './style.css';

// === 全域狀態 ===
let map = null;
let deckOverlay = null;
let tripsData = null;       // TripsLayer 用的資料
let positionsData = null;    // 密度/六角/熱力圖用的 per-frame 資料
let currentMode = 'trajectory';
let activeCategories = null; // null = 全部
let queryResults = [];       // 查詢模式的軌跡結果
let queryShips = [];         // 查詢模式的船舶散點

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

    // 初始圖例
    updateLegend(currentMode, getCurrentTheme());
  });
}

// === 資料載入 ===
async function loadData() {
  const loadingText = document.querySelector('.loading-text');

  // 平行載入兩個資料集
  if (loadingText) loadingText.textContent = '載入船舶資料中...';

  const [trajResult, posResult] = await Promise.all([
    loadArrowData('trajectory'),
    loadArrowData('positions'),
  ]);

  // 轉換資料
  if (loadingText) loadingText.textContent = '處理資料中...';

  if (trajResult.format === 'arrow') {
    tripsData = transformTrajectoryArrow(trajResult.table);
  } else {
    tripsData = transformTrajectoryJson(trajResult.data);
  }

  if (posResult.format === 'arrow') {
    positionsData = transformPositionsArrow(posResult.table, posResult.metadata);
  } else {
    positionsData = transformPositionsJson(posResult.data);
  }

  // 初始化時間軸（使用 positionsData 的幀時間）
  initTimeline({
    frameTimes: positionsData.frameTimes,
    baseDatetime: positionsData.baseDatetime,
    onTimeChange: handleTimeChange,
  });

  // 初始渲染
  updateLayers(getCurrentTime());

  // 更新統計
  updateStats(getCurrentTime());
}

// === 時間變化回調 ===
function handleTimeChange(currentTime) {
  updateLayers(currentTime);
  updateStats(currentTime);
}

// === 圖層更新 ===
function updateLayers(currentTime) {
  if (!deckOverlay) return;

  let layers = [];
  const theme = getCurrentTheme();

  switch (currentMode) {
    case 'trajectory':
      if (tripsData) {
        layers = createTripsLayers(tripsData, currentTime, theme, activeCategories);
      }
      break;
    case 'density':
    case 'hexbin':
    case 'heatmap': {
      const framePositions = getFramePositions(currentTime);
      if (framePositions.length > 0) {
        if (currentMode === 'density') {
          layers = createGridLayers(framePositions, theme);
        } else if (currentMode === 'hexbin') {
          layers = createHexagonLayers(framePositions, theme);
        } else {
          layers = createHeatmapLayers(framePositions, theme);
        }
      }
      break;
    }
    case 'query':
      if (queryResults.length > 0) {
        layers = createQueryLayers(queryResults, theme);
      }
      if (queryShips.length > 0) {
        layers.push(createQueryShipDots(queryShips));
      }
      break;
  }

  deckOverlay.setProps({ layers });
}

// === 取得當前幀的船舶位置（密度/六角/熱力圖用）===
function getFramePositions(currentTime) {
  if (!positionsData) return [];

  // 找最接近的幀
  const frameTimes = positionsData.frameTimes;
  let closest = frameTimes[0];
  let minDiff = Math.abs(closest - currentTime);
  for (const ft of frameTimes) {
    const diff = Math.abs(ft - currentTime);
    if (diff < minDiff) {
      minDiff = diff;
      closest = ft;
    }
  }

  const frame = positionsData.frames.get(closest);
  if (!frame) return [];

  // 篩選船舶類別
  return activeCategories
    ? frame.filter(s => activeCategories.has(s.category))
    : frame;
}

// === 統計面板更新 ===
function updateStats(currentTime) {
  const statShips = document.getElementById('statShips');
  if (!statShips) return;

  if (currentMode === 'trajectory' && tripsData) {
    // 計算在 currentTime 可見的船舶數
    let count = 0;
    for (const trip of tripsData) {
      if (activeCategories && !activeCategories.has(trip.category)) continue;
      const ts = trip.timestamps;
      if (ts.length > 0 && currentTime >= ts[0] && currentTime <= ts[ts.length - 1]) {
        count++;
      }
    }
    statShips.textContent = count.toLocaleString();
  } else if (positionsData) {
    // 找最接近的幀
    const frameTimes = positionsData.frameTimes;
    let closest = frameTimes[0];
    for (const ft of frameTimes) {
      if (Math.abs(ft - currentTime) < Math.abs(closest - currentTime)) closest = ft;
    }
    const frame = positionsData.frames.get(closest);
    if (frame) {
      const filtered = activeCategories
        ? frame.filter(s => activeCategories.has(s.category))
        : frame;
      statShips.textContent = filtered.length.toLocaleString();
    }
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
      const mode = tab.dataset.mode;
      currentMode = mode;
      setMode(mode);

      // 更新 tab 樣式
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');

      // 更新標題
      if (modeTitle) modeTitle.textContent = modeNames[mode] || mode;

      // 查詢模式特殊處理
      if (mode === 'query') {
        enableQueryMode();
      } else {
        disableQueryMode();
      }

      // 更新圖例
      updateLegend(mode, getCurrentTheme());

      // 重新渲染
      updateLayers(getCurrentTime());
      updateStats(getCurrentTime());
    });
  });

  // 檢查 API 可用性（查詢模式需要後端）
  checkQueryApi();
}

// === 船舶類型篩選 ===
function setupFilters() {
  const container = document.getElementById('filterChecks');
  const toggleBtn = document.getElementById('filterToggle');
  if (!container) return;

  // 建立 checkbox
  for (const [key, { label }] of Object.entries(VESSEL_CATEGORIES)) {
    const labelEl = document.createElement('label');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.value = key;
    checkbox.addEventListener('change', updateFilters);
    labelEl.appendChild(checkbox);
    labelEl.appendChild(document.createTextNode(label));
    container.appendChild(labelEl);
  }

  // 全選/取消全選
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      const checkboxes = container.querySelectorAll('input[type="checkbox"]');
      const allChecked = Array.from(checkboxes).every(cb => cb.checked);
      checkboxes.forEach(cb => { cb.checked = !allChecked; });
      toggleBtn.textContent = allChecked ? '全選' : '取消全選';
      updateFilters();
    });
  }
}

function updateFilters() {
  const container = document.getElementById('filterChecks');
  const checkboxes = container.querySelectorAll('input[type="checkbox"]');
  const checked = Array.from(checkboxes).filter(cb => cb.checked).map(cb => cb.value);

  if (checked.length === Object.keys(VESSEL_CATEGORIES).length) {
    activeCategories = null; // 全部
  } else {
    activeCategories = new Set(checked);
  }

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

    // deck.gl 在 map style 變更後需要重新加 overlay
    // MapLibre setStyle 會清掉所有 controls，需要重新 add
    map.once('style.load', () => {
      updateLayers(getCurrentTime());
      updateLegend(currentMode, theme);
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
  } catch {
    // API 不可用，隱藏查詢 tab
  }
}

// === 啟動 ===
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
