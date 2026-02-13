/**
 * 時間軸控制模組
 * 管理播放/暫停、速度、slider、鍵盤快捷鍵。
 */
import { PLAY_SPEEDS } from '../utils/constants.js';

let isPlaying = false;
let playSpeed = 1;
let currentTime = 0;
let minTime = 0;
let maxTime = 0;
let rafId = null;
let lastTick = 0;
let baseTimestamp = 0; // unix epoch of time 0

// 回調：當 currentTime 變化時通知外部
let onTimeChange = null;

/**
 * 初始化時間軸控制。
 * @param {object} opts
 * @param {number} opts.minTime - 起始時間（秒）
 * @param {number} opts.maxTime - 結束時間（秒）
 * @param {number} opts.baseTimestamp - base unix timestamp
 * @param {function} opts.onTimeChange - 時間變化回調 (currentTime) => void
 */
export function initTimeline(opts) {
  minTime = opts.minTime;
  maxTime = opts.maxTime;
  baseTimestamp = opts.baseTimestamp || 0;
  currentTime = minTime;
  onTimeChange = opts.onTimeChange;

  setupSlider();
  setupPlayButton();
  setupSpeedButtons();
  setupKeyboard();

  // 初始渲染
  updateTimeDisplay();
  if (onTimeChange) onTimeChange(currentTime);
}

export function getCurrentTime() {
  return currentTime;
}

export function setCurrentTime(t) {
  currentTime = Math.max(minTime, Math.min(maxTime, t));
  updateSliderPosition();
  updateTimeDisplay();
  if (onTimeChange) onTimeChange(currentTime);
}

export function getIsPlaying() {
  return isPlaying;
}

// === Slider ===
function setupSlider() {
  const slider = document.getElementById('timeline');
  if (!slider) return;

  slider.min = 0;
  slider.max = 1000; // 用 0-1000 作為精度
  slider.value = 0;

  slider.addEventListener('input', (e) => {
    const ratio = parseInt(e.target.value) / 1000;
    currentTime = minTime + ratio * (maxTime - minTime);
    updateTimeDisplay();
    if (onTimeChange) onTimeChange(currentTime);
  });
}

function updateSliderPosition() {
  const slider = document.getElementById('timeline');
  if (!slider) return;
  const ratio = (maxTime > minTime) ? (currentTime - minTime) / (maxTime - minTime) : 0;
  slider.value = Math.round(ratio * 1000);
}

// === 播放/暫停 ===
function setupPlayButton() {
  const btn = document.getElementById('playBtn');
  if (!btn) return;
  btn.addEventListener('click', togglePlay);
}

export function togglePlay() {
  if (isPlaying) {
    stopPlay();
  } else {
    startPlay();
  }
}

function startPlay() {
  isPlaying = true;
  lastTick = performance.now();
  updatePlayButtonUI();

  // 如果已經到底，從頭開始
  if (currentTime >= maxTime - 1) {
    currentTime = minTime;
  }

  function tick(now) {
    if (!isPlaying) return;

    const elapsed = (now - lastTick) / 1000; // 秒
    lastTick = now;

    // 前進量 = 真實秒 × 速度 × 600（10 分鐘的秒數，讓 1x 速度 = 1 秒播一幀）
    currentTime += elapsed * playSpeed * 600;

    if (currentTime >= maxTime) {
      currentTime = minTime; // 循環播放
    }

    updateSliderPosition();
    updateTimeDisplay();
    if (onTimeChange) onTimeChange(currentTime);

    rafId = requestAnimationFrame(tick);
  }

  rafId = requestAnimationFrame(tick);
}

function stopPlay() {
  isPlaying = false;
  if (rafId) {
    cancelAnimationFrame(rafId);
    rafId = null;
  }
  updatePlayButtonUI();
}

function updatePlayButtonUI() {
  const btn = document.getElementById('playBtn');
  if (!btn) return;
  btn.innerHTML = isPlaying ? '&#9646;&#9646;' : '&#9654;';
}

// === 速度控制 ===
function setupSpeedButtons() {
  const container = document.getElementById('speedControls');
  if (!container) return;

  container.innerHTML = '';
  for (const speed of PLAY_SPEEDS) {
    const btn = document.createElement('button');
    btn.className = 'speed-btn' + (speed === playSpeed ? ' active' : '');
    btn.textContent = `${speed}x`;
    btn.addEventListener('click', () => {
      playSpeed = speed;
      container.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
    container.appendChild(btn);
  }
}

// === 鍵盤快捷鍵 ===
function setupKeyboard() {
  document.addEventListener('keydown', (e) => {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

    switch (e.code) {
      case 'Space':
        e.preventDefault();
        togglePlay();
        break;
      case 'ArrowRight':
        e.preventDefault();
        setCurrentTime(currentTime + 600); // 前進 10 分鐘
        break;
      case 'ArrowLeft':
        e.preventDefault();
        setCurrentTime(currentTime - 600); // 後退 10 分鐘
        break;
    }
  });
}

// === 時間顯示 ===
function updateTimeDisplay() {
  const el = document.getElementById('timeDisplay');
  if (!el) return;

  const unixTs = baseTimestamp + currentTime;
  const date = new Date(unixTs * 1000);
  const pad = (n) => String(n).padStart(2, '0');

  el.textContent = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
