// web/common/script.js
(function(global) {
    'use strict';

    function WSClient(url, options) {
        options = options || {};
        this.url = url;
        this.reconnect = options.reconnect !== false;
        this.ws = null;
        this.callbacks = {};
        this.pending = {};
        this.seq = 0;
        this.autoReconnect = true;
    }

    WSClient.prototype.connect = function() {
        var self = this;
        if (this.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.ws.readyState)) return;

        this.ws = new WebSocket(this.url);

        this.ws.onopen = function() {
            Object.keys(self.pending).forEach(function(id) {
                if (!self.pending[id].sent) {
                    self.ws.send(self.pending[id].payload);
                    self.pending[id].sent = true;
                }
            });
            if (self.callbacks.open) self.callbacks.open();
        };

        this.ws.onmessage = function(event) {
            var msg;
            try { msg = JSON.parse(event.data); } catch (err) { return; }

            if (msg.type === 'response') {
                var task = self.pending[msg.id];
                if (!task) return;
                delete self.pending[msg.id];
                clearTimeout(task.timer);
                if (msg.error) {
                    task.reject(new Error(msg.error.msg || 'WS request failed'));
                } else {
                    task.resolve(msg.result);
                }
                return;
            }

            if (self.callbacks.message) self.callbacks.message(msg);
        };

        this.ws.onclose = function() {
            Object.keys(self.pending).forEach(function(id) {
                if (self.pending[id]) self.pending[id].sent = false;
            });
            if (self.autoReconnect && self.reconnect) setTimeout(function() { self.connect(); }, 2000);
            if (self.callbacks.close) self.callbacks.close();
        };

        this.ws.onerror = function(err) {
            if (self.callbacks.error) self.callbacks.error(err);
        };
    };

    WSClient.prototype.request = function(method, params) {
        var self = this;
        var id = ++this.seq;
        var payload = JSON.stringify({ id: id, type: 'request', method: method, params: params || {} });

        return new Promise(function(resolve, reject) {
            self.pending[id] = {
                payload: payload,
                sent: false,
                resolve: resolve,
                reject: reject,
                timer: setTimeout(function() {
                    delete self.pending[id];
                    reject(new Error('Request timeout: ' + method));
                }, 30000)
            };
            if (!self.ws || self.ws.readyState !== WebSocket.OPEN) return self.connect();
            self.ws.send(payload);
            self.pending[id].sent = true;
        });
    };

    WSClient.prototype.close = function() {
        this.autoReconnect = false;
        if (this.ws) this.ws.close();
    };

    function cacheKey(method, params) {
        return method + ':' + JSON.stringify(Object.keys(params || {}).sort().reduce(function(data, key) {
            data[key] = params[key];
            return data;
        }, {}));
    }

    var WSAPI = {
        cache: {},
        cacheKeys: [],
        call: function(method, params) {
            var key = method === 'kline.data' ? cacheKey(method, params || {}) : null;
            if (key && this.cache[key]) return Promise.resolve(this.cache[key]);
            return window.wsClient.request(method, params).then(function(data) {
                data = data && typeof data === 'object' && data.data !== undefined && Object.keys(data).length === 1 ? data.data : data;
                if (key) {
                    WSAPI.cache[key] = data;
                    WSAPI.cacheKeys.push(key);
                    if (WSAPI.cacheKeys.length > 20) delete WSAPI.cache[WSAPI.cacheKeys.shift()];
                }
                return data;
            });
        }
    };

    var State = {
        data: {},
        set: function(key, val) { this.data[key] = val; },
        get: function(key) { return this.data[key]; }
    };

    global.WSClient = WSClient;
    global.WSAPI = WSAPI;
    global.State = State;
    global.wsClient = new WSClient('/ws');
})(typeof window !== 'undefined' ? window : this);

let currentViewName = null;

document.addEventListener('DOMContentLoaded', function() {
    switchView('dashboard', document.querySelector('.nav-item'));
});

async function switchView(viewName, navEl) {
    if (currentViewName) {
        const destroyFunc = window['destroy_' + currentViewName];
        if (typeof destroyFunc === 'function') destroyFunc();
    }

    document.querySelectorAll('.nav-item').forEach(function(el) { el.classList.remove('active'); });
    if (navEl) navEl.classList.add('active');

    document.getElementById('page-title').innerText = viewName;

    const container = document.getElementById('view-container');
    container.innerHTML = '<div class="panel">Loading...</div>';

    try {
        const htmlPath = '/' + viewName + '/index.html';
        const res = await fetch(htmlPath);
        if (res.ok) {
            const html = await res.text();
            container.innerHTML = html;
            currentViewName = viewName;
            loadPageScript(viewName);
        } else {
            container.innerHTML = '<div class="panel" style="color:#b42318;">页面未找到: ' + htmlPath + '</div>';
        }
    } catch (e) {
        container.innerHTML = '<div class="panel" style="color:#b42318;">加载失败: ' + e.message + '</div>';
    }
}

function loadPageScript(viewName) {
    const existingScript = document.getElementById('script-' + viewName);
    if (existingScript) existingScript.remove();

    const script = document.createElement('script');
    script.src = '/' + viewName + '/script.js';
    script.id = 'script-' + viewName;
    script.onload = function() {
        const initFunc = window['init_' + viewName];
        if (typeof initFunc === 'function') initFunc();
    };
    document.body.appendChild(script);
}
