/**
 * Visit Status Badge Component & Management for Immo-Boussole
 */

const VISIT_STATUS_CONFIG = {
    retour_agence: {
        key: 'retour_agence',
        label: "Retour d'agence pour RDV",
        shortLabel: "Retour agence",
        icon: "fa-solid fa-comments",
        badgeClass: "status-retour_agence",
        itemClass: "item-retour_agence",
        stepFamily: "contact",
        step: "appel_direct",
        status: "programme",
        color: "#38bdf8"
    },
    visite_programmee: {
        key: 'visite_programmee',
        label: "Visite programmée",
        shortLabel: "Visite programmée",
        icon: "fa-solid fa-calendar-check",
        badgeClass: "status-visite_programmee",
        itemClass: "item-visite_programmee",
        stepFamily: "visite",
        step: "1ere_visite",
        status: "programme",
        color: "#818cf8"
    },
    deja_visitee: {
        key: 'deja_visitee',
        label: "Déjà visitée, réflexion",
        shortLabel: "Déjà visitée",
        icon: "fa-solid fa-brain",
        badgeClass: "status-deja_visitee",
        itemClass: "item-deja_visitee",
        stepFamily: "visite",
        step: "1ere_visite",
        status: "effectuee",
        color: "#fbbf24"
    },
    sans_suite_acheteur: {
        key: 'sans_suite_acheteur',
        label: "Sans suite acheteur",
        shortLabel: "Sans suite (acheteur)",
        icon: "fa-solid fa-user-slash",
        badgeClass: "status-sans_suite_acheteur",
        itemClass: "item-sans_suite_acheteur",
        stepFamily: "cloture",
        step: "offre_refusee",
        status: "annulee",
        color: "#ef4444"
    },
    sans_suite_visiteur: {
        key: 'sans_suite_visiteur',
        label: "Sans suite visiteur",
        shortLabel: "Sans suite (visiteur)",
        icon: "fa-solid fa-ban",
        badgeClass: "status-sans_suite_visiteur",
        itemClass: "item-sans_suite_visiteur",
        stepFamily: "cloture",
        step: "abandon",
        status: "annulee",
        color: "#ef4444"
    },
    a_relancer: {
        key: 'a_relancer',
        label: "A relancer pour RDV",
        shortLabel: "A relancer",
        icon: "fa-solid fa-clock-rotate-left",
        badgeClass: "status-a_relancer",
        itemClass: "item-a_relancer",
        stepFamily: "contact",
        step: "relance_sans_reponse",
        status: "programme",
        color: "#fb923c"
    }
};

/**
 * Returns the HTML for a visit status badge & dropdown container
 */
