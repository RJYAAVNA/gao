// 多银行理财台账 - Main JavaScript
// PWA & UI Interactions

// Service Worker Registration
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.getRegistrations().then(async registrations => {
        for (const registration of registrations) {
          if (new URL(registration.scope).pathname === '/static/') await registration.unregister();
        }
        return navigator.serviceWorker.register('/sw.js', {scope: '/'});
      })
      .then(registration => {
        console.log('ServiceWorker registered:', registration.scope);
      })
      .catch(err => {
        console.log('ServiceWorker registration failed:', err);
      });
  });
}

// Install PWA Prompt
let deferredPrompt;
const installButton = document.getElementById('install-button');

window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;

  if (installButton) {
    installButton.style.display = 'block';
    installButton.addEventListener('click', async () => {
      if (deferredPrompt) {
        deferredPrompt.prompt();
        const { outcome } = await deferredPrompt.userChoice;
        console.log(`用户选择: ${outcome}`);
        deferredPrompt = null;
        installButton.style.display = 'none';
      }
    });
  }
});

// Note: Import utils.js for formatCurrency, formatMoney, formatPercentage, etc.
// These are kept here for backward compatibility but prefer using utils.js functions

// Animate Number with formatting
function animateNumber(element, targetValue, duration = 1000, formatter = null) {
  const startValue = 0;
  const startTime = performance.now();

  // Use provided formatter or default to formatMoney from utils
  const formatFunc = formatter || ((v) => formatMoney(v, 2));

  function update(currentTime) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);

    // Easing function
    const easeOutQuart = 1 - Math.pow(1 - progress, 4);
    const currentValue = startValue + (targetValue - startValue) * easeOutQuart;

    element.textContent = formatFunc(currentValue);

    if (progress < 1) {
      requestAnimationFrame(update);
    } else {
      element.textContent = formatFunc(targetValue);
    }
  }

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    element.textContent = formatFunc(targetValue);
  } else {
    requestAnimationFrame(update);
  }
}

// Stagger Animation for Grid Items
function staggerGridItems() {
  const items = document.querySelectorAll('.grid-item');

  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    items.forEach(item => {
      item.style.opacity = '1';
      item.style.transform = 'none';
    });
    return;
  }

  items.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateY(16px) scale(0.92)';

    setTimeout(() => {
      item.style.transition = 'opacity 400ms ease, transform 400ms cubic-bezier(0.34, 1.56, 0.64, 1)';
      item.style.opacity = '1';
      item.style.transform = 'translateY(0) scale(1)';
    }, index * 60);
  });
}

// Initialize on DOM Ready
document.addEventListener('DOMContentLoaded', () => {
  // Animate numbers on page load
  const valueElements = document.querySelectorAll('[data-animate-value]');
  valueElements.forEach(el => {
    const targetValue = parseFloat(el.dataset.animateValue);
    if (!isNaN(targetValue)) {
      animateNumber(el, targetValue);
    }
  });

  // Stagger grid items
  if (document.querySelector('.grid-item')) {
    staggerGridItems();
  }

  // Handle list item clicks
  const listItems = document.querySelectorAll('.list-item[data-href]');
  listItems.forEach(item => {
    item.addEventListener('click', () => {
      window.location.href = item.dataset.href;
    });

    // Make keyboard accessible
    item.setAttribute('tabindex', '0');
    item.setAttribute('role', 'link');
    item.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        window.location.href = item.dataset.href;
      }
    });
  });
});

// Export utilities for use in other modules
window.ledgerApp = {
  formatCurrency,
  formatPercentage,
  formatDate,
  animateNumber
};
