// web/common/script.js
// WebSocket Manager with optional gzip compression - Global scope version
let currentViewName = null;

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    switchView('dashboard', document.querySelector('.nav-item'));
});

// Navigation Router
async function switchView(viewName, navEl) {
    if (currentViewName) {
        const destroyFunc = window[`destroy_${currentViewName}`];
        if (typeof destroyFunc === 'function') {
            destroyFunc();
        }
    }

    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    if (navEl) navEl.classList.add('active');

    const titles = {
        'dashboard': '首页状态',
        'tasks': '任务执行',
        'logs': '日志查看',
        'kline': 'K线查看'
    };
    document.getElementById('page-title').innerText = titles[viewName] || viewName;

    const container = document.getElementById('view-container');
    container.innerHTML = '<div style="padding:20px; color:#999;">Loading...</div>';

    try {
        const htmlPath = `/${viewName}/index.html`;
        const res = await fetch(htmlPath);
        if (res.ok) {
            const html = await res.text();
            container.innerHTML = html;
            currentViewName = viewName;
            loadPageScript(viewName);
        } else {
            container.innerHTML = `<div style="color:red;">页面未找到: ${htmlPath}</div>`;
        }
    } catch (e) {
        console.error(e);
        container.innerHTML = `<div style="color:red;">加载失败: ${e.message}</div>`;
    }
}