function renderVisitStatusBadge(listingId, currentStatus, listingTitle = '') {
    const safeTitle = (listingTitle || '').replace(/"/g, '&quot;');
    const current = VISIT_STATUS_CONFIG[currentStatus];

    let badgeHtml = '';
    if (current) {
        badgeHtml = `
            <div class="visit-status-badge ${current.badgeClass}" title="${current.label} (cliquer pour modifier)">
                <i class="${current.icon}"></i>
                <span class="badge-text">${current.label}</span>
                <i class="fa-solid fa-chevron-down badge-caret"></i>
            </div>
        `;
    } else {
        badgeHtml = `
            <div class="visit-status-add-btn" title="Définir un état de visite">
                <i class="fa-solid fa-plus"></i>
            </div>
        `;
    }

    let menuItems = '';
    for (const [key, cfg] of Object.entries(VISIT_STATUS_CONFIG)) {
        const isActive = (currentStatus === key) ? 'active' : '';
        menuItems += `
            <div class="visit-status-item ${cfg.itemClass} ${isActive}" data-status="${key}">
                <span class="dot"></span>
                <i class="${cfg.icon}" style="width: 14px; text-align: center;"></i>
                <span>${cfg.label}</span>
            </div>
        `;
    }

    if (currentStatus) {
        menuItems += `
            <div class="visit-status-item item-clear" data-status="">
                <i class="fa-solid fa-xmark" style="width: 14px; text-align: center;"></i>
                <span>Effacer l'état</span>
            </div>
        `;
    }

    return `
        <div class="visit-status-container ${!current ? 'show-add' : ''}" data-listing-id="${listingId}" data-listing-title="${safeTitle}" onclick="event.stopPropagation();">
            ${badgeHtml}
            <div class="visit-status-menu">
                ${menuItems}
            </div>
        </div>
    `;
}

/**
 * Sets up global event delegation for all visit status badges
 */
document.addEventListener('DOMContentLoaded', () => {
    // Toggle dropdown open/close on badge or add-btn click
    document.addEventListener('click', (e) => {
        const trigger = e.target.closest('.visit-status-badge, .visit-status-add-btn');
        if (trigger) {
            e.preventDefault();
            e.stopPropagation();
            const container = trigger.closest('.visit-status-container');
            const wasOpen = container.classList.contains('open');

            // Close all others
            document.querySelectorAll('.visit-status-container.open').forEach(c => c.classList.remove('open'));

            if (!wasOpen) {
                container.classList.add('open');
            }
            return;
        }

        // Handle item selection in dropdown
        const item = e.target.closest('.visit-status-item');
        if (item) {
            e.preventDefault();
            e.stopPropagation();
            const container = item.closest('.visit-status-container');
            const listingId = container.dataset.listingId;
            const listingTitle = container.dataset.listingTitle || '';
            const newStatus = item.dataset.status;

            container.classList.remove('open');
            updateListingVisitStatus(listingId, newStatus, listingTitle);
            return;
        }

        // Click outside closes all dropdowns
        document.querySelectorAll('.visit-status-container.open').forEach(c => c.classList.remove('open'));
    });
});

/**
 * Updates a listing's visit status via API and updates UI
 */
async function updateListingVisitStatus(listingId, newStatus, listingTitle = '') {
    try {
        const res = await fetch(`/api/listings/${listingId}/visit-status`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ last_visit_status: newStatus || null })
        });

        if (!res.ok) {
            throw new Error('Erreur lors de la mise à jour');
        }

        const data = await res.json();
        const updatedStatus = data.last_visit_status;

        // Update all badge containers for this listing on the page
        document.querySelectorAll(`.visit-status-container[data-listing-id="${listingId}"]`).forEach(c => {
            c.outerHTML = renderVisitStatusBadge(listingId, updatedStatus, listingTitle);
        });

        // Update card data attribute for filtering if present
        document.querySelectorAll(`[data-id="${listingId}"], [data-listing-id="${listingId}"]`).forEach(el => {
            el.dataset.visitStatus = updatedStatus || '';
            if (updatedStatus in {'visite_programmee':1, 'retour_agence':1, 'deja_visitee':1, 'a_relancer':1}) {
                el.dataset.toVisit = 'true';
            } else if (updatedStatus in {'sans_suite_acheteur':1, 'sans_suite_visiteur':1}) {
                el.dataset.toVisit = 'false';
            }
        });

        // Trigger filter refresh if active
        if (typeof applyListingFilters === 'function') {
            applyListingFilters();
        }

        // If a status was selected (not cleared), prompt to create visit in Visit Manager
        if (updatedStatus && VISIT_STATUS_CONFIG[updatedStatus]) {
            showVisitSyncConfirmationModal(listingId, updatedStatus, listingTitle);
        }

    } catch (err) {
        console.error('Error updating visit status:', err);
        if (typeof showToast === 'function') {
            showToast('Erreur lors de la mise à jour de l\'état de visite', 'error');
        } else {
            alert('Erreur lors de la mise à jour de l\'état de visite');
        }
    }
}

/**
 * Shows confirmation modal proposing to create a matching visit in Visit Manager
 */
function showVisitSyncConfirmationModal(listingId, statusKey, listingTitle) {
    const cfg = VISIT_STATUS_CONFIG[statusKey];
    if (!cfg) return;

    // Remove existing modal if any
    const existing = document.getElementById('visitStatusSyncModal');
    if (existing) existing.remove();

    const dateFormatted = new Date().toLocaleDateString('fr-FR', {
        day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'
    });

    const modalHtml = `
        <div class="visit-status-modal-overlay" id="visitStatusSyncModal" onclick="closeVisitSyncModal(event)">
            <div class="visit-status-modal" onclick="event.stopPropagation()">
                <div class="visit-status-modal-header">
                    <div class="visit-status-modal-icon" style="background: ${cfg.color}25; color: ${cfg.color};">
                        <i class="${cfg.icon}"></i>
                    </div>
                    <div>
                        <div class="visit-status-modal-title">Créer une entrée dans les visites ?</div>
                        <div style="font-size: 0.75rem; color: ${cfg.color}; font-weight: 600;">${cfg.label}</div>
                    </div>
                </div>
                <div class="visit-status-modal-body">
                    L'état du bien a été mis à jour. Souhaitez-vous enregistrer également cette étape dans votre <strong>Gestionnaire de visites</strong> ?
                    <div class="visit-status-preview-box">
                        <div class="visit-status-preview-row">
                            <span class="visit-status-preview-label">Bien :</span>
                            <span class="visit-status-preview-value">#${listingId} ${listingTitle ? '— ' + listingTitle.slice(0, 30) + '...' : ''}</span>
                        </div>
                        <div class="visit-status-preview-row">
                            <span class="visit-status-preview-label">Étape :</span>
                            <span class="visit-status-preview-value">${cfg.stepFamily.toUpperCase()} (${cfg.step})</span>
                        </div>
                        <div class="visit-status-preview-row">
                            <span class="visit-status-preview-label">Date :</span>
                            <span class="visit-status-preview-value">${dateFormatted}</span>
                        </div>
                    </div>
                </div>
                <div class="visit-status-modal-actions">
                    <button class="visit-status-modal-btn cancel" onclick="closeVisitSyncModal()">Non, conserver uniquement l'état</button>
                    <button class="visit-status-modal-btn confirm" onclick="confirmVisitSync(${listingId}, '${statusKey}')">
                        <i class="fa-solid fa-check" style="margin-right: 4px;"></i> Oui, créer la visite
                    </button>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
}

function closeVisitSyncModal() {
    const modal = document.getElementById('visitStatusSyncModal');
    if (modal) modal.remove();
}

/**
 * Creates the visit in backend
 */
async function confirmVisitSync(listingId, statusKey) {
    const cfg = VISIT_STATUS_CONFIG[statusKey];
    if (!cfg) return;

    try {
        const payload = {
            listing_id: parseInt(listingId),
            step_family: cfg.stepFamily,
            step: cfg.step,
            visit_type: cfg.stepFamily === 'cloture' ? 'reponse_negative' : (cfg.step === 'contre_visite' ? 'contre_visite' : (cfg.stepFamily === 'contact' ? 'contact_agence' : 'visite')),
            scheduled_at: new Date().toISOString(),
            status: cfg.status,
            notes: `Créé automatiquement suite au passage à l'état '${cfg.label}'`
        };

        const res = await fetch('/api/visites', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        if (!res.ok) throw new Error('Erreur lors de la création de la visite');

        closeVisitSyncModal();
        if (typeof showToast === 'function') {
            showToast('Visite créée avec succès dans le gestionnaire de visites !', 'success');
        } else {
            // fallback notification
            const toast = document.createElement('div');
            toast.style.cssText = 'position:fixed;bottom:20px;right:20px;background:#10d9a4;color:#0b0f1a;padding:10px 18px;border-radius:10px;font-weight:700;z-index:999999;box-shadow:0 8px 24px rgba(0,0,0,0.5);';
            toast.textContent = 'Visite créée avec succès dans le gestionnaire !';
            document.body.appendChild(toast);
            setTimeout(() => toast.remove(), 3500);
        }
    } catch (err) {
        console.error('Error creating visit:', err);
        alert('Erreur lors de la création de la visite dans le gestionnaire.');
    }
}
