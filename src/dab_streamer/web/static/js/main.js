/**
 * DAB+ Podcast Streamer - Main JavaScript
 */

// Global state
const DABStreamer = {
    isPlaying: false,
    currentTrack: null,
    refreshInterval: null
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    updateBroadcastIndicator();
    startStatusRefresh();
});

/**
 * Update the broadcast status indicator in navbar
 */
async function updateBroadcastIndicator() {
    try {
        const res = await fetch('/api/broadcast/status');
        const data = await res.json();

        if (data.success) {
            const badge = document.getElementById('broadcast-status');
            const scheduler = data.scheduler;

            if (scheduler.playing) {
                badge.className = 'badge bg-success me-2';
                badge.innerHTML = '<i class="bi bi-circle-fill"></i> En diffusion';
                DABStreamer.isPlaying = true;
            } else if (scheduler.running) {
                badge.className = 'badge bg-warning me-2';
                badge.innerHTML = '<i class="bi bi-circle-fill"></i> En attente';
                DABStreamer.isPlaying = false;
            } else {
                badge.className = 'badge bg-secondary me-2';
                badge.innerHTML = '<i class="bi bi-circle-fill"></i> Hors ligne';
                DABStreamer.isPlaying = false;
            }

            DABStreamer.currentTrack = scheduler.current_item;
        }
    } catch (error) {
        console.error('Error updating broadcast indicator:', error);
    }
}

/**
 * Start periodic status refresh
 */
function startStatusRefresh() {
    if (DABStreamer.refreshInterval) {
        clearInterval(DABStreamer.refreshInterval);
    }
    DABStreamer.refreshInterval = setInterval(updateBroadcastIndicator, 5000);
}

/**
 * Stop periodic status refresh
 */
function stopStatusRefresh() {
    if (DABStreamer.refreshInterval) {
        clearInterval(DABStreamer.refreshInterval);
        DABStreamer.refreshInterval = null;
    }
}

/**
 * Format duration from seconds to MM:SS
 */
function formatDuration(seconds) {
    if (!seconds || seconds === 0) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

/**
 * Format file size
 */
function formatFileSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

/**
 * Format date
 */
function formatDate(dateString) {
    if (!dateString) return '-';
    const date = new Date(dateString);
    return date.toLocaleDateString('fr-FR', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    // Create toast container if it doesn't exist
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        document.body.appendChild(container);
    }

    // Create toast
    const toastId = 'toast-' + Date.now();
    const bgClass = {
        'info': 'bg-info',
        'success': 'bg-success',
        'warning': 'bg-warning',
        'error': 'bg-danger'
    }[type] || 'bg-info';

    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white ${bgClass} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, { delay: 3000 });
    toast.show();

    // Remove after hidden
    toastElement.addEventListener('hidden.bs.toast', () => {
        toastElement.remove();
    });
}

/**
 * Confirm dialog wrapper
 */
function confirmAction(message, callback) {
    if (confirm(message)) {
        callback();
    }
}

/**
 * API helper function
 */
async function apiCall(endpoint, method = 'GET', data = null) {
    const options = {
        method: method,
        headers: {}
    };

    if (data) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(data);
    }

    try {
        const response = await fetch(endpoint, options);
        const result = await response.json();

        if (!result.success && result.error) {
            showToast(result.error, 'error');
        }

        return result;
    } catch (error) {
        console.error('API Error:', error);
        showToast('Erreur de connexion', 'error');
        return { success: false, error: error.message };
    }
}

/**
 * Debounce function
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

/**
 * Copy text to clipboard
 */
async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        showToast('Copié dans le presse-papiers', 'success');
    } catch (error) {
        console.error('Copy failed:', error);
        showToast('Erreur lors de la copie', 'error');
    }
}

// Export for use in templates
window.DABStreamer = DABStreamer;
window.formatDuration = formatDuration;
window.formatFileSize = formatFileSize;
window.formatDate = formatDate;
window.showToast = showToast;
window.confirmAction = confirmAction;
window.apiCall = apiCall;
window.debounce = debounce;
window.copyToClipboard = copyToClipboard;
