/**
 * Address Autocomplete Helper (BAN / api-adresse.data.gouv.fr)
 * Immo-Boussole
 */

function initAddressAutocomplete(options) {
    const input = document.getElementById(options.inputId);
    const dropdown = document.getElementById(options.dropdownId);
    const spinner = options.spinnerId ? document.getElementById(options.spinnerId) : null;
    const clearBtn = options.clearBtnId ? document.getElementById(options.clearBtnId) : null;
    const onSelect = options.onSelect || function() {};
    const onClear = options.onClear || function() {};

    if (!input || !dropdown) return;

    let debounceTimer = null;
    let currentResults = [];
    let highlightedIndex = -1;

    function updateClearBtn() {
        if (clearBtn) {
            clearBtn.style.display = input.value.trim() ? 'flex' : 'none';
        }
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            input.value = '';
            closeDropdown();
            updateClearBtn();
            onClear();
            input.focus();
        });
    }

    input.addEventListener('input', () => {
        updateClearBtn();
        const query = input.value.trim();
        if (query.length < 2) {
            closeDropdown();
            return;
        }

        if (spinner) spinner.style.display = 'inline-block';
        if (debounceTimer) clearTimeout(debounceTimer);

        debounceTimer = setTimeout(async () => {
            try {
                const res = await fetch(`/api/geo/address-autocomplete?q=${encodeURIComponent(query)}&limit=6`);
                if (!res.ok) throw new Error('Network error');
                const data = await res.json();
                currentResults = data.results || [];
                renderDropdown(currentResults);
            } catch (err) {
                console.error('[Autocomplete Error]', err);
                closeDropdown();
            } finally {
                if (spinner) spinner.style.display = 'none';
            }
        }, 220);
    });

    input.addEventListener('keydown', (e) => {
        if (!dropdown.classList.contains('open') || currentResults.length === 0) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            highlightedIndex = (highlightedIndex + 1) % currentResults.length;
            updateHighlight();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            highlightedIndex = (highlightedIndex - 1 + currentResults.length) % currentResults.length;
            updateHighlight();
        } else if (e.key === 'Enter') {
            if (highlightedIndex >= 0 && highlightedIndex < currentResults.length) {
                e.preventDefault();
                selectItem(currentResults[highlightedIndex]);
            }
        } else if (e.key === 'Escape') {
            closeDropdown();
        }
    });

    document.addEventListener('click', (e) => {
        if (!input.contains(e.target) && !dropdown.contains(e.target)) {
            closeDropdown();
        }
    });

    function renderDropdown(items) {
        dropdown.innerHTML = '';
        highlightedIndex = -1;

        if (!items || items.length === 0) {
            closeDropdown();
            return;
        }

        items.forEach((item, idx) => {
            const li = document.createElement('li');
            li.className = 'address-suggestion-item';
            
            const prec = item.precision || 'city';
            let iconClass = 'fa-city';
            let precLabel = 'Commune';

            if (prec === 'exact') {
                iconClass = 'fa-bullseye';
                precLabel = item.city || 'Exact';
            } else if (prec === 'street') {
                iconClass = 'fa-location-dot';
                precLabel = 'Rue';
            }

            li.innerHTML = `
                <div class="address-suggestion-left">
                    <div class="address-suggestion-icon ${prec}">
                        <i class="fa-solid ${iconClass}"></i>
                    </div>
                    <div class="address-suggestion-texts">
                        <div class="address-suggestion-title">${escapeHtml(item.name || item.label)}</div>
                        <div class="address-suggestion-subtitle">${escapeHtml(item.postcode ? item.postcode + ' ' + item.city : item.city || item.context || '')}</div>
                    </div>
                </div>
                <span class="address-suggestion-type-badge ${prec}">${precLabel}</span>
            `;

            li.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                selectItem(item);
            });

            dropdown.appendChild(li);
        });

        dropdown.classList.add('open');
    }

    function updateHighlight() {
        const items = dropdown.querySelectorAll('.address-suggestion-item');
        items.forEach((el, i) => {
            if (i === highlightedIndex) {
                el.classList.add('highlighted');
                el.scrollIntoView({ block: 'nearest' });
            } else {
                el.classList.remove('highlighted');
            }
        });
    }

    function selectItem(item) {
        input.value = item.label || item.name;
        updateClearBtn();
        closeDropdown();
        onSelect(item);
    }

    function closeDropdown() {
        dropdown.classList.remove('open');
        dropdown.innerHTML = '';
        highlightedIndex = -1;
    }

    function escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    return {
        setValue: function(val) {
            input.value = val || '';
            updateClearBtn();
        },
        clear: function() {
            input.value = '';
            closeDropdown();
            updateClearBtn();
        }
    };
}
