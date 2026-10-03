/**
 * 前端工具函数库
 * 数字格式化、日期处理、DOM 操作等
 */

/**
 * 格式化金额 - 添加千分位分隔符
 * @param {number} value - 数值
 * @param {number} decimals - 小数位数，默认 2
 * @returns {string} 格式化后的字符串，如 "1,234.56"
 */
function formatCurrency(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }

  return new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  }).format(value);
}

/**
 * 格式化金额（带货币符号）
 * @param {number} value - 数值
 * @param {number} decimals - 小数位数，默认 2
 * @returns {string} 格式化后的字符串，如 "¥1,234.56"
 */
function formatMoney(value, decimals = 2) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }

  return '¥' + formatCurrency(value, decimals);
}

/**
 * 格式化大额数字为缩写形式
 * @param {number} value - 数值
 * @param {number} decimals - 小数位数，默认 1
 * @returns {string} 格式化后的字符串，如 "1.2万" 或 "15.3万"
 */
function formatLargeNumber(value, decimals = 1) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }

  const absValue = Math.abs(value);
  const sign = value < 0 ? '-' : '';

  if (absValue >= 100000000) {
    // 亿
    return sign + (absValue / 100000000).toFixed(decimals) + '亿';
  } else if (absValue >= 10000) {
    // 万
    return sign + (absValue / 10000).toFixed(decimals) + '万';
  } else {
    return sign + absValue.toFixed(decimals);
  }
}

/**
 * 格式化百分比
 * @param {number} value - 数值（小数形式，如 0.0524 表示 5.24%）
 * @param {number} decimals - 小数位数，默认 2
 * @param {boolean} showSign - 是否显示正负号，默认 true
 * @returns {string} 格式化后的字符串，如 "+5.24%"
 */
function formatPercentage(value, decimals = 2, showSign = true) {
  if (value === null || value === undefined || isNaN(value)) {
    return '-';
  }

  const percentValue = value * 100;
  const sign = showSign && percentValue > 0 ? '+' : '';

  return sign + percentValue.toFixed(decimals) + '%';
}

/**
 * 格式化日期为相对时间或绝对时间
 * @param {string|Date} date - 日期
 * @returns {string} 格式化后的字符串
 */
function formatDate(date) {
  if (!date) return '-';

  const d = typeof date === 'string' ? new Date(date) : date;
  if (isNaN(d.getTime())) return '-';

  const now = new Date();
  const diffMs = now - d;
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  // 如果是今天
  if (diffDays === 0) {
    const hours = d.getHours().toString().padStart(2, '0');
    const minutes = d.getMinutes().toString().padStart(2, '0');
    return `今天 ${hours}:${minutes}`;
  }

  // 如果是昨天
  if (diffDays === 1) {
    return '昨天';
  }

  // 如果在 7 天内
  if (diffDays < 7) {
    return `${diffDays} 天前`;
  }

  // 否则显示完整日期
  const year = d.getFullYear();
  const month = (d.getMonth() + 1).toString().padStart(2, '0');
  const day = d.getDate().toString().padStart(2, '0');

  return `${year}-${month}-${day}`;
}

/**
 * 防抖函数
 * @param {Function} func - 要执行的函数
 * @param {number} wait - 等待时间（毫秒）
 * @returns {Function} 防抖后的函数
 */
function debounce(func, wait = 300) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * 节流函数
 * @param {Function} func - 要执行的函数
 * @param {number} limit - 时间间隔（毫秒）
 * @returns {Function} 节流后的函数
 */
function throttle(func, limit = 300) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}

/**
 * 显示 Toast 提示
 * @param {string} message - 提示消息
 * @param {string} type - 类型：'success' | 'error' | 'warning' | 'info'
 * @param {number} duration - 显示时长（毫秒），默认 3000
 */
function showToast(message, type = 'info', duration = 3000) {
  // 移除已存在的 toast
  const existingToast = document.querySelector('.toast');
  if (existingToast) {
    existingToast.remove();
  }

  // 创建 toast 元素
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.setAttribute('role', 'alert');
  toast.setAttribute('aria-live', 'polite');

  // 根据类型选择图标
  let icon = '';
  switch (type) {
    case 'success':
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>';
      break;
    case 'error':
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>';
      break;
    case 'warning':
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>';
      break;
    default:
      icon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>';
  }

  toast.innerHTML = `
    <div class="toast-icon">${icon}</div>
    <div class="toast-message">${message}</div>
  `;

  document.body.appendChild(toast);

  // 触发动画
  setTimeout(() => toast.classList.add('toast-show'), 10);

  // 自动移除
  setTimeout(() => {
    toast.classList.remove('toast-show');
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

/**
 * 获取颜色类名（根据数值正负）
 * @param {number} value - 数值
 * @returns {string} CSS 类名
 */
function getColorClass(value) {
  if (value === null || value === undefined || isNaN(value)) {
    return '';
  }
  return value >= 0 ? 'text-success' : 'text-danger';
}

/**
 * 平滑滚动到指定元素
 * @param {string|HTMLElement} target - 目标元素或选择器
 * @param {number} offset - 偏移量（像素）
 */
function smoothScrollTo(target, offset = 0) {
  const element = typeof target === 'string' ? document.querySelector(target) : target;
  if (!element) return;

  const targetPosition = element.getBoundingClientRect().top + window.pageYOffset - offset;

  window.scrollTo({
    top: targetPosition,
    behavior: 'smooth'
  });
}

// 导出函数（如果使用模块化）
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    formatCurrency,
    formatMoney,
    formatLargeNumber,
    formatPercentage,
    formatDate,
    debounce,
    throttle,
    showToast,
    getColorClass,
    smoothScrollTo
  };
}
