import { initMap, toggleTheme, getCurrentTheme } from './map.js';
import './style.css';

// === 全域狀態 ===
let map = null;

// === 初始化 ===
function init() {
  map = initMap('map');

  // 地圖載入完成後隱藏 loading
  map.on('load', () => {
    const loading = document.getElementById('loading');
    if (loading) loading.style.display = 'none';
    console.log('[ship-gis] MapLibre 地圖初始化完成');
  });

  // 主題切換按鈕
  const themeBtn = document.getElementById('theme-toggle');
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const theme = toggleTheme();
      themeBtn.textContent = theme === 'day' ? '\u263D' : '\u2600';
    });
  }
}

// DOM 就緒後啟動
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
