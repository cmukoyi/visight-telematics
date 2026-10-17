class PinplotQrGenerator extends HTMLElement {
    async connectedCallback() {
        if (this.shadowRoot) return;
        const shadow = this.attachShadow({ mode: 'open' });
        shadow.innerHTML = '<p role="status">Loading...</p>';
        try {
            const response = await fetch('/customer/qr-generator.html', { cache: 'no-store' });
            if (!response.ok) throw new Error(`QR generator: HTTP ${response.status}`);
            const source = new DOMParser().parseFromString(await response.text(), 'text/html');
            const scripts = [...source.querySelectorAll('script')].map(script => script.textContent);
            source.querySelectorAll('script').forEach(script => script.remove());
            const style = document.createElement('style');
            style.textContent = [...source.querySelectorAll('style')].map(sheet => sheet.textContent
                .replace(/:root/g, '#qr-app').replace(/\bhtml\b|\bbody\b/g, '#qr-app')).join('\n') + `
                :host { display:block; min-width:0; }
                #qr-app { min-width:0; height:auto; overflow:visible; padding:12px 0; }
                .app { grid-template-columns:minmax(0,1fr) minmax(0,1fr) 260px; }
                @media(max-width:1100px) {
                    .app { grid-template-columns:minmax(0,1fr) minmax(0,1fr); }
                    .app > :last-child { grid-column:1 / -1; }
                }
                @media(max-width:640px) {
                    .app { grid-template-columns:minmax(0,1fr); }
                    .intro-steps { flex-wrap:wrap; }
                    .two-col { grid-template-columns:minmax(0,1fr); }
                }
            `;
            const root = document.createElement('div');
            root.id = 'qr-app';
            root.append(...source.body.childNodes);
            shadow.replaceChildren(style, root);
            const ready = [];
            const scopedDocument = new Proxy(document, {
                get(target, property) {
                    if (property === 'body' || property === 'documentElement') return root;
                    if (property === 'getElementById') return id => shadow.getElementById(id);
                    if (property === 'querySelector' || property === 'querySelectorAll') return shadow[property].bind(shadow);
                    if (property === 'addEventListener') return (type, listener, options) => {
                        if (type === 'DOMContentLoaded') ready.push(listener);
                        else root.addEventListener(type, listener, options);
                    };
                    const value = Reflect.get(target, property, target);
                    return typeof value === 'function' ? value.bind(target) : value;
                }
            });
            const element = this;
            const scopedWindow = new Proxy(window, {
                get(target, property) {
                    if (property === 'parent') return window;
                    if (property === 'location') return {
                        search: `?lang=${encodeURIComponent(element.language())}`,
                        hostname: location.hostname, origin: location.origin,
                        replace: () => {}
                    };
                    if (property === 'addEventListener') return (type, listener, options) => {
                        if (type === 'load') ready.push(listener);
                        else window.addEventListener(type, listener, options);
                    };
                    const value = Reflect.get(target, property, target);
                    return typeof value === 'function' ? value.bind(target) : value;
                }
            });
            // Keep legacy handlers and generator globals out of the portal namespace.
            const runtime = new Function('document', 'window', scripts.join('\n') + `
                return {
                    handle: function(code, event) { return eval(code); },
                    language: function(lang) { qrLanguage = lang; translateQrGenerator(); },
                    render: function() { generate(); }
                };
            `)(scopedDocument, scopedWindow);
            const bindHandlers = () => {
                root.querySelectorAll('*').forEach(control => {
                    [...control.attributes].filter(attribute => /^on[a-z]+$/.test(attribute.name)).forEach(attribute => {
                        const code = attribute.value;
                        const type = attribute.name.slice(2);
                        control.removeAttribute(attribute.name);
                        control.addEventListener(type, function(event) {
                            if (runtime.handle.call(this, code, event) === false) event.preventDefault();
                        });
                    });
                });
            };
            bindHandlers();
            new MutationObserver(bindHandlers).observe(root, { childList: true, subtree: true });
            const translate = () => runtime.language(this.language());
            const theme = () => {
                root.classList.toggle('dark', document.documentElement.getAttribute('data-theme') === 'dark');
                const branding = JSON.parse(localStorage.getItem('pinplot_branding') || 'null');
                ['--primary', '--primary-mid', '--primary-border', '--primary-light', '--accent'].forEach(property => root.style.removeProperty(property));
                if (branding?.theme_primary) {
                    ['--primary', '--primary-mid', '--primary-border'].forEach(property => root.style.setProperty(property, branding.theme_primary));
                    root.style.setProperty('--primary-light', branding.theme_primary + '26');
                }
                if (branding?.theme_accent) root.style.setProperty('--accent', branding.theme_accent);
                runtime.render();
            };
            ready.forEach(listener => listener());
            translate();
            theme();
            document.addEventListener('portal-language-changed', translate);
            document.addEventListener('portal-branding-changed', theme);
            new MutationObserver(theme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
            this.dataset.ready = 'true';
        } catch (error) {
            console.error(error);
            shadow.innerHTML = '<p role="alert">QR generator unavailable. <a href="/customer/qr-generator.html">Open generator</a></p>';
        }
    }

    language() {
        return typeof TranslationService !== 'undefined' ? TranslationService.getInstance().getCurrentLanguage() : 'en';
    }
}

customElements.define('pinplot-qr-generator', PinplotQrGenerator);