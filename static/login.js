// ==================================================
// Login page initialisation and startup
// ==================================================

const instanceId = getInstanceId();
const bootstrapColors = ['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'];
const basicAuth = document.getElementById("auth-form");
const oidcAuth = document.getElementById("oidc-container");
const oidcBtn = document.getElementById("oidc-btn");
const separator = document.getElementById("auth-separator");
const versionElement = document.getElementById("app-version");


function getInstanceId() {
    // Fallback for browsers that don't support crypto.randomUUID()
    const fallbackUUID = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = (Math.random() * 16) | 0, v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });

    let uuid = localStorage.getItem('persistent_uuid');
    if (!uuid) {
        uuid = (typeof crypto !== 'undefined' && crypto.randomUUID) ? crypto.randomUUID() : fallbackUUID();
        localStorage.setItem('persistent_uuid', uuid);
    }
    return uuid;
}

document.addEventListener("DOMContentLoaded", function () {
    getAuthStatus();
});

async function getAuthStatus() {
    try {
        const response = await fetch("/api/auth/status");
        const data = await response.json();

        const basicAuthEnabled = data.basic_enabled;
        const oidcAuthEnabled = data.oidc_enabled;
        const oidcLabel = data.oidc_label;
        const version = data.version;

        basicAuth.style.display = basicAuthEnabled ? "block" : "none";
        oidcBtn.style.display = oidcAuthEnabled ? "block" : "none";
        oidcBtn.textContent = `Sign In with ${oidcLabel != "" ? oidcLabel : "OIDC"}`

        versionElement.textContent = `v${version}`;

        separator.classList.toggle("d-none", !basicAuthEnabled || !oidcAuthEnabled);
    } catch (err) {
        console.error("Failed to fetch auth status:", err);
    }
}