function loadPageScript(viewName) {
    const existingScript = document.getElementById(`script-${viewName}`);
    if (existingScript) existingScript.remove();

    const script = document.createElement('script');
    script.src = `/${viewName}/script.js`;
    script.id = `script-${viewName}`;
    script.onload = () => {
        const initFunc = window[`init_${viewName}`];
        if (typeof initFunc === 'function') {
            initFunc();
        }
    };
    document.body.appendChild(script);
}
(function(global) {
    'use strict';

    // WebSocket 客户端类
    function WSClient(url, options) {
        options = options || {};
        this.url = url;
        this.compress = options.compress !== false;
        this.reconnect = options.reconnect !== false;
        this.heartbeat = options.heartbeat || 30000;
        this.ws = null;
        this.callbacks = {};
        this.buffer = [];
        this.heartTimer = null;
        this.autoReconnect = true;
    }

    WSClient.prototype.connect = function() {
        var self = this;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
        
        this.ws = new WebSocket(this.url);
        this.ws.binaryType = 'arraybuffer';

        this.ws.onopen = function() {
            self._startHeartbeat();
            while (self.buffer.length) {
                self._sendRaw(self.buffer.shift());
            }
            if (self.callbacks.open) self.callbacks.open();
        };

        this.ws.onmessage = function(event) {
            var data = event.data;
            // 自动解压 gzip（后端压缩时）
            if (self.compress && event.data instanceof ArrayBuffer) {
                try {
                    var ds = new DecompressionStream('gzip');
                    var stream = new Response(
                        new Blob([event.data]).stream().pipeThrough(ds)
                    );
                    stream.text().then(function(text) {
                        self._handleMessage(text);
                    }).catch(function() {
                        self._handleMessage(event.data);
                    });
                    return;
                } catch (e) {
                    console.warn('Decompress failed, fallback to raw:', e);
                }
            }
            self._handleMessage(data);
        };

        this.ws.onclose = function() {
            self._stopHeartbeat();
            if (self.autoReconnect && self.reconnect) {
                setTimeout(function() { self.connect(); }, 3000);
            }
            if (self.callbacks.close) self.callbacks.close();
        };

        this.ws.onerror = function(err) {
            console.error('WS error:', err);
            if (self.callbacks.error) self.callbacks.error(err);
        };
    };

    WSClient.prototype._handleMessage = function(data) {
        var parsed = typeof data === 'string' ? JSON.parse(data) : data;
        var key = parsed.reqId ? 'res_' + parsed.reqId : 'message';
        if (this.callbacks[key]) {
            this.callbacks[key](parsed);
        }
    };

    WSClient.prototype.on = function(event, fn) {
        this.callbacks[event] = fn;
        return this;
    };

    WSClient.prototype.off = function(event) {
        delete this.callbacks[event];
        return this;
    };

    WSClient.prototype.send = function(type, payload) {
        payload = payload || {};
        var msg = JSON.stringify(Object.assign({ type: type }, payload));
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this._sendRaw(msg);
        } else {
            this.buffer.push(msg);
        }
    };

    WSClient.prototype._sendRaw = function(data) {
        this.ws.send(data);
    };

    WSClient.prototype.request = function(endpoint, params, options) {
        var self = this;
        options = options || {};
        var timeout = options.timeout || 30000;
        
        return new Promise(function(resolve, reject) {
            var reqId = Date.now() + '_' + Math.random().toString(36).slice(2);
            var to = setTimeout(function() {
                self.off('res_' + reqId);
                reject(new Error('Request timeout: ' + endpoint));
            }, timeout);

            self.on('res_' + reqId, function(res) {
                clearTimeout(to);
                self.off('res_' + reqId);
                if (res.error) {
                    reject(new Error(res.error));
                } else {
                    resolve(res);
                }
            });

            self.send('request', { reqId: reqId, endpoint: endpoint, params: params });
            if (!self.ws || self.ws.readyState !== WebSocket.OPEN) {
                self.connect();
            }
        });
    };

    WSClient.prototype._startHeartbeat = function() {
        var self = this;
        this._stopHeartbeat();
        this.heartTimer = setInterval(function() {
            if (self.ws && self.ws.readyState === WebSocket.OPEN) {
                self.ws.send('ping');
            }
        }, this.heartbeat);
    };

    WSClient.prototype._stopHeartbeat = function() {
        if (this.heartTimer) {
            clearInterval(this.heartTimer);
            this.heartTimer = null;
        }
    };

    WSClient.prototype.close = function() {
        this.autoReconnect = false;
        if (this.ws) this.ws.close();
    };

    // API 兼容层：优先 WS，失败 fallback 到 fetch
    var WSAPI = {
        get: function(endpoint, params, useWS) {
            if (useWS === false) {
                var qs = new URLSearchParams(params || {}).toString();
                return fetch('/api' + endpoint + (qs ? '?' + qs : '')).then(function(r) { return r.json(); });
            }
            var qs = new URLSearchParams(params || {}).toString();
            var url = endpoint + (qs ? '?' + qs : '');
            return (window.klineWS ? window.klineWS.request(url, params, { method: 'GET', timeout: 30000 }) : Promise.reject())
                .catch(function() {
                    return fetch('/api' + endpoint + (qs ? '?' + qs : '')).then(function(r) { return r.json(); });
                });
        },
        post: function(endpoint, body, useWS) {
            if (useWS === false) {
                return fetch('/api' + endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body || {})
                }).then(function(r) { return r.json(); });
            }
            return (window.klineWS ? window.klineWS.request(endpoint, Object.assign({}, body, { __method: 'POST' }), { timeout: 30000 }) : Promise.reject())
                .catch(function() {
                    return fetch('/api' + endpoint, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(body || {})
                    }).then(function(r) { return r.json(); });
                });
        },
        delete: function(endpoint, useWS) {
            if (useWS === false) {
                return fetch('/api' + endpoint, { method: 'DELETE' }).then(function(r) { return r.json(); });
            }
            return (window.klineWS ? window.klineWS.request(endpoint, { __method: 'DELETE' }, { timeout: 30000 }) : Promise.reject())
                .catch(function() {
                    return fetch('/api' + endpoint, { method: 'DELETE' }).then(function(r) { return r.json(); });
                });
        }
    };

    // 状态管理
    var State = {
        data: {},
        set: function(key, val) { this.data[key] = val; },
        get: function(key) { return this.data[key]; }
    };

    // 全局挂载
    global.WSClient = WSClient;
    global.WSAPI = WSAPI;
    global.State = State;
    
    // 创建单例（按需连接）
    global.klineWS = new WSClient('/ws/kline');

})(typeof window !== 'undefined' ? window : this);