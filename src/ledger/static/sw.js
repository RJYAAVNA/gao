// Service Worker for 多银行理财台账 PWA
// Version 1.0.0

const CACHE_NAME = 'ledger-v1.0.0';
const RUNTIME_CACHE = 'ledger-runtime-v1.0.0';
const OFFLINE_URL = '/offline';

// 核心资源（安装时缓存）
const CORE_ASSETS = [
  '/',
  '/offline',
  '/static/css/main.css',
  '/static/js/utils.js',
  '/static/js/main.js',
  '/static/manifest.json',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@300;400;500;600;700&display=swap',
  'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js'
];

// 安装事件 - 缓存核心资源
self.addEventListener('install', (event) => {
  console.log('[SW] 安装中...');

  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => {
        console.log('[SW] 缓存核心资源');
        return cache.addAll(CORE_ASSETS);
      })
      .then(() => {
        console.log('[SW] 安装完成');
        return self.skipWaiting(); // 立即激活新的 Service Worker
      })
      .catch((error) => {
        console.error('[SW] 安装失败:', error);
      })
  );
});

// 激活事件 - 清理旧缓存
self.addEventListener('activate', (event) => {
  console.log('[SW] 激活中...');

  event.waitUntil(
    caches.keys()
      .then((cacheNames) => {
        return Promise.all(
          cacheNames
            .filter((cacheName) => {
              // 删除旧版本的缓存
              return cacheName !== CACHE_NAME && cacheName !== RUNTIME_CACHE;
            })
            .map((cacheName) => {
              console.log('[SW] 删除旧缓存:', cacheName);
              return caches.delete(cacheName);
            })
        );
      })
      .then(() => {
        console.log('[SW] 激活完成');
        return self.clients.claim(); // 立即控制所有页面
      })
  );
});

// Fetch 事件 - 网络优先，失败时回退到缓存
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // 跳过非 GET 请求
  if (request.method !== 'GET') {
    return;
  }

  // 跳过 chrome-extension 和其他协议
  if (!url.protocol.startsWith('http')) {
    return;
  }

  // API 请求 - 网络优先，不缓存
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .catch(() => {
          // API 离线时返回友好的错误提示
          return new Response(
            JSON.stringify({
              error: '网络连接失败，请检查您的网络连接',
              offline: true
            }),
            {
              status: 503,
              headers: { 'Content-Type': 'application/json' }
            }
          );
        })
    );
    return;
  }

  // 静态资源 - 缓存优先
  if (
    url.pathname.startsWith('/static/') ||
    url.origin === 'https://fonts.googleapis.com' ||
    url.origin === 'https://fonts.gstatic.com' ||
    url.origin === 'https://cdn.jsdelivr.net'
  ) {
    event.respondWith(
      caches.match(request)
        .then((cached) => {
          if (cached) {
            return cached;
          }

          return fetch(request).then((response) => {
            // 只缓存成功的响应
            if (response.status === 200) {
              const responseClone = response.clone();
              caches.open(RUNTIME_CACHE).then((cache) => {
                cache.put(request, responseClone);
              });
            }
            return response;
          });
        })
        .catch(() => {
          // 离线时返回占位符
          return new Response('资源加载失败', { status: 503 });
        })
    );
    return;
  }

  // HTML 页面 - 网络优先，离线时显示缓存或离线页面
  event.respondWith(
    fetch(request)
      .then((response) => {
        // 缓存 HTML 响应
        if (response.status === 200) {
          const responseClone = response.clone();
          caches.open(RUNTIME_CACHE).then((cache) => {
            cache.put(request, responseClone);
          });
        }
        return response;
      })
      .catch(() => {
        // 网络失败时尝试从缓存中获取
        return caches.match(request)
          .then((cached) => {
            if (cached) {
              return cached;
            }

            // 如果没有缓存，返回离线页面
            return caches.match(OFFLINE_URL).then((offlinePage) => {
              if (offlinePage) {
                return offlinePage;
              }

              // 最后的备用方案：返回内联的离线页面
              return new Response(
                `
                <!DOCTYPE html>
                <html lang="zh-CN">
                <head>
                  <meta charset="UTF-8">
                  <meta name="viewport" content="width=device-width, initial-scale=1.0">
                  <title>离线 - 多银行理财台账</title>
                  <style>
                    body {
                      font-family: 'IBM Plex Sans', sans-serif;
                      background: #0F172A;
                      color: #F8FAFC;
                      display: flex;
                      align-items: center;
                      justify-content: center;
                      min-height: 100vh;
                      margin: 0;
                      padding: 1rem;
                      text-align: center;
                    }
                    .container {
                      max-width: 400px;
                    }
                    h1 {
                      font-size: 1.5rem;
                      margin-bottom: 1rem;
                    }
                    p {
                      color: #94A3B8;
                      line-height: 1.6;
                      margin-bottom: 1.5rem;
                    }
                    button {
                      background: #F59E0B;
                      color: #0F172A;
                      border: none;
                      padding: 12px 24px;
                      border-radius: 8px;
                      font-weight: 600;
                      cursor: pointer;
                      font-size: 1rem;
                    }
                    button:hover {
                      opacity: 0.9;
                    }
                    svg {
                      width: 64px;
                      height: 64px;
                      margin-bottom: 1.5rem;
                      opacity: 0.5;
                    }
                  </style>
                </head>
                <body>
                  <div class="container">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18.364 5.636a9 9 0 010 12.728m0 0l-2.829-2.829m2.829 2.829L21 21M15.536 8.464a5 5 0 010 7.072m0 0l-2.829-2.829m-4.243 2.829a4.978 4.978 0 01-1.414-2.83m-1.414 5.658a9 9 0 01-2.167-9.238m7.824 2.167a1 1 0 111.414 1.414m-1.414-1.414L3 3" />
                    </svg>
                    <h1>您当前处于离线状态</h1>
                    <p>无法连接到服务器。请检查您的网络连接，然后重试。</p>
                    <button onclick="window.location.reload()">重新加载</button>
                  </div>
                </body>
                </html>
                `,
                {
                  status: 503,
                  headers: { 'Content-Type': 'text/html; charset=utf-8' }
                }
              );
            });
          });
      })
  );
});

// 消息事件 - 处理来自客户端的消息
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }

  if (event.data && event.data.type === 'CACHE_URLS') {
    const urlsToCache = event.data.payload;
    caches.open(RUNTIME_CACHE).then((cache) => {
      cache.addAll(urlsToCache);
    });
  }
});

// 后台同步（如果支持）
self.addEventListener('sync', (event) => {
  console.log('[SW] 后台同步:', event.tag);

  if (event.tag === 'sync-data') {
    event.waitUntil(
      // 这里可以添加后台同步逻辑
      Promise.resolve()
    );
  }
});

console.log('[SW] Service Worker 已加载');
