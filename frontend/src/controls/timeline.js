import { BASE_INTERVALS, PLAY_SPEEDS } from '../utils/constants.js';

/**
 * 時間軸控制器：播放/暫停、速度、slider、鍵盤快捷鍵。
 */

let isPlaying = false;
let playSpeed = 1;
let currentTime = 0;
let minTime = 0;
let maxTime = 0;
let rafId = null;
let lastTickTime = 0;

/** @type {Function} 外部回調：currentTime 變化時通知 */
let onTimeChange = null;

/** @type {string} 當前模式 */
let currentMode = 'trajectory';

// DOM elements
let playBtn, slider, speedBtns, timeDisplay;

/**
 * 初始化時間軸控制器。
 * @param {Object} opts
 * @param {number[]} opts.frameTimes - 所有幀的時間（秒）
 * @param {string} opts.baseDatetime - 起始時間 ISO string
 * @param {Function} opts.onTimeChange - currentTime 更新回調
 */
export function initTimeline(opts) {
  minTime = opts.frameTimes[0] || 0;
  maxTime = opts.frameTimes[opts.frameTimes.length - 1] || 0;
  currentTime = minTime;
  onTimeChange = opts.onTimeChange;

  playBtn = document.getElementById('playBtn');
  slider = document.getElementById('timeline');
  timeDisplay = document.getElementById('timeDisplay');

  // 初始化 slider 範圍
  slider.min = minTime;
  slider.max = maxTime;
  slider.value = minTime;
  slider.step = 1;

  // 播放按鈕
  playBtn.addEventListener('click', togglePlay);

  // slider 拖曳
  slider.addEventListener('input', (e) => {
    currentTime = parseFloat(e.target.value);
    notifyTimeChange();
  });

  // 速度按鈕
  initSpeedButtons();

  // 鍵盤快捷鍵
  document.addEventListener('keydown', handleKeyboard);

  // 初始更新
  updateTimeDisplay(opts.baseDatetime);
  notifyTimeChange();
}

/**
 * 設定當前模式（影響播放間隔）。
 */
export function setMode(mode) {
  currentMode = mode;
}

/**
 * 取得當前播放時間。
 */
export function getCurrentTime() {
  return currentTime;
}

/**
 * 外部設定當前時間。
 */
export function setCurrentTime(time) {
  currentTime = Math.max(minTime, Math.min(maxTime, time));
  slider.value = currentTime;
  notifyTimeChange();
}

function togglePlay() {
  isPlaying = !isPlaying;
  playBtn.innerHTML = isPlaying ? '&#9208;' : '&#9654;';
  if (isPlaying) {
    lastTickTime = performance.now();
    rafId = requestAnimationFrame(tick);
  } else {
    if (rafId) cancelAnimationFrame(rafId);
    rafId = null;
  }
}

function tick(now) {
  if (!isPlaying) return;

  const elapsed = now - lastTickTime;
  const interval = getFrameInterval();

  // 根據經過的實際時間推進 currentTime
  // interval ms 對應 600 秒（10 分鐘一幀）
  const timeAdvance = (elapsed / interval) * 600;
  currentTime += timeAdvance;
  lastTickTime = now;

  // 到底時循環
  if (currentTime > maxTime) {
    currentTime = minTime;
  }

  slider.value = currentTime;
  notifyTimeChange();

  rafId = requestAnimationFrame(tick);
}

function getFrameInterval() {
  const base = BASE_INTERVALS[currentMode] || 1000;
  return base / playSpeed;
}

function notifyTimeChange() {
  updateTimeDisplay();
  if (onTimeChange) onTimeChange(currentTime);
}

function updateTimeDisplay(baseDatetime) {
  if (!timeDisplay) return;
  // currentTime 是相對秒數，需要 baseDatetime 來算絕對時間
  // baseDatetime 在 initTimeline 時存起來
  if (baseDatetime) {
    updateTimeDisplay._baseDt = new Date(baseDatetime.replace(' ', 'T'));
  }
  if (!updateTimeDisplay._baseDt) return;

  const dt = new Date(updateTimeDisplay._baseDt.getTime() + currentTime * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  timeDisplay.textContent =
    `${dt.getFullYear()}-${pad(dt.getMonth()+1)}-${pad(dt.getDate())} ` +
    `${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
}

function initSpeedButtons() {
  const container = document.getElementById('speedControls');
  if (!container) return;
  container.innerHTML = '';

  for (const speed of PLAY_SPEEDS) {
    const btn = document.createElement('button');
    btn.className = `speed-btn${speed === playSpeed ? ' active' : ''}`;
    btn.textContent = `${speed}x`;
    btn.addEventListener('click', () => {
      playSpeed = speed;
      container.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
    container.appendChild(btn);
  }
}

function handleKeyboard(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

  switch (e.code) {
    case 'Space':
      e.preventDefault();
      togglePlay();
      break;
    case 'ArrowLeft':
      e.preventDefault();
      setCurrentTime(currentTime - 600); // 後退一幀（10分鐘）
      break;
    case 'ArrowRight':
      e.preventDefault();
      setCurrentTime(currentTime + 600); // 前進一幀
      break;
  }
}

/**
 * 清理資源。
 */
export function destroyTimeline() {
  isPlaying = false;
  if (rafId) cancelAnimationFrame(rafId);
  document.removeEventListener('keydown', handleKeyboard);
}
