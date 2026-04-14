// web/common/script.js
// WebSocket Manager - Pure WebSocket, NO HTTP fallback
(function(global) {
    'use strict';

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

    // 关键修复：_handleMessage 移除 reqId，避免污染业务数据
    WSClient.prototype._handleMessage = function(data) {
        var parsed = typeof data === 'string' ? JSON.parse(data) : data;
        var reqId = parsed.reqId;
        var key = reqId ? 'res_' + reqId : 'message';
        if (this.callbacks[key]) {
            // 移除 reqId 字段
            if (reqId !== undefined) {
                delete parsed.reqId;
            }
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

    // 关键修复：request 方法解包 data 字段
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
                    // 解包：如果响应只有 data 字段，直接返回 data
                    if (res.data !== undefined && Object.keys(res).length === 1) {
                        resolve(res.data);
                    } else {
                        resolve(res);
                    }
                }
            });

            // 过滤内部字段，只传递业务参数
            var cleanParams = {};
            if (params && typeof params === 'object') {
                for (var key in params) {
                    if (params.hasOwnProperty(key) && key !== 'reqId' && key !== '__method') {
                        cleanParams[key] = params[key];
                    }
                }
            }
            self.send('request', { reqId: reqId, endpoint: endpoint, params: cleanParams });
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
                // 发送 JSON 格式的 ping，避免后端 json.loads 失败
                self.ws.send(JSON.stringify({type: 'ping'}));
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

    // API层：纯WebSocket传输
    var WSAPI = {
        get: function(endpoint, params) {
            return window.klineWS.request(endpoint, params, { method: 'GET', timeout: 30000 });
        },
        post: function(endpoint, body) {
            return window.klineWS.request(endpoint, Object.assign({}, body, { __method: 'POST' }), { timeout: 30000 });
        },
        delete: function(endpoint) {
            return window.klineWS.request(endpoint, { __method: 'DELETE' }, { timeout: 30000 });
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
    
    global.klineWS = new WSClient('/ws/kline');

})(typeof window !== 'undefined' ? window : this);

// Navigation Router - Global scope
let currentViewName = null;

document.addEventListener('DOMContentLoaded', () => {
    switchView('dashboard', document.querySelector('.nav-item'));
});

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