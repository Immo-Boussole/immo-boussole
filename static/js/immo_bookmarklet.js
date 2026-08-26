/**
 * Immo-Boussole — Bookmarklet d'importation multi-portails
 * Permet l'extraction directe des annonces depuis le navigateur de l'utilisateur
 * (contournement DataDome / Cloudflare) et leur synchronisation avec Immo-Boussole.
 */
(async function() {
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

        static _normalizeImageUrl(url) {
            if (!url || typeof url !== 'string') return '';
            let u = url.trim();
            if (!u) return '';
            if (u.startsWith('//')) u = 'https:' + u;
            if (u.includes('/_next/image') && u.includes('url=')) {
                try {
                    const parsed = new URL(u, window.location.origin);
                    const realUrl = parsed.searchParams.get('url');
                    if (realUrl) u = decodeURIComponent(realUrl);
                } catch (e) {}
            }
            u = u.replace(/\/(?:crop|fit-in|resize|thumbnail)\/\d+x\d+\//i, '/fit-in/1920x1080/');
            u = u.replace(/\/\d+x\d+\//i, '/1920x1080/');
            try {
                const parsed = new URL(u);
                if (parsed.searchParams.has('w') || parsed.searchParams.has('width')) {
                    parsed.searchParams.set('w', '1920');
                    parsed.searchParams.delete('h');
                    parsed.searchParams.delete('height');
                    u = parsed.toString();
                }
            } catch (e) {}
            return u;
        }

        static _extractAllPhotos(node, depth = 0) {
            if (!node || depth > 8) return [];
            const photos = [];
            const isPhotoValid = (u) => {
                if (!u || typeof u !== 'string' || !u.startsWith('http')) return false;
                const low = u.toLowerCase();
                return !['logo', 'avatar', 'icon', 'placeholder', 'badge', 'pin-map', 'favicon', 'pixel'].some(k => low.includes(k));
            };
            const addUrl = (candidate) => {
                if (!candidate) return;
                const norm = SelogerParser._normalizeImageUrl(candidate);
                if (norm && isPhotoValid(norm) && !photos.includes(norm)) photos.push(norm);
            };

            const extractItem = (item) => {
                if (typeof item === 'string') addUrl(item);
                else if (item && typeof item === 'object') {
                    for (const k of ['hdUrl', 'largeUrl', 'fullUrl', 'url', 'src', 'path', 'contentUrl', 'uri', 'original', 'large', 'big', 'url_photo', 'url_large', 'rawUrl', 'thumbnail']) {
                        if (typeof item[k] === 'string') addUrl(item[k]);
                    }
                    if (item.image) extractItem(item.image);
                }
            };

            if (Array.isArray(node)) {
                node.forEach(extractItem);
            } else if (typeof node === 'object') {
                for (const k of ['images', 'photos', 'medias', 'pictures', 'rawPhotos', 'gallery']) {
                    if (node[k]) {
                        if (Array.isArray(node[k])) node[k].forEach(extractItem);
                        else if (typeof node[k] === 'object') {
                            for (const subK of ['images', 'photos', 'all', 'large', 'list']) {
                                if (Array.isArray(node[k][subK])) node[k][subK].forEach(extractItem);
                            }
                        }
                    }
                }
                for (const val of Object.values(node)) {
                    if (val && typeof val === 'object') {
                        SelogerParser._extractAllPhotos(val, depth + 1).forEach(p => {
                            if (!photos.includes(p)) photos.push(p);
                        });
                    }
                }
            }
            return photos;
        }

        static _parseHeatingString(text) {
            if (!text || typeof text !== 'string') return { type: null, mode: null };
            const t = text.trim();
            if (!t) return { type: null, mode: null };
            const tLow = t.toLowerCase();
            let mode = null;
            if (tLow.includes('individuel')) mode = 'Individuel';
            else if (tLow.includes('collectif')) mode = 'Collectif';

            let type = null;
            if (tLow.includes('pompe à chaleur') || tLow.includes('pompe a chaleur') || /\bpac\b/i.test(tLow)) type = 'Pompe à chaleur';
            else if (tLow.includes('climatisation') || tLow.includes('clim réversible') || tLow.includes('clim reversible')) type = 'Climatisation réversible';
            else if (tLow.includes('gaz')) type = 'Gaz';
            else if (tLow.includes('électrique') || tLow.includes('electrique') || tLow.includes('convecteur') || tLow.includes('radiateur')) type = 'Électrique';
            else if (tLow.includes('fioul') || tLow.includes('fuel') || tLow.includes('mazout')) type = 'Fioul';
            else if (tLow.includes('bois') || tLow.includes('granulé') || tLow.includes('pellet') || tLow.includes('poêle') || tLow.includes('poele')) type = 'Bois / Granulés';
            else if (tLow.includes('au sol') || tLow.includes('plancher chauffant')) type = 'Au sol';
            else if (tLow.includes('solaire')) type = 'Solaire';
            else if (tLow.includes('urbain') || tLow.includes('géothermie') || tLow.includes('geothermie')) type = 'Géothermie / Réseau urbain';
            else if (!mode && t.length < 40) {
                type = t.charAt(0).toUpperCase() + t.slice(1);
            }
            return { type, mode };
        }

        static _parseYear(val) {
            if (val === null || val === undefined) return null;
            if (typeof val === 'number') {
                const ival = Math.floor(val);
                return (ival >= 1700 && ival <= 2099) ? ival : null;
            }
            const m = String(val).match(/\b(1[789]\d{2}|20\d{2})\b/);
            return m ? parseInt(m[1], 10) : null;
        }

        static _extractBuildingYear(node, depth = 0) {
            if (!node || depth > 8) return null;
            if (typeof node === 'object') {
                for (const k of ['buildingYear', 'constructionYear', 'yearBuilt', 'anneeConstruction', 'year']) {
                    if (node[k] !== undefined && node[k] !== null) {
                        const y = SelogerParser._parseYear(node[k]);
                        if (y) return y;
                    }
                }
                if (node.building) {
                    const y = SelogerParser._extractBuildingYear(node.building, depth + 1);
                    if (y) return y;
                }
                if (node.general) {
                    const y = SelogerParser._extractBuildingYear(node.general, depth + 1);
                    if (y) return y;
                }
                for (const k of ['criterias', 'criteria', 'characteristics', 'features', 'tags', 'specifications']) {
                    if (Array.isArray(node[k])) {
                        for (const item of node[k]) {
                            if (typeof item === 'object' && item) {
                                const label = String(item.label || item.key || item.name || item.title || '').toLowerCase();
                                if (label.includes('construction') || label.includes('annee') || label.includes('année') || label.includes('year')) {
                                    const y = SelogerParser._parseYear(item.value || item.text || item.val);
                                    if (y) return y;
                                }
                            } else if (typeof item === 'string' && (item.includes('construction') || item.includes('année') || item.includes('annee'))) {
                                const y = SelogerParser._parseYear(item);
                                if (y) return y;
                            }
                        }
                    }
                }
            }
            return null;
        }

        static _extractHeating(node, depth = 0) {
            if (!node || depth > 8) return { type: null, mode: null };
            let type = null;
            let mode = null;
            if (typeof node === 'object' && node) {
                const energy = node.energy;
                if (typeof energy === 'object' && energy) {
                    for (const k of ['heating', 'heatingType', 'heatingMode', 'heatingSystem']) {
                        if (energy[k]) {
                            const res = SelogerParser._parseHeatingString(String(energy[k]));
                            if (res.type && !type) type = res.type;
                            if (res.mode && !mode) mode = res.mode;
                        }
                    }
                }
                for (const k of ['heating', 'heatingType', 'heatingMode', 'heatingSystem', 'chauffage']) {
                    if (node[k]) {
                        if (typeof node[k] === 'object') {
                            const res1 = SelogerParser._parseHeatingString(String(node[k].type || node[k].label || node[k].value || ''));
                            const res2 = SelogerParser._parseHeatingString(String(node[k].mode || ''));
                            if (res1.type && !type) type = res1.type;
                            if (res2.type && !type) type = res2.type;
                            if (res1.mode && !mode) mode = res1.mode;
                            if (res2.mode && !mode) mode = res2.mode;
                        } else {
                            const res = SelogerParser._parseHeatingString(String(node[k]));
                            if (res.type && !type) type = res.type;
                            if (res.mode && !mode) mode = res.mode;
                        }
                    }
                }
                for (const k of ['criterias', 'criteria', 'characteristics', 'features', 'tags', 'specifications']) {
                    if (Array.isArray(node[k])) {
                        for (const item of node[k]) {
                            if (typeof item === 'object' && item) {
                                const label = String(item.label || item.key || item.name || item.title || '').toLowerCase();
                                if (label.includes('chauffage') || label.includes('heating')) {
                                    const res = SelogerParser._parseHeatingString(String(item.value || item.text || item.val || ''));
                                    if (res.type && !type) type = res.type;
                                    if (res.mode && !mode) mode = res.mode;
                                }
                            } else if (typeof item === 'string' && item.toLowerCase().includes('chauffage')) {
                                const res = SelogerParser._parseHeatingString(item);
                                if (res.type && !type) type = res.type;
                                if (res.mode && !mode) mode = res.mode;
                            }
                        }
                    }
                }
            }
            return { type, mode };
        }

        static async parse() {
            const listings = [];
            const pathname = window.location.pathname;
            const isAdPage = (/\/annonce\/|\/annonces?\//.test(pathname)) && !pathname.includes('/resultats') && !pathname.includes('/recherche');

            // 1. Chercher les données structurées JSON
            let classified = null;
            let fullData = null;
            let searchAds = [];

            // A. window.__UFRN_LIFECYCLE_SERVERREQUEST__
            try {
                if (window.__UFRN_LIFECYCLE_SERVERREQUEST__) {
                    fullData = window.__UFRN_LIFECYCLE_SERVERREQUEST__;
                    const ufrn = fullData;
                    if (ufrn.app_cldp?.data?.classified) classified = ufrn.app_cldp.data.classified;
                    else if (ufrn.classified) classified = ufrn.classified;
                }
            } catch (e) {}

            // B. __NEXT_DATA__
            if (!classified) {
                const nextScript = document.getElementById('__NEXT_DATA__');
                if (nextScript) {
                    try {
                        fullData = JSON.parse(nextScript.textContent);
                        const pageProps = fullData?.props?.pageProps || {};
                        const listingData = pageProps.listingData || {};
                        classified = listingData.listing || listingData.classified || pageProps.classified || pageProps.ad || pageProps.initialState?.classified || pageProps.initialState?.listing;
                        searchAds = pageProps.searchData?.ads || pageProps.initialData?.searchData?.ads || [];
                    } catch (e) {}
                }
            }

            // C. Balises scripts JSON
            if (!classified) {
                document.querySelectorAll('script[type="application/json"]').forEach(s => {
                    if (!classified && (s.textContent.includes('classified') || s.textContent.includes('livingArea') || s.textContent.includes('price'))) {
                        try {
                            const d = JSON.parse(s.textContent);
                            if (d.classified) { classified = d.classified; fullData = d; }
                            else if (d.app_cldp?.data?.classified) { classified = d.app_cldp.data.classified; fullData = d; }
                        } catch (e) {}
                    }
                });
            }

            if (isAdPage) {
                if (classified) {
                    const formatted = await this._formatClassified(classified, fullData);
                    listings.push(formatted);
                    return { type: 'single', listings };
                }

                // Fallback DOM pour page de détail SeLoger
                const formattedDom = await this._parseAdFromDom();
                listings.push(formattedDom);
                return { type: 'single', listings };
            }

            // Page de recherche / liste
            if (searchAds && searchAds.length > 0) {
                for (const item of searchAds) {
                    listings.push(this._formatSearchAd(item));
                }
                return { type: 'search', listings };
            }

            // Fallback DOM pour page de recherche
            const adCards = document.querySelectorAll('div[data-test="sl.cards-container"], [class*="Card__Container"], a[href*="/annonce/"], a[href*="/annonces/"]');
            const seenUrls = new Set();
            adCards.forEach(card => {
                const anchor = card.tagName === 'A' ? card : card.querySelector('a[href*="/annonce/"], a[href*="/annonces/"]');
                if (!anchor) return;
                const rawHref = anchor.getAttribute('href');
                if (!rawHref) return;
                const fullUrl = rawHref.startsWith('http') ? rawHref.split('?')[0] : `https://www.seloger.com${rawHref.split('?')[0]}`;
                if (seenUrls.has(fullUrl)) return;
                seenUrls.add(fullUrl);

                const titleElem = card.querySelector('[class*="Card__Title"], [class*="title"], h2, h3') || anchor;
                const priceElem = card.querySelector('[class*="Price"], [data-test="price"]');
                const priceText = priceElem ? priceElem.textContent.replace(/[^\d]/g, '') : null;
                const price = priceText ? parseFloat(priceText) : null;

                const img = card.querySelector('img[src*="seloger"], img[src*="aviv"], img[src*="poliris"]');
                const rawSrc = img?.src || img?.getAttribute('src') || '';
                const photos = rawSrc ? [SelogerParser._normalizeImageUrl(rawSrc.split('?')[0])] : [];

                listings.push({
                    url: fullUrl,
                    title: titleElem?.textContent?.trim() || 'Annonce SeLoger',
                    price: price,
                    photos: photos,
                    source: 'seloger'
                });
            });

            return { type: listings.length === 1 ? 'single' : 'search', listings };
        }

        static async _formatClassified(classified, fullData = null) {
            const loc = classified.location || {};
            let city = loc.city || loc.cityName || classified.city || '';
            let zipcode = loc.zipCode || loc.postalCode || loc.postCode || classified.zipCode || '';
            
            if (!city && Array.isArray(loc.tags) && loc.tags.length > 0) {
                city = loc.tags[0];
            }
            if (city && !zipcode) {
                const cpMatch = String(city).match(/\b(\d{5})\b/);
                if (cpMatch) {
                    zipcode = cpMatch[1];
                    city = String(city).replace(/\(?\d{5}\)?/, '').trim();
                }
            }

            const locationStr = [city, zipcode ? `(${zipcode})` : ''].filter(Boolean).join(' ');

            // Pricing
            const pricing = classified.pricing || {};
            const priceVal = pricing.amount || pricing.price || classified.price || null;
            const charges = pricing.charges || classified.charges || null;
            const landTax = pricing.landTax || pricing.propertyTax || classified.landTax || null;

            // Characteristics
            const roomsInfo = classified.rooms || {};
            const rooms = roomsInfo.total || roomsInfo.roomCount || classified.roomCount || classified.rooms || null;
            const bedrooms = roomsInfo.bedrooms || roomsInfo.bedRooms || classified.bedroomCount || classified.bedrooms || null;
            const bathrooms = (roomsInfo.bathRooms || 0) + (roomsInfo.showerRooms || 0) || classified.bathroomCount || null;

            const area = classified.livingArea || classified.surface || classified.area || null;
            const landArea = classified.landSurface || classified.landArea || classified.groundArea || null;

            // DPE / GES
            const energy = classified.energy || {};
            const dpeObj = energy.dpe || {};
            const gesObj = energy.ges || {};
            const dpe = typeof dpeObj === 'string' ? dpeObj.charAt(0) : (dpeObj.grade || dpeObj.letter || classified.dpeRating || classified.energyRate || null);
            const ges = typeof gesObj === 'string' ? gesObj.charAt(0) : (gesObj.grade || gesObj.letter || classified.gesRating || classified.gesRate || null);

            // Title: Prioritize custom headline / title
            const title = classified.customTitle || classified.headline || classified.title || classified.subject || document.querySelector('h1')?.textContent?.trim() || document.title.replace(/\s*[-|]\s*SeLoger.*$/i, '').trim();

            // Description
            const description = classified.description || classified.body || '';

            // Medias & Floorplans
            let photos = SelogerParser._extractAllPhotos(classified);
            if ((!photos || photos.length < 2) && fullData) {
                const fullPhotos = SelogerParser._extractAllPhotos(fullData);
                fullPhotos.forEach(p => { if (!photos.includes(p)) photos.push(p); });
            }

            const floorplans = [];
            const domains = classified.domains || {};
            const medias = domains.medias || (classified.medias && typeof classified.medias === 'object' ? classified.medias : {});

            const fpList = medias.floorplans || medias.plans || medias.floorPlans || classified.floorplans || classified.floorPlans || classified.plans || [];
            if (Array.isArray(fpList)) {
                fpList.forEach(fp => {
                    const u = typeof fp === 'object' ? (fp.url || fp.src) : fp;
                    if (typeof u === 'string') {
                        const norm = SelogerParser._normalizeImageUrl(u);
                        if (norm && !floorplans.includes(norm)) floorplans.push(norm);
                    }
                });
            }

            // Fallback fetch floorplans if subpage exists
            const cleanUrl = window.location.href.split('?')[0].replace(/\/$/, '');
            if (floorplans.length === 0) {
                try {
                    const fpResp = await fetch(`${cleanUrl}/medias/floorplans`, { credentials: 'same-origin' });
                    if (fpResp.ok) {
                        const fpHtml = await fpResp.text();
                        const domParser = new DOMParser();
                        const fpDoc = domParser.parseFromString(fpHtml, 'text/html');
                        fpDoc.querySelectorAll('img[src*="seloger"], img[src*="aviv"], img[src*="poliris"]').forEach(img => {
                            const src = img.src || img.getAttribute('src');
                            if (src) {
                                const norm = SelogerParser._normalizeImageUrl(src);
                                if (norm && !floorplans.includes(norm) && !photos.includes(norm)) {
                                    floorplans.push(norm);
                                }
                            }
                        });
                    }
                } catch (e) {}
            }

            // Append floorplans to photos
            floorplans.forEach(fpUrl => {
                if (!photos.includes(fpUrl)) photos.push(fpUrl);
            });

            // Building Year & Heating
            const buildingYear = SelogerParser._extractBuildingYear(classified) || (fullData ? SelogerParser._extractBuildingYear(fullData) : null);
            let heating = SelogerParser._extractHeating(classified);
            if (!heating.type && !heating.mode && fullData) {
                heating = SelogerParser._extractHeating(fullData);
            }

            return {
                url: cleanUrl,
                external_id: classified.id ? `sl_${classified.id}` : undefined,
                title: title,
                price: typeof priceVal === 'number' ? priceVal : parseFloat(priceVal) || null,
                area: area ? parseFloat(area) : null,
                land_area: landArea ? parseFloat(landArea) : null,
                rooms: rooms ? parseInt(rooms, 10) : null,
                bedrooms: bedrooms ? parseInt(bedrooms, 10) : null,
                bathroom_count: bathrooms ? parseInt(bathrooms, 10) : null,
                city: city || 'France',
                postal_code: zipcode || null,
                location: locationStr || city || 'France',
                description: description,
                property_type: classified.propertyType || classified.estateType || null,
                dpe_rating: dpe ? String(dpe).toUpperCase().charAt(0) : null,
                ges_rating: ges ? String(ges).toUpperCase().charAt(0) : null,
                land_tax: landTax ? parseFloat(landTax) : null,
                charges: charges ? parseFloat(charges) : null,
                heating_type: heating.type || null,
                heating_mode: heating.mode || null,
                building_year: buildingYear || null,
                photos: photos,
                floorplans: floorplans,
                source: 'seloger'
            };
        }

        static async _parseAdFromDom() {
            const cleanUrl = window.location.href.split('?')[0].replace(/\/$/, '');
            const title = document.querySelector('h1')?.textContent?.trim() || document.title.replace(/\s*[-|]\s*SeLoger.*$/i, '').trim();
            const priceText = document.querySelector('[data-test="price"], .price, [class*="Price"]')?.textContent?.replace(/[^\d]/g, '');
            const price = priceText ? parseFloat(priceText) : null;
            const descElem = document.querySelector('[data-test="sl.description"], [data-test="description"], [class*="Description"], [class*="ShowMore"] p');
            const description = descElem ? (descElem.innerText || descElem.textContent).trim() : '';

            // Location
            const locElem = document.querySelector('[data-test="location"], [class*="Location"], [class*="Address"]');
            const locText = locElem ? locElem.textContent.trim() : '';
            let city = locText;
            let zipcode = '';
            const cpMatch = locText.match(/\b(\d{5})\b/);
            if (cpMatch) {
                zipcode = cpMatch[1];
                city = locText.replace(/\(?\d{5}\)?/, '').trim();
            }
            const locationStr = locText || [city, zipcode ? `(${zipcode})` : ''].filter(Boolean).join(' ');

            // Surface & rooms regex from badges / criteria
            let area = null;
            let rooms = null;
            let bedrooms = null;
            const bodyText = document.body.innerText || '';
            const areaMatch = bodyText.match(/(\d+(?:[.,]\d+)?)\s*m²/);
            if (areaMatch) area = parseFloat(areaMatch[1].replace(',', '.'));
            const roomsMatch = bodyText.match(/(\d+)\s*pièce/i);
            if (roomsMatch) rooms = parseInt(roomsMatch[1], 10);
            const bedsMatch = bodyText.match(/(\d+)\s*chambre/i);
            if (bedsMatch) bedrooms = parseInt(bedsMatch[1], 10);

            // Building Year & Heating from DOM & text
            let buildingYear = null;
            const yearMatch = bodyText.match(/(?:année(?:\s*de)?\s*construction|construite?\s*(?:en|dans\s*les\s*années)?|bâtie?\s*en)\s*[:\s]*(\d{4})\b/i) || bodyText.match(/\bconstruction\s*(?:de\s*)?(\d{4})\b/i);
            if (yearMatch) buildingYear = SelogerParser._parseYear(yearMatch[1]);

            let heating = { type: null, mode: null };
            const heatMatch = bodyText.match(/chauffage\s*(?:[:\s]|est\s*de\s*type\s*)?\s*([a-zA-ZÀ-ÿ\s\(\)\/]+?)(?:\.|\n|,|$|;)/i);
            if (heatMatch) heating = SelogerParser._parseHeatingString(heatMatch[0]);
            if (!heating.type) heating = SelogerParser._parseHeatingString(bodyText);

            // Photos & Floorplans
            const photos = [];
            const floorplans = [];
            document.querySelectorAll('img[src*="seloger"], img[src*="aviv"], img[src*="poliris"]').forEach(img => {
                const src = (img.src || img.getAttribute('src') || '').split('?')[0];
                if (src && !photos.includes(src)) photos.push(src);
            });

            try {
                const fpResp = await fetch(`${cleanUrl}/medias/floorplans`, { credentials: 'same-origin' });
                if (fpResp.ok) {
                    const fpHtml = await fpResp.text();
                    const domParser = new DOMParser();
                    const fpDoc = domParser.parseFromString(fpHtml, 'text/html');
                    fpDoc.querySelectorAll('img[src*="seloger"], img[src*="aviv"], img[src*="poliris"]').forEach(img => {
                        const src = (img.src || img.getAttribute('src') || '').split('?')[0];
                        if (src && !floorplans.includes(src)) {
                            floorplans.push(src);
                            if (!photos.includes(src)) photos.push(src);
                        }
                    });
                }
            } catch (e) {}

            return {
                url: cleanUrl,
                title: title,
                price: price,
                area: area,
                rooms: rooms,
                bedrooms: bedrooms,
                city: city || 'France',
                postal_code: zipcode || null,
                location: locationStr || city || 'France',
                description: description,
                heating_type: heating.type || null,
                heating_mode: heating.mode || null,
                building_year: buildingYear || null,
                photos: photos,
                floorplans: floorplans,
                source: 'seloger'
            };
        }

        static _formatSearchAd(ad) {
            const loc = ad.location || {};
            const city = loc.city || loc.cityName || '';
            const zipcode = loc.zipCode || loc.postalCode || '';
            const locStr = [city, zipcode ? `(${zipcode})` : ''].filter(Boolean).join(' ');

            return {
                url: ad.url || (ad.permalink ? `https://www.seloger.com${ad.permalink}` : window.location.href),
                external_id: ad.id ? `sl_${ad.id}` : undefined,
                title: ad.customTitle || ad.headline || ad.title || ad.subject || 'Annonce SeLoger',
                price: typeof ad.price === 'number' ? ad.price : parseFloat(ad.price) || null,
                area: ad.surface || ad.livingArea ? parseFloat(ad.surface || ad.livingArea) : null,
                rooms: ad.rooms || ad.roomCount ? parseInt(ad.rooms || ad.roomCount, 10) : null,
                city: city,
                postal_code: zipcode,
                location: locStr || city || 'France',
                photos: Array.isArray(ad.photos) ? ad.photos : [],
                source: 'seloger'
            };
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
    const parseResult = await parser.parse();
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
