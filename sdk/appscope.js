(function (window, document) {
    'use strict';

    // ── Config ──────────────────────────────────────────────────────────────────
    const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';
    let _apiKey = '';
    let _baseUrl = DEFAULT_BASE_URL;
    let _sessionId = '';
    let _userId = '';
    let _queue = [];
    let _ready = false;
    let _sessionStart = Date.now();
    let _lastActivity = Date.now();
    const SESSION_TIMEOUT = 30 * 60 * 1000; // 30 minutes idle = new session

    // ── Utilities ────────────────────────────────────────────────────────────────
    function generateId() {
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
            const r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
    }

    function hashUserId(id) {
        // Simple deterministic hash — keeps PII off your servers
        let hash = 0;
        const str = String(id);
        for (let i = 0; i < str.length; i++) {
            const char = str.charCodeAt(i);
            hash = ((hash << 5) - hash) + char;
            hash = hash & hash;
        }
        return 'u_' + Math.abs(hash).toString(36);
    }

    function getOrCreateSessionId() {
        const now = Date.now();
        const stored = sessionStorage.getItem('_as_sid');
        const storedTime = parseInt(sessionStorage.getItem('_as_st') || '0');

        // New session if none exists or idle timeout exceeded
        if (!stored || (now - storedTime) > SESSION_TIMEOUT) {
            const sid = generateId();
            sessionStorage.setItem('_as_sid', sid);
            sessionStorage.setItem('_as_st', now.toString());
            return sid;
        }

        sessionStorage.setItem('_as_st', now.toString());
        return stored;
    }

    function getContext() {
        return {
            device_type: /Mobi|Android/i.test(navigator.userAgent) ? 'mobile' : 'desktop',
            browser: getBrowser(),
            country: null, // filled server-side from IP
            app_version: window.AppScope._config.version || '1.0.0',
        };
    }

    function getBrowser() {
        const ua = navigator.userAgent;
        if (ua.includes('Chrome') && !ua.includes('Edg')) return 'chrome';
        if (ua.includes('Firefox')) return 'firefox';
        if (ua.includes('Safari') && !ua.includes('Chrome')) return 'safari';
        if (ua.includes('Edg')) return 'edge';
        return 'other';
    }

    function getCurrentPage() {
        return window.location.pathname;
    }

    // ── Core send ────────────────────────────────────────────────────────────────
    function send(eventName, category, properties = {}) {
        if (!_ready) {
            _queue.push({ eventName, category, properties });
            return;
        }

        // Refresh session activity
        const now = Date.now();
        if ((now - _lastActivity) > SESSION_TIMEOUT) {
            _sessionId = getOrCreateSessionId();
        }
        _lastActivity = now;

        const payload = {
            user_id: _userId,
            session_id: _sessionId,
            event_name: eventName,
            event_category: category,
            timestamp: new Date().toISOString(),
            properties: {
                page: getCurrentPage(),
                element: properties.element || null,
                feature: properties.feature || null,
                extra: properties.extra || {},
                ...properties,
            },
            context: getContext(),
        };

        // Use sendBeacon for reliability (works even on page close)
        const blob = new Blob([JSON.stringify(payload)], { type: 'application/json' });
        const url = `${_baseUrl}/events/track`;

        if (navigator.sendBeacon) {
            // sendBeacon doesn't support custom headers — fall back to fetch
            fetchEvent(url, payload);
        } else {
            fetchEvent(url, payload);
        }
    }

    function fetchEvent(url, payload) {
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'x-api-key': _apiKey,
            },
            body: JSON.stringify(payload),
            keepalive: true, // survives page navigation
        }).catch(function () {
            // Silent fail — never break the client's app
        });
    }

    // ── Flush queue ───────────────────────────────────────────────────────────────
    function flushQueue() {
        while (_queue.length > 0) {
            const item = _queue.shift();
            send(item.eventName, item.category, item.properties);
        }
    }

    // ── Auto tracking ─────────────────────────────────────────────────────────────
    function trackPageView() {
        send('page_viewed', 'navigation', {
            page: getCurrentPage(),
            feature: null,
            extra: {},
        });
    }

    function setupClickTracking() {
        document.addEventListener('click', function (e) {
            const target = e.target.closest('[data-as-track]');
            if (!target) return;

            send('element_clicked', 'engagement', {
                element: target.getAttribute('data-as-track'),
                feature: target.getAttribute('data-as-feature') || null,
                page: getCurrentPage(),
                extra: {},
            });
        }, true);
    }

    function setupOnboardingTracking() {
        // Auto-detect onboarding steps via data-as-step attribute
        const observer = new MutationObserver(function () {
            const steps = document.querySelectorAll('[data-as-step]');
            steps.forEach(function (el) {
                if (el._as_tracked) return;
                el._as_tracked = true;
                const step = parseInt(el.getAttribute('data-as-step'));
                const completed = el.getAttribute('data-as-complete') === 'true';

                send(completed ? 'onboarding_completed' : 'onboarding_step_viewed', 'onboarding', {
                    feature: 'onboarding',
                    page: getCurrentPage(),
                    extra: { step },
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    }

    function setupSpaTracking() {
        // Track navigation in single-page apps (React, Vue, etc.)
        let lastPath = window.location.pathname;

        const pushState = history.pushState;
        history.pushState = function () {
            pushState.apply(history, arguments);
            if (window.location.pathname !== lastPath) {
                lastPath = window.location.pathname;
                trackPageView();
            }
        };

        window.addEventListener('popstate', function () {
            if (window.location.pathname !== lastPath) {
                lastPath = window.location.pathname;
                trackPageView();
            }
        });
    }

    function setupErrorTracking() {
        window.addEventListener('error', function (e) {
            send('js_error', 'error', {
                page: getCurrentPage(),
                feature: null,
                extra: {
                    message: e.message,
                    filename: e.filename,
                    line: e.lineno,
                },
            });
        });
    }

    function setupExitTracking() {
        window.addEventListener('beforeunload', function () {
            send('session_ended', 'navigation', {
                page: getCurrentPage(),
                feature: null,
                extra: {
                    session_duration_ms: Date.now() - _sessionStart,
                },
            });
        });
    }

    // ── Public API ────────────────────────────────────────────────────────────────
    window.AppScope = {
        _config: {},

        init: function (config) {
            if (!config.apiKey) {
                console.warn('[AppScope] apiKey is required.');
                return;
            }

            _apiKey = config.apiKey;
            _baseUrl = config.baseUrl || DEFAULT_BASE_URL;
            _sessionId = getOrCreateSessionId();
            _sessionStart = Date.now();
            _lastActivity = Date.now();
            this._config = config;

            // Set user ID (hashed for privacy)
            if (config.userId) {
                _userId = hashUserId(config.userId);
            } else {
                // Anonymous user — persist across pages
                let anonId = localStorage.getItem('_as_uid');
                if (!anonId) {
                    anonId = generateId();
                    localStorage.setItem('_as_uid', anonId);
                }
                _userId = anonId;
            }

            _ready = true;
            flushQueue();

            // Auto tracking
            trackPageView();
            setupClickTracking();
            setupOnboardingTracking();
            setupSpaTracking();
            setupErrorTracking();
            setupExitTracking();

            if (config.debug) {
                console.log('[AppScope] Initialized.', {
                    userId: _userId,
                    sessionId: _sessionId,
                    baseUrl: _baseUrl,
                });
            }
        },

        // Identify a logged-in user
        identify: function (userId, traits) {
            _userId = hashUserId(userId);
            if (traits) {
                send('user_identified', 'engagement', {
                    feature: null,
                    extra: traits,
                });
            }
        },

        // Track a custom event
        track: function (eventName, properties) {
            const category = properties?.category || 'engagement';
            send(eventName, category, properties || {});
        },

        // Track a feature interaction
        feature: function (featureName, action) {
            send('feature_used', 'engagement', {
                feature: featureName,
                element: action || 'interacted',
                extra: {},
            });
        },

        // Track onboarding step manually
        onboardingStep: function (step, completed) {
            send(completed ? 'onboarding_completed' : 'onboarding_step_viewed', 'onboarding', {
                feature: 'onboarding',
                extra: { step },
            });
        },
    };

}(window, document));