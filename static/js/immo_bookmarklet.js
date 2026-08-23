/**
 * Immo-Boussole — Bookmarklet d'importation multi-portails
 * Permet l'extraction directe des annonces depuis le navigateur de l'utilisateur
 * (contournement DataDome / Cloudflare) et leur synchronisation avec Immo-Boussole.
 */
(function() {
    'use strict';

    // 1. Initialisation de la configuration
    const config = window.__IMMO_CONFIG__ || {};
    let serverUrl = config.server || localStorage.getItem('immo_server_url') || window.location.origin;
    let apiKey = config.apiKey || localStorage.getItem('immo_api_key') || '';

    // Nettoyer l'URL du serveur (supprimer le slash final)
    serverUrl = serverUrl.replace(/\/+$/, '');

    // Si pas d'API Key ou serveur spécifié, demander à l'utilisateur
    if (!apiKey) {
        apiKey = prompt("Immo-Boussole — Veuillez entrer votre clé API (générée dans votre profil Immo-Boussole) :", "");
        if (!apiKey) {
            alert("Opération annulée : Clé API requise pour synchroniser avec Immo-Boussole.");
            return;
        }
        localStorage.setItem('immo_api_key', apiKey);
    }
    if (!serverUrl || serverUrl === window.location.origin) {
        const customUrl = prompt("Immo-Boussole — URL de votre instance Immo-Boussole :", serverUrl);
        if (customUrl) {
            serverUrl = customUrl.replace(/\/+$/, '');
            localStorage.setItem('immo_server_url', serverUrl);
        }
    }

    // 2. Parsers par portail immobilier
    class LeboncoinParser {
        static canHandle(url) {
            return url.includes('leboncoin.fr');
        }

        static parse() {
            const listings = [];
            const isAdPage = /\/ad\/|\/ventes_immobilieres\/\d+/.test(window.location.pathname);

            // Essai via le payload __NEXT_DATA__
            const nextDataScript = document.getElementById('__NEXT_DATA__');
            if (nextDataScript) {
                try {
                    const data = JSON.parse(nextDataScript.textContent);
                    const pageProps = data?.props?.pageProps || {};

                    // Cas A : Page de détail d'annonce
                    const ad = pageProps.ad || pageProps.initialData?.ad;
                    if (ad) {
                        listings.push(this._formatAd(ad));
                        return { type: 'single', listings };
                    }

                    // Cas B : Page de recherche / liste
                    const searchAds = pageProps.searchData?.ads || pageProps.initialData?.searchData?.ads || [];
                    if (searchAds.length > 0) {
                        for (const item of searchAds) {
                            listings.push(this._formatAd(item));
                        }
                        return { type: 'search', listings };
                    }
                } catch (e) {
                    console.warn('[Immo-Boussole] Erreur lecture __NEXT_DATA__:', e);
                }
            }

            // Fallback DOM pour page de détail
            if (isAdPage) {
                const titleElem = document.querySelector('h1[data-qa-id="adview_title"]') || document.querySelector('h1');
                const priceElem = document.querySelector('div[data-qa-id="adview_price"]') || document.querySelector('[data-test-id="price"]');
                const descElem = document.querySelector('div[data-qa-id="adview_description_container"]') || document.querySelector('[data-qa-id="adview_description"]');
                
                const title = titleElem ? titleElem.textContent.trim() : document.title.replace(' - Leboncoin', '').trim();
                const priceText = priceElem ? priceElem.textContent.replace(/[^\d]/g, '') : '0';
                const price = priceText ? parseFloat(priceText) : null;
                const desc = descElem ? descElem.textContent.trim() : '';

                // Photos
                const photoUrls = [];
                document.querySelectorAll('img[src*="img.leboncoin.fr"]').forEach(img => {
                    const src = img.src.split('?')[0];
                    if (src && !photoUrls.includes(src)) photoUrls.push(src);
                });

                listings.push({
                    url: window.location.href.split('?')[0],
                    title: title,
                    price: price,
                    description: desc,
                    photos: photoUrls,
                    source: 'leboncoin'
                });
                return { type: 'single', listings };
            }

            // Fallback DOM pour page de recherche
            const adContainers = document.querySelectorAll('a[data-qa-id="aditem_container"], article[data-qa-id="aditem_container"] a');
            adContainers.forEach(container => {
                const href = container.getAttribute('href');
                if (!href) return;
                const url = href.startsWith('http') ? href.split('?')[0] : `https://www.leboncoin.fr${href.split('?')[0]}`;
                const title = container.querySelector('[data-qa-id="aditem_title"]')?.textContent?.trim() || 'Annonce Leboncoin';
                const priceText = container.querySelector('[data-test-id="price"]')?.textContent?.replace(/[^\d]/g, '');
                const price = priceText ? parseFloat(priceText) : null;
                
                const img = container.querySelector('img[src*="img.leboncoin.fr"]');
                const photos = img ? [img.src.split('?')[0]] : [];

                listings.push({
                    url: url,
                    title: title,
                    price: price,
                    photos: photos,
                    source: 'leboncoin'
                });
            });

            return { type: listings.length === 1 ? 'single' : 'search', listings };
        }

        static _formatAd(ad) {
            const loc = ad.location || {};
            const city = loc.city || '';
            const zipcode = loc.zipcode || '';
            const locationStr = [city, zipcode].filter(Boolean).join(' ');

            const priceVal = Array.isArray(ad.price) ? ad.price[0] : (ad.price || 0);
            
            // Attributs
            let area = null;
            let rooms = null;
            let bedrooms = null;
            let propertyType = null;
            let dpe = null;
            let ges = null;

            if (Array.isArray(ad.attributes)) {
                for (const attr of ad.attributes) {
                    if (attr.key === 'square') area = parseFloat(attr.value);
                    else if (attr.key === 'rooms') rooms = parseInt(attr.value, 10);
                    else if (attr.key === 'bedrooms') bedrooms = parseInt(attr.value, 10);
                    else if (attr.key === 'real_estate_type') propertyType = attr.value_label || attr.value;
                    else if (attr.key === 'energy_rate') dpe = attr.value;
                    else if (attr.key === 'ges') ges = attr.value;
                }
            }

            // Photos
            const photoUrls = [];
            const imgs = ad.images || {};
            const urls = imgs.urls_large || imgs.urls || [];
            if (Array.isArray(urls)) {
                urls.forEach(u => { if (typeof u === 'string' && !photoUrls.includes(u)) photoUrls.push(u); });
            } else if (typeof urls === 'string') {
                photoUrls.push(urls);
            }

            const adUrl = ad.url ? (ad.url.startsWith('http') ? ad.url : `https://www.leboncoin.fr${ad.url}`) : window.location.href;

            return {
                url: adUrl.split('?')[0],
                external_id: ad.list_id ? `lbc_${ad.list_id}` : undefined,
                title: ad.subject || 'Annonce Leboncoin',
                price: typeof priceVal === 'number' ? priceVal : parseFloat(priceVal) || null,
                area: area,
                rooms: rooms,
                bedrooms: bedrooms,
                city: city,
                postal_code: zipcode,
                location: locationStr || city || 'France',
                description: ad.body || '',
                property_type: propertyType,
                dpe_rating: dpe,
                ges_rating: ges,
                photos: photoUrls,
                source: 'leboncoin'
            };
        }
    }

    class SelogerParser {
        static canHandle(url) {
            return url.includes('seloger.com');
        }

        static parse() {
            const listings = [];
            const isAdPage = /\/annonces?\//.test(window.location.pathname);

            if (isAdPage) {
                const title = document.querySelector('h1')?.textContent?.trim() || document.title;
                const priceText = document.querySelector('[data-test="price"], .price, [class*="Price"]')?.textContent?.replace(/[^\d]/g, '');
                const price = priceText ? parseFloat(priceText) : null;
                const photos = [];
                document.querySelectorAll('img[src*="seloger"]').forEach(img => {
                    if (img.src && !photos.includes(img.src)) photos.push(img.src);
                });

                listings.push({
                    url: window.location.href.split('?')[0],
                    title: title,
                    price: price,
                    photos: photos,
                    source: 'seloger'
                });
                return { type: 'single', listings };
            }

            document.querySelectorAll('a[href*="/annonces/"]').forEach(a => {
                const href = a.getAttribute('href');
                if (href && !listings.some(l => l.url === href)) {
                    const fullUrl = href.startsWith('http') ? href : `https://www.seloger.com${href}`;
                    listings.push({
                        url: fullUrl.split('?')[0],
                        title: a.textContent?.trim() || 'Annonce SeLoger',
                        photos: [],
                        source: 'seloger'
                    });
                }
            });

            return { type: listings.length === 1 ? 'single' : 'search', listings };
        }
    }

    // 3. Détection du parser adapté
    let parser = null;
    const currentUrl = window.location.href;
    if (LeboncoinParser.canHandle(currentUrl)) {
        parser = LeboncoinParser;
    } else if (SelogerParser.canHandle(currentUrl)) {
        parser = SelogerParser;
    } else {
        // Parser générique de fallback
        parser = {
            parse: () => ({
                type: 'single',
                listings: [{
                    url: window.location.href.split('?')[0],
                    title: document.title,
                    source: 'manuel'
                }]
            })
        };
    }

    // 4. Extraction des données
    const parseResult = parser.parse();
    const rawListings = parseResult.listings || [];

    if (rawListings.length === 0) {
        alert("Immo-Boussole : Aucune annonce immobilière détectée sur cette page.");
        return;
    }

    // 5. Interface Utilisateur Flottante (Modal Glassmorphism)
    const existingModal = document.getElementById('immo-boussole-overlay');
    if (existingModal) existingModal.remove();

    const overlay = document.createElement('div');
    overlay.id = 'immo-boussole-overlay';
    overlay.style.cssText = `
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
        background: rgba(11, 15, 26, 0.75); backdrop-filter: blur(8px);
        z-index: 9999999; display: flex; align-items: center; justify-content: center;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        color: #eef2ff; box-sizing: border-box;
    `;

    const modal = document.createElement('div');
    modal.style.cssText = `
        background: #131929; border: 1px solid rgba(255, 255, 255, 0.12);
        border-radius: 16px; width: 92%; max-width: 680px; max-height: 88vh;
        display: flex; flex-direction: column; box-shadow: 0 20px 50px rgba(0,0,0,0.6);
        overflow: hidden; animation: immoFadeIn 0.25s ease-out;
    `;

    modal.innerHTML = `
        <style>
            @keyframes immoFadeIn { from { opacity: 0; transform: scale(0.96); } to { opacity: 1; transform: scale(1); } }
            .immo-btn {
                background: #4f8ef7; color: #fff; border: none; border-radius: 10px;
                padding: 10px 18px; font-weight: 600; font-size: 0.9rem; cursor: pointer;
                display: inline-flex; align-items: center; justify-content: center; gap: 8px;
                transition: all 0.2s ease;
            }
            .immo-btn:hover { background: #3b7ad9; transform: translateY(-1px); }
            .immo-btn:disabled { background: #334155; color: #94a3b8; cursor: not-allowed; transform: none; }
            .immo-btn.secondary { background: #1e293b; color: #cbd5e1; border: 1px solid rgba(255,255,255,0.1); }
            .immo-btn.secondary:hover { background: #334155; color: #fff; }
            .immo-item {
                display: flex; align-items: center; gap: 12px; padding: 10px 14px;
                background: #1a2236; border: 1px solid rgba(255,255,255,0.06);
                border-radius: 10px; margin-bottom: 8px; transition: all 0.15s ease;
            }
            .immo-item:hover { border-color: rgba(79, 142, 247, 0.4); background: #202b44; }
            .immo-badge {
                font-size: 0.7rem; font-weight: 700; padding: 2px 8px; border-radius: 6px;
                text-transform: uppercase; letter-spacing: 0.05em;
            }
            .immo-badge.exists { background: rgba(248, 168, 75, 0.2); color: #f8a84b; border: 1px solid rgba(248, 168, 75, 0.4); }
            .immo-badge.new { background: rgba(16, 217, 164, 0.2); color: #10d9a4; border: 1px solid rgba(16, 217, 164, 0.4); }
        </style>
        
        <!-- Header -->
        <div style="padding: 16px 20px; border-bottom: 1px solid rgba(255,255,255,0.08); display: flex; align-items: center; justify-content: space-between;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <div style="font-size: 1.4rem;">🧭</div>
                <div>
                    <div style="font-weight: 800; font-size: 1.1rem; color: #eef2ff;">Immo-Boussole Import</div>
                    <div style="font-size: 0.75rem; color: #8b9cc8;">${parseResult.type === 'single' ? 'Fiche d\'annonce détectée' : `${rawListings.length} annonces détectées`} sur ${LeboncoinParser.canHandle(currentUrl) ? 'Leboncoin' : 'Portail Immobilier'}</div>
                </div>
            </div>
            <button id="immo-close-btn" style="background: none; border: none; color: #8b9cc8; font-size: 1.3rem; cursor: pointer; padding: 4px 8px; border-radius: 6px;">✕</button>
        </div>

        <!-- Controls Bar -->
        <div style="padding: 12px 20px; background: #0e1422; border-bottom: 1px solid rgba(255,255,255,0.05); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
            <label style="display: flex; align-items: center; gap: 8px; font-size: 0.85rem; font-weight: 600; cursor: pointer;">
                <input type="checkbox" id="immo-select-all" checked style="width: 16px; height: 16px; cursor: pointer; accent-color: #4f8ef7;">
                <span>Tout sélectionner (<span id="immo-selected-count">${rawListings.length}</span>/${rawListings.length})</span>
            </label>
            <div id="immo-checking-status" style="font-size: 0.75rem; color: #8b9cc8;">Vérification des doublons...</div>
        </div>

        <!-- Listings List -->
        <div id="immo-list-container" style="padding: 16px 20px; overflow-y: auto; flex: 1; max-height: 48vh;">
            <!-- Injected list items -->
        </div>

        <!-- Footer Actions -->
        <div style="padding: 16px 20px; border-top: 1px solid rgba(255,255,255,0.08); background: #131929; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;">
            <div id="immo-result-msg" style="font-size: 0.85rem; color: #8b9cc8; flex: 1;"></div>
            <div style="display: flex; gap: 10px;">
                <button id="immo-cancel-btn" class="immo-btn secondary">Fermer</button>
                <button id="immo-submit-btn" class="immo-btn">
                    <span>🚀 Importer (${rawListings.length}) vers Immo-Boussole</span>
                </button>
            </div>
        </div>
    `;

    overlay.appendChild(modal);
    document.body.appendChild(overlay);

    // 6. Gestion des événements UI
    const closeBtn = document.getElementById('immo-close-btn');
    const cancelBtn = document.getElementById('immo-cancel-btn');
    const selectAllCb = document.getElementById('immo-select-all');
    const selectedCountSpan = document.getElementById('immo-selected-count');
    const listContainer = document.getElementById('immo-list-container');
    const submitBtn = document.getElementById('immo-submit-btn');
    const resultMsg = document.getElementById('immo-result-msg');
    const checkingStatus = document.getElementById('immo-checking-status');

    const closeModal = () => overlay.remove();
    closeBtn.onclick = closeModal;
    cancelBtn.onclick = closeModal;
    overlay.onclick = (e) => { if (e.target === overlay) closeModal(); };

    // Rendu initial de la liste
    function renderList(existingUrls = []) {
        listContainer.innerHTML = '';
        rawListings.forEach((item, idx) => {
            const isExisting = existingUrls.includes(item.url);
            const thumb = (item.photos && item.photos.length > 0) ? item.photos[0] : null;
            
            const row = document.createElement('div');
            row.className = 'immo-item';
            row.innerHTML = `
                <input type="checkbox" class="immo-item-cb" data-idx="${idx}" checked style="width: 18px; height: 18px; cursor: pointer; accent-color: #4f8ef7;">
                ${thumb ? `<img src="${thumb}" style="width: 54px; height: 42px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.1);">` : `<div style="width: 54px; height: 42px; background: #0b0f1a; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">🏠</div>`}
                <div style="flex: 1; min-width: 0;">
                    <div style="font-weight: 700; font-size: 0.88rem; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                        ${item.title || 'Annonce sans titre'}
                    </div>
                    <div style="font-size: 0.78rem; color: #8b9cc8; margin-top: 2px; display: flex; gap: 10px; align-items: center; flex-wrap: wrap;">
                        ${item.price ? `<span style="color: #10d9a4; font-weight: 700;">${item.price.toLocaleString('fr-FR')} €</span>` : ''}
                        ${item.area ? `<span>${item.area} m²</span>` : ''}
                        ${item.rooms ? `<span>${item.rooms} p.</span>` : ''}
                        ${item.location ? `<span>📍 ${item.location}</span>` : ''}
                    </div>
                </div>
                ${isExisting ? `<span class="immo-badge exists" title="Cette annonce est déjà enregistrée dans votre base">Déjà présent</span>` : `<span class="immo-badge new">Nouveau</span>`}
            `;
            listContainer.appendChild(row);
        });

        updateCounts();
    }

    function updateCounts() {
        const checkboxes = document.querySelectorAll('.immo-item-cb');
        const checked = Array.from(checkboxes).filter(cb => cb.checked);
        selectedCountSpan.textContent = checked.length;
        selectAllCb.checked = checked.length === checkboxes.length && checkboxes.length > 0;
        submitBtn.querySelector('span').textContent = `🚀 Importer (${checked.length}) vers Immo-Boussole`;
        submitBtn.disabled = checked.length === 0;
    }

    selectAllCb.onchange = () => {
        document.querySelectorAll('.immo-item-cb').forEach(cb => cb.checked = selectAllCb.checked);
        updateCounts();
    };

    listContainer.addEventListener('change', (e) => {
        if (e.target.classList.contains('immo-item-cb')) {
            updateCounts();
        }
    });

    renderList();

    // 7. Vérification des doublons en arrière-plan
    async function checkDuplicates() {
        try {
            const urls = rawListings.map(l => l.url);
            const res = await fetch(`${serverUrl}/api/v1/actions/check-external-listings`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${apiKey}`
                },
                body: JSON.stringify({ urls: urls })
            });

            if (res.ok) {
                const data = await res.json();
                const existing = data.existing_urls || [];
                checkingStatus.textContent = existing.length > 0 ? `${existing.length} annonce(s) déjà dans la base` : `Toutes les annonces sont nouvelles`;
                renderList(existing);
            } else {
                checkingStatus.textContent = 'Non connecté';
            }
        } catch (e) {
            console.warn('[Immo-Boussole] Erreur vérification doublons:', e);
            checkingStatus.textContent = '';
        }
    }

    checkDuplicates();

    // 8. Envoi vers l'API Immo-Boussole
    submitBtn.onclick = async () => {
        const selectedIndices = Array.from(document.querySelectorAll('.immo-item-cb:checked')).map(cb => parseInt(cb.getAttribute('data-idx'), 10));
        const selectedListings = selectedIndices.map(idx => rawListings[idx]).filter(Boolean);

        if (selectedListings.length === 0) return;

        submitBtn.disabled = true;
        submitBtn.querySelector('span').textContent = `⏳ Envoi de ${selectedListings.length} annonce(s)...`;
        resultMsg.textContent = "Traitement et synchronisation en cours...";

        try {
            const res = await fetch(`${serverUrl}/api/v1/actions/submit-external-listings-batch`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${apiKey}`
                },
                body: JSON.stringify({
                    listings: selectedListings
                })
            });

            if (!res.ok) {
                const err = await res.json().catch(() => ({ detail: res.statusText }));
                throw new Error(err.detail || `Erreur serveur (${res.status})`);
            }

            const data = await res.json();
            
            // Succès
            submitBtn.style.background = '#10d9a4';
            submitBtn.querySelector('span').textContent = '✅ Importation réussie !';
            
            resultMsg.innerHTML = `
                <span style="color: #10d9a4; font-weight: 700;">${data.created_count} créée(s)</span>, 
                <span style="color: #f8a84b;">${data.already_exists_count} mise(s) à jour</span>.
                <a href="${serverUrl}" target="_blank" style="color: #4f8ef7; margin-left: 8px; text-decoration: underline; font-weight: 600;">Ouvrir Immo-Boussole ↗</a>
            `;

            cancelBtn.textContent = 'Terminé';
            cancelBtn.classList.remove('secondary');
            cancelBtn.classList.add('primary');

        } catch (err) {
            console.error('[Immo-Boussole] Erreur lors de l\'import:', err);
            submitBtn.disabled = false;
            submitBtn.style.background = '#f25c69';
            submitBtn.querySelector('span').textContent = '❌ Réessayer';
            resultMsg.innerHTML = `<span style="color: #f25c69; font-weight: 600;">Erreur: ${err.message}</span>`;
        }
    };

})();
