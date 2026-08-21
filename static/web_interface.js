
// ==================================================
// App initialisation and startup
// ==================================================

let config = {};                // Current configuration
let statusTimeout;              // Store timeout reference
let schedules = [];             // Scheduled imports
let currentBulkImport = '';     // Current bulk import file
let bulkTextAsLoaded = '';      // File contents when loaded, to determine changes
let barTimer = null;            // Timer for progress bar
let docker = false;             // Docker environment detected or not
let tvPicker, moviePicker, tpdbUserPicker;
let validationTimeout
let currentBrowseTargetInput = null;
let currentDirectoryPath = "/";
let initialConfig = ''

const socket = io();
const instanceId = getInstanceId();
const bootstrapColors = ['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'];
const CHUNK_SIZE = 1024 * 512; // 512 KB per chunk for uploads

function initInteractiveTooltip(tooltipTriggerEl) {
    if (!tooltipTriggerEl || bootstrap.Tooltip.getInstance(tooltipTriggerEl)) return; // Already initialized

    let hideTimeout = null;

    const tooltip = new bootstrap.Tooltip(tooltipTriggerEl, {
        html: true,
        sanitize: false,
        container: 'body',
        delay: { show: 100, hide: 250 } // 250ms buffer to cross the gap
    });

    // When the mouse enters the (i) icon, clear any pending hide timers
    tooltipTriggerEl.addEventListener('mouseenter', () => {
        if (hideTimeout) clearTimeout(hideTimeout);
    });

    // Listen for when Bootstrap actually renders the tooltip box in the DOM
    tooltipTriggerEl.addEventListener('inserted.bs.tooltip', () => {
        const tooltipElement = document.getElementById(tooltipTriggerEl.getAttribute('aria-describedby'));
        if (!tooltipElement) return;

        // When mouse enters the tooltip box itself, stop Bootstrap from hiding it
        tooltipElement.addEventListener('mouseenter', () => {
            // Intercept Bootstrap's internal hide timer
            const instance = bootstrap.Tooltip.getInstance(tooltipTriggerEl);
            if (instance && instance._timeout) {
                clearTimeout(instance._timeout);
                instance._timeout = 0;
            }
        });

        // Hide smoothly when mouse leaves the tooltip box
        tooltipElement.addEventListener('mouseleave', () => {
            const instance = bootstrap.Tooltip.getInstance(tooltipTriggerEl);
            if (instance) instance.hide();
        });
    });
};

document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    initInteractiveTooltip(el);
});

// UI References
const scrapeUrlInput = document.getElementById("scrape_url");
const dropArea = document.getElementById("drop-area");
const scheduleIcon = document.getElementById("schedule_icon");
const setTimeBtn = document.getElementById("set_time");
const scheduleTimeInput = document.getElementById("schedule_time");
const scheduleTypeSelect = document.getElementById("schedule_type");
const scheduleTimeGroup = document.getElementById("schedule_time_group");
const scheduleIntervalGroup = document.getElementById("schedule_interval_group");
const scheduleIntervalValueInput = document.getElementById("schedule_interval_value");
const scheduleIntervalUnitSelect = document.getElementById("schedule_interval_unit");
const scheduleListEl = document.getElementById("schedule_list");
const timeSelectBox = document.getElementById("time_select_box");
const runNowLabel = document.getElementById("run_now_label");
const runNowCheckbox = document.getElementById("run_now_checkbox");
const bulkFileSwitcher = document.getElementById("switch_bulk_file");

// Event listeners
document.addEventListener("DOMContentLoaded", function () {
    updateLog("📍 New session started with ID: " + instanceId)


    const stickyContainers = document.querySelectorAll(".sticky-bottom");

    stickyContainers.forEach(container => {
        // Find collapsible FABs inside this specific container
        const fabBtns = container.querySelectorAll(".fab-collapse");
        if (!fabBtns.length) return;

        // Create or find a sentinel right above this container
        let sentinel = container.previousElementSibling;
        if (!sentinel || !sentinel.classList.contains("fab-sentinel")) {
            sentinel = document.createElement("div");
            sentinel.className = "fab-sentinel";
            sentinel.style.height = "1px";
            sentinel.style.marginTop = "1rem";
            container.parentNode.insertBefore(sentinel, container);
        }

        // Set up observer for this container's sentinel
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                fabBtns.forEach(btn => {
                    if (entry.isIntersecting) {
                        btn.classList.remove("collapsed"); // Expand at bottom
                        btn.classList.add("gap-2");
                    } else {
                        btn.classList.add("collapsed");    // Collapse over content
                        btn.classList.remove("gap-2");
                    }
                });
            });
        }, {
            root: null,
            rootMargin: "0px 0px 20px 0px",
            threshold: 0
        });

        observer.observe(sentinel);
    });

    // Initialize the folder browser modal for Kometa asset and temp directory selection (non-docker)
    const folderModalElement = document.getElementById("folderBrowserModal");
    if (!folderModalElement) return;

    // Prevent 'aria-hidden on focused element' warning on close (Cancel, X, or Confirm)
    folderModalElement.addEventListener("hide.bs.modal", () => {
        // 1. Clear focus from whatever element currently has focus inside the modal
        if (folderModalElement.contains(document.activeElement)) {
            document.activeElement.blur();
        }

        // 2. Safely return focus to the input or button that opened the modal
        if (currentBrowseTargetInput) {
            currentBrowseTargetInput.focus();
        }
        // Clear folder name field
        document.getElementById("new_folder_name").value = '';
        toggleConfigButtons();
    });
        
    const folderModal = new bootstrap.Modal(folderModalElement, {
        focus: false
    });

    // Attach click event to all browse buttons
    document.querySelectorAll(".browse-folder-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-target");
            currentBrowseTargetInput = document.getElementById(targetId);

            // Start browsing at current field value if present, or root
            const initialPath = currentBrowseTargetInput.value.trim() || "/";
            loadDirectory(initialPath);
            folderModal.show();
        });
    });

    // Up directory navigation button
    document.getElementById("folder_nav_up").addEventListener("click", () => {
        const parts = currentDirectoryPath.split("/").filter(Boolean);
        parts.pop();
        const parentPath = "/" + parts.join("/");
        loadDirectory(parentPath || "/");
    });

    // Confirm selection button
    document.getElementById("select_folder_confirm").addEventListener("click", () => {
        if (currentBrowseTargetInput) {
            currentBrowseTargetInput.value = currentDirectoryPath;
        }
        document.getElementById("select_folder_confirm").blur(); // Remove focus from the confirm button
        folderModal.hide();
    });

    // Enable or disabled add folder button
    document.getElementById("new_folder_name").addEventListener("input", () => {

        const newFolderField = document.getElementById("new_folder_name");
        const newFolderName = newFolderField.value;
        const newFolderButton = document.getElementById("add_folder");
        
        if (newFolderName) {
            newFolderButton.classList.remove("btn-secondary");
            newFolderButton.classList.add("btn-success");
            newFolderButton.disabled = false;
        } else {
            newFolderButton.disabled = true;
            newFolderButton.classList.add("btn-secondary");
            newFolderButton.classList.remove("btn-success");
        }
    });

    // Add folder button listener
    document.getElementById("add_folder").addEventListener("click", () => {
        const newFolderField = document.getElementById("new_folder_name");
        const newFolderName = newFolderField.value;
        const currentPath = document.getElementById("folder_current_path").textContent;
        const newFolderButton = document.getElementById("add_folder");
        
        socket.on("folder_created", (data) => {
            if (validResponse(data)) {
                if (data.success) {
                    newFolderField.value = '';
                    newFolderButton.disabled = true
                    newFolderButton.classList.add("btn-secondary");
                    newFolderButton.classList.remove("btn-success");
                    loadDirectory(data.path)
                }
            }
        })
        
        socket.emit("create_directory", {
            instance_id: instanceId,
            parent_path: currentPath,
            folder_name: newFolderName
        });
    });


    // Initialize the 'eye' icons to toggle between masked and non-masked view
    // for Plex and webhook token input fields
    document.querySelectorAll(".toggle-password-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            const targetId = btn.getAttribute("data-target");
            const targetInput = document.getElementById(targetId);
            const icon = btn.querySelector("i");

            if (!targetInput || !icon) return;

            if (targetInput.type === "password") {
                targetInput.type = "text";
                icon.className = "bi bi-eye-slash";
                btn.setAttribute("title", "Hide token");
            } else {
                targetInput.type = "password";
                icon.className = "bi bi-eye";
                btn.setAttribute("title", "Show token");
            }
        });
    });

    // Initialize TomSelect Pickers
    tpdbUserPicker = new TomSelect('#webhook_tpdb_users', {
            create: true,
            createOnBlur: true,
            delimiter: ',',
            persist: true,
            plugins: {
                'clear_button': {
                    html: (data) => `<div class="${data.className}" title="${data.title}"><i class="bi bi-x-circle"></i></div>`
                },
                'remove_button': {}
            }
        });
    
    tvPicker = new TomSelect('#tv_library', {
        inputTypes: [],
        controlInput: '<input readonly>',
        plugins: {
        'clear_button': {
            html: (data) => `<div class="${data.className}" title="${data.title}"><i class="bi bi-x-circle"></i></div>`
        },
        'remove_button': {}
    },
        onChange: () => updatePickerLabel(tvPicker)
    });
    tvPicker.on('clear', () => {
        tvPicker.refreshOptions(false); // Refreshes the dropdown list without closing it
        updatePickerLabel(tvPicker);     // Updates your "(X available)" placeholder label
    });
    
    moviePicker = new TomSelect('#movie_library', {
        inputTypes: [],
        controlInput: '<input readonly>',
        plugins: {
            'clear_button': {
                html: (data) => `<div class="${data.className}" title="${data.title}"><i class="bi bi-x-circle"></i></div>`
            },
            'remove_button': {}
        },
        onChange: () => updatePickerLabel(moviePicker)
    });
    moviePicker.on('clear', () => {
        moviePicker.refreshOptions(false); // Refreshes the dropdown list without closing it
        updatePickerLabel(moviePicker);     // Updates your "(X available)" placeholder label
    });

    loadConfig();
    toggleThePosterDBElements();
    toggleWebhookSettings();
    detectEnvironment();
    getScrapeState();
});

// Specific event listeners
document.getElementById("switch_bulk_file").addEventListener("change", bulkFileSwitched);
document.getElementById("switch_bulk_file").addEventListener("mousedown", loadBulkFileList);
document.getElementById("bulk_import_text").addEventListener("input", updateBulkSaveButtonState);
document.getElementById("scraper-filters-global").addEventListener("change", inheritGlobalFiltersForScraper);
document.getElementById("upload-filters-global").addEventListener("change", inheritGlobalFiltersForUploads);
document.getElementById("btnUpdate").addEventListener("click", updateApp);
document.getElementById("test_notif_btn").addEventListener("click", testNotifications);
document.getElementById("debug-mode").addEventListener("change", function() {
    socket.emit("debug_mode", { instance_id: instanceId, action: "toggle" });
});
document.getElementById("plex_token").addEventListener("change", updateLibraryPickers);
document.getElementById("plex_base_url").addEventListener("change", updateLibraryPickers);


// Automatically clear sticky hover/focus states on mobile touch devices
document.addEventListener('touchend', (e) => {
    // Don't blur if the touch target or active element is part of TomSelect
    if (e.target.closest('.ts-wrapper, .ts-dropdown')) {
        return;
    }

    const activeEl = document.activeElement;

    // Don't blur active text inputs, select dropdowns, or textareas while typing/interacting
    if (activeEl && activeEl.matches('input, textarea, select')) {
        return;
    }

    // For buttons, links, and icons: blur on touch release so :active state resets smoothly
    if (activeEl && activeEl !== document.body) {
        activeEl.blur();
    }
}, { passive: true });
// ==================================================
// General helper functions
// ==================================================

// Function to fetch and render directory contents from backend
async function loadDirectory(path = "/") {
    const folderList = document.getElementById("folder_list");
    const currentPathSpan = document.getElementById("folder_current_path");
    
    folderList.innerHTML = `<div class="p-3 text-center text-muted"><span class="spinner-border spinner-border-sm"></span> Loading...</div>`;

    try {
        // Call your backend directory browsing endpoint
        const response = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        const data = await response.json();

        currentDirectoryPath = data.current_path;
        currentPathSpan.textContent = currentDirectoryPath;
        folderList.innerHTML = "";

        if (data.folders.length === 0) {
            folderList.innerHTML = `<div class="p-3 text-center text-muted small">No subdirectories found</div>`;
            return;
        }

        data.folders.forEach(folder => {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "list-group-item list-group-item-action d-flex align-items-center gap-2 py-2 input-monospace small";
            item.innerHTML = `<i class="bi bi-folder text-primary"></i> <span>${folder.name}</span>`;
            
            item.addEventListener("click", () => {
                loadDirectory(folder.path);
            });
            folderList.appendChild(item);
        });
    } catch (err) {
        folderList.innerHTML = `<div class="p-3 text-center text-danger small">Failed to load directory</div>`;
    }
}

// Functions and listeners to query the scrape state from the backend and update the UI to reflect
// any ongoing process, including disabling buttons, adding scrapers, updating progress bars...
function getScrapeState() {
    socket.on("get_scrape_state", (data) => {
        if (data.type == "stopped") return;

        scrapeState(data.running, data.type)
        if (data.type == "bulk") {
            progressBar(data.bulk_bar.percent, data.bulk_bar.message, "bulk", data.bulk_bar.speed);
        }
        progressBar(data.main_bar.percent, data.main_bar.message, "main", data.main_bar.speed);
    });
    socket.emit("get_scrape_state", { instance_id: instanceId })
}
function scrapeState(running, type) {

    let cancelBtnId = ""
    let tabId = ""
    let btnId = ""
    if (type == "bulk") {
        cancelBtnId = "bulk-import-cancel";
        tabId = "bulk-import-tab";
        btnId = "bulk_button";
    } else if (type == "scrape") {
        cancelBtnId = "scrape-cancel";
        tabId = "scraper-tab";
        btnId = "scrape_button";
    } else if (type == "upload") {
        cancelBtnId = "upload-cancel";
        tabId = "uploader-tab";
    }
    const cancelBtnElement = document.getElementById(cancelBtnId);
    const tabElement = document.getElementById(tabId).querySelector("i");
    const btnElement = document.getElementById(btnId);

    // Shows or hides the cancel button on the appropriate tab
    cancelBtnElement.classList.toggle("d-none", !running);

    // Shows or hides the spinner on the appropriate tab
    // and disables or enables the file drop area
    if (running) {
        disableElement(["scrape_url", "scrape_button", "bulk_button"], true);
        dropArea.classList.add("disabled");

        if (!tabElement.dataset.originalIcon) {
            tabElement.dataset.originalIcon = tabElement.className;
        }
        tabElement.className = "spinner-border spinner-border-sm";
        if (btnElement) {
            if (!btnElement.querySelector("i").dataset.originalIcon) {
                btnElement.querySelector("i").dataset.originalIcon = btnElement.querySelector("i").className;
            }
            btnElement.querySelector("i").className = "spinner-border spinner-border-sm";
        }
    } else {
        disableElement(["scrape_url", "scrape_button", "bulk_button"], false);
        dropArea.classList.remove("disabled");

        tabElement.className = tabElement.dataset.originalIcon || "bi bi-gear";
        if (btnElement) {
            btnElement.querySelector("i").className = btnElement.querySelector("i").dataset.originalIcon || "bi bi-gear";
        }

        // Every run kind lands in the history now, not just bulk imports
        loadRunHistory();
    }
}
socket.on("scrape_state", (data) => {
    scrapeState(data.running, data.type)
});

// A webhook import finishes without a scrape_state change, so it says so itself
socket.on("run_history_updated", () => {
    loadRunHistory();
});



function updateLibraryPickers() {
    const baseUrl = document.getElementById("plex_base_url").value;
    const token = document.getElementById("plex_token").value;

    tvPicker.disable();
    setPickerPlaceholder(tvPicker, "No libraries available");
    moviePicker.disable();
    setPickerPlaceholder(moviePicker, "No libraries available");
        
    socket.on("get_plex_libraries", (data) => {
        if (validResponse(data)) {
            if (data.tv_libraries && data.tv_libraries.length > 0) {
                data.tv_libraries.forEach(lib => tvPicker.addOption({ value: lib, text: lib }));
                tvPicker.enable();
                tvPicker.wrapper.classList.remove("is-invalid");
            } else {
                tvPicker.clear();
                tvPicker.clearOptions();
                tvPicker.disable();
                tvPicker.wrapper.classList.add("is-invalid");
            }
            data.message ? updatePickerLabel(tvPicker, data.message) : updatePickerLabel(tvPicker);
            tvPicker.wrapper.classList.remove("loading");
            
            if (data.movie_libraries && data.movie_libraries.length > 0) {
                data.movie_libraries.forEach(lib => moviePicker.addOption({ value: lib, text: lib }));
                moviePicker.enable();
                moviePicker.wrapper.classList.remove("is-invalid");
            } else {
                moviePicker.clear();
                moviePicker.clearOptions();
                moviePicker.disable();
                moviePicker.wrapper.classList.add("is-invalid");
            }
            data.message ? updatePickerLabel(moviePicker, data.message) : updatePickerLabel(moviePicker);
            moviePicker.wrapper.classList.remove("loading");
        }
    });

    if (baseUrl && token) {
        tvPicker.disable();
        moviePicker.disable();
        tvPicker.wrapper.classList.remove("is-invalid");
        moviePicker.wrapper.classList.remove("is-invalid");
        setPickerPlaceholder(tvPicker, "Loading libraries...");
        setPickerPlaceholder(moviePicker, "Loading libraries...");
        tvPicker.wrapper.classList.add("loading");
        moviePicker.wrapper.classList.add("loading");        
        socket.emit("get_plex_libraries", { instance_id: instanceId, url: baseUrl, token: token });
    }
}

function detectEnvironment() {
    socket.emit("detect_docker", { instance_id: instanceId });
    socket.emit("debug_mode", { instance_id: instanceId, action: "get" });
    socket.emit("check_for_update", { instance_id: instanceId });
}

socket.on("version_check", function(data) {
    if(validResponse(data, true)){
        if (data.new_version) {
            // Show update notifier
            document.getElementById("latest_version").innerText = data.new_version;
            document.getElementById("version_notifier").classList.remove("d-none");
            //document.getElementById("check-update-btn").classList.add("d-none");
        }
        // Display current version in the About tab
        document.getElementById("app_version").innerText = data.current_version;
        // If running in Docker, show message about self-update being disabled and hide update button
        if (data.docker) {
            document.getElementById("docker_update_message").innerText = "Self-update is disabled in Docker. Please pull the latest image manually.";
        } else {
            document.getElementById("docker_update_message").innerText = "";
            document.getElementById("btnUpdate").classList.remove("d-none");
        }
    }
});

socket.on("debug_mode", function(data) {
    if (validResponse(data)) {
        // Set the correct state of the debug mode toggle based on the backend value
        document.getElementById("debug-mode").checked = data.debug;
    }
});

function toggleDockerWarning() {
    socket.emit("detect_docker", { instance_id: instanceId });
}
socket.on("docker_detected", (data) => {
    const dockerWarning = document.getElementById("docker_warning");
    const kometaBase = document.getElementById("kometa_base");
    const tempDir = document.getElementById("temp_dir");
    const saveToKometaCheckbox = document.getElementById("save_to_kometa");
    const optionTemp = document.getElementById("option-temp");
    const uploadOptionTemp = document.getElementById("upload-option-temp");
    
    if (validResponse(data)) {
        if (data.docker == "true") {
            docker = true;
            // If no Kometa asset directory has been bind-mounted to the container /asset path, disable the
            // ability to turn on saving to Kometa asset directory
            if (data.kometa_base == "(not defined)") {
                saveToKometaCheckbox.disabled = true;
                saveToKometaCheckbox.checked = false;
                toggleKometaSettings();
                dockerWarning.innerHTML = '<i class="bi bi-exclamation-triangle"></i>&ensp;Kometa base path not defined in <span class="text-nowrap"><code>docker-compose.yml</code></span>. Saving assets to Kometa asset directory is not available.<button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>';
                dockerWarning.classList.add("alert-danger");
                dockerWarning.classList.remove("d-none");
            }
            if (saveToKometaCheckbox.checked && !saveToKometaCheckbox.disabled) {
                dockerWarning.classList.remove("d-none");
            }
            
            // Disables path input fields, sets values to those detected by backend
            // and removes the in-line browse button
            const pathInputIds = ["kometa_base", "temp_dir"];
            pathInputIds.forEach(id => {
                const input = document.getElementById(id);
                if (input) {
                    input.disabled = true;
                    input.value = id === "kometa_base" ? data.kometa_base : data.temp_dir;
                    input.classList.remove("has-inline-btn", "pe-5");
                    const browseBtn = input.parentElement.querySelector(".browse-folder-btn");
                    if (browseBtn) {
                        browseBtn.classList.add("d-none");
                    }
                }
            });
            if (data.temp_dir == "(not defined)") {
                optionTemp.checked = false;
                optionTemp.parentElement.classList.add("d-none");
                uploadOptionTemp.checked = false;
                uploadOptionTemp.parentElement.classList.add("d-none");
            }
        } else {
            docker = false;
            dockerWarning.classList.add("d-none");
        }
    }
});

// Send test notification
function testNotifications() {

    const urls = Array.from(document.querySelectorAll(".apprise-url-input"))
        .map(input => input.value.trim())
        .filter(url => url !== "");

    if (urls.length == 0) {
        updateStatus("Set at least one notification URL", "warning", false, false, "exclamation-triangle")
    } else {
        socket.emit("test_notifications", { instance_id: instanceId, urls: urls });
    }
}

// Check incoming socket message is for this instance
function validResponse(data, allow_broadcast = false) {
    return data.instance_id === instanceId || (allow_broadcast && data.broadcast);
}


// Generate a UUID to create an instance ID in local storage
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



// ==================================================
// UI-specific helper functions
// ==================================================

function setPickerPlaceholder(instance, text) {
    if (!instance) return;
    instance.settings.placeholder = text;
    if (instance.control_input) {
        instance.control_input.placeholder = text;
    }
    instance.input.setAttribute('placeholder', text);
}

function updatePickerLabel(picker, message = '') {
    if (!picker) return;

    const totalOptions = Object.keys(picker.options).length;
    const selectedCount = picker.getValue().length;
    if (totalOptions == 0) {
        message ? setPickerPlaceholder(picker, message) : setPickerPlaceholder(picker, "No libraries available");
    } else if (selectedCount === 0) {
        setPickerPlaceholder(picker, `(${totalOptions} available)`);
    } else if (selectedCount < totalOptions) {
        const remaining = totalOptions - selectedCount;
        setPickerPlaceholder(picker, `(${remaining} left)`);
    } else {
        setPickerPlaceholder(picker, "");
    }
}

// Disable frontend elements from backend
function disableElement(element_ids, mode = true) {
    if (!element_ids) return;  // Exit if no element_ids provided

    // Ensure it's always treated as an array
    let elements = Array.isArray(element_ids) ? element_ids : [element_ids];

    // Loop through each element ID and disable/enable it
    elements.forEach(id => {
        let element = document.getElementById(id);
        if (element) {
            element.disabled = mode;
        } else {
            console.warn(`Element with ID "${id}" not found.`);
        }
    });
}
socket.on("element_disable", (data) => {
    if (validResponse(data)) {
        disableElement(data.element, data.mode);
    }
});

// Adds a spinner to a button
function addSpinner(elementId, mode = true) {
    if (!elementId) return;  // Exit if no element_ids provided

    const element = document.getElementById(elementId);

    if (!element) {
        console.warn(`Element ID with ${id} not found.`);
        return;
    }
    const icon = element.querySelector("i");

    if (mode === true) {
        if (icon) {
            if (!icon.dataset.originalClass) {
                icon.dataset.originalClass = icon.className;
            }
            icon.className = "spinner-border spinner-border-sm";
            icon.setAttribute("role", "status");
            icon.setAttribute("aria-hidden", "true");
        }
        element.disabled = true;
    } else {
        if (icon && icon.dataset.originalClass) {
            icon.className = icon.dataset.originalClass;
            icon.removeAttribute("role");
            icon.removeAttribute("aria-hidden");
        }
        element.disabled = false;
    }
}
socket.on("add_spinner", (data) => {
    if (validResponse(data)) {
        addSpinner(data.element, data.mode);
    }
});

// Update the status bar
function updateStatus(message, color = "info", sticky = false, spinner = false, icon = false, width=null) {
    const statusEl = document.getElementById("status");
    const statusContainer = document.getElementById("status_container");
    const spinnerEl = document.getElementById("status_spinner"); // Get the spinner element
    const messageEl = document.getElementById("status_message");
    const iconEl = document.getElementById("status_icon");

    if (!statusEl) return;

    if (statusContainer) {
        if (width === "modal") {
            statusContainer.style.maxWidth = "500px";
        } else if (typeof width === "string" && width.endsWith("px")) {
            statusContainer.style.maxWidth = width;
        } else {
            statusContainer.style.maxWidth = "";
        }
    }

    // Check if message has timestamp with milliseconds [00:00:00.000] to [23:59:59.999]
    const hasTimestamp = /^\[(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}\]/.test(message);

    // Remove timestamp if present
    if (hasTimestamp) {
        message = message.replace(/^\[(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}\]\s*/, '');
    }
    
    // Update the message and color
    messageEl.innerHTML = message;

    // If the passed color is not valid, default to 'info'
    const bootstrapColors = ['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'];
    if (!bootstrapColors.includes(color)) {
        color = 'info';
    }

    // Handle the spinner visibility based on the spinner argument
    if (spinnerEl) {
        if (spinner) {
            spinnerEl.classList.remove('collapse'); // Remove 'collapse' to show the spinner
        } else {
            spinnerEl.classList.add('collapse'); // Add 'collapse' to hide the spinner
        }
    }

    // Handle the icon visibility based on the icon and spinner arguments
    iconEl.classList.add('collapse'); // Add 'collapse' to hide the icon
    if (iconEl) {
        if (icon && !spinner) {
            iconEl.className = "bi-" + icon;
        }
    }

    if (spinner || icon) {
        messageEl.classList.add('ps-2'); // Add padding for the message
    } else {
        messageEl.classList.remove('ps-2'); // Remove padding for the message
    }

    statusEl.classList.forEach(className => {
        if (className.startsWith("text-bg-")) {
            statusEl.classList.remove(className);
        }
    });

    // Add the new text-bg-{color} class for the background color
    if (color) {
        statusEl.classList.add('text-bg-' + color);
    }

    // Ensure the fade class is present for transitions
    statusEl.classList.add('fade'); // Add the fade class to trigger the fade transition

    // Show the status element with fade-in effect
    statusEl.classList.add('show'); // Add show class to display the element

    // Clear any existing timeout to prevent multiple timeouts
    clearTimeout(statusTimeout);

    // Set a new timeout to hide the status element after 3 seconds
    if (!sticky) {
        statusTimeout = setTimeout(() => {
            statusEl.classList.remove('show'); // Fade out the status after 5 seconds
            setTimeout(() => {
                if (statusContainer) statusContainer.style.maxWidth = "";
            }, 150); // Reset width
        }, 5000);
    }
}
socket.on("status_update", (data) => {
    if (validResponse(data, true)) {
        updateStatus(data.message, data.color, data.sticky, data.spinner, data.icon, data.width);
    }
});

// Update the log page
function updateLog(message, color = null) {
    let statusElement = document.getElementById("scraping_log");

    // Match [00:00:00.000] to [23:59:59] at the start
    const hasTimestamp = /^\[(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\.\d{3}\]/.test(message);

    // Add timestamp if message doesn't already have one
    if (!hasTimestamp) {
        let timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });
        message = '[' + timestamp + '] ' + message;
    } else {
        // Remove timestamp milliseconds for consistency
        message = message.replace(/^\[(\d{2}:\d{2}:\d{2})\.\d{3}\]/, '[$1]');
    }

    // Prepend the new message (newest first) as a node, so we do not re-parse the entire log
    // on every line. That, plus the line cap below, stops a long scrape from growing the page
    // until the browser runs out of memory.
    const entry = document.createElement("div");
    entry.className = "log_message";
    entry.innerHTML = message;
    statusElement.prepend(entry);

    const MAX_LOG_LINES = 500;
    while (statusElement.childElementCount > MAX_LOG_LINES) {
        statusElement.removeChild(statusElement.lastElementChild);
    }
}
socket.on("log_update", (data) => {
    if (validResponse(data, true)) {
        updateLog(data.message);
    }
});


// Update the progress bars, showing and hiding as required
function progressBar(percent, message = "", barType = "main", speed = "smooth") {

    const suffix = barType === "bulk" ? "_bulk" : "_main";
    const container = document.getElementById("progress_bar_container" + suffix);
    const bar = document.getElementById("progress_bar" + suffix);
    const barTitle = document.getElementById("progress_bar_title" + suffix);
    const barPercent = document.getElementById("progress_bar_percent" + suffix);

    if (!container || !bar) return;

    percent = Math.min(Math.max(percent, 0), 100);

    container.classList.add("show");

    if (barTimer) clearTimeout(barTimer);

    if (barTitle) barTitle.innerText = message;
    if (barPercent) barPercent.innerText = Math.round(percent) + "%";

    const currentPercent = parseFloat(bar.style.width) || 0;

    if (speed == "fast") transition = "none";
    else transition = "width 0.5s ease";

    if (percent < currentPercent) {
        bar.style.transition = "none";
        void bar.offsetWidth;
        bar.style.width = percent + "%";
        void bar.offsetHeight;
    } else {
        bar.style.transition = transition;
        bar.style.width = percent + "%";
    }

    if (percent === 100) {
        barTimer = setTimeout(() => {
            // Hide both containers
            document.getElementById("progress_bar_container_main").classList.remove("show");
            document.getElementById("progress_bar_container_bulk").classList.remove("show");
            document.getElementById("progress_bar_main").style.width = "0%";
            document.getElementById("progress_bar_bulk").style.width = "0%";
        }, 2000);
    }
}
socket.on("progress_bar", (data) => {
    if (validResponse(data, true)) {
        progressBar(data.percent, data.message, data.bar_type, data.bar_speed)
    }
})


// Add scraped URL to the bulk list, label and sort it
socket.on("add_to_bulk_list", (data) => {

    if (validResponse(data)) {

        let bulkText = document.getElementById("bulk_import_text").value;
        let urlWithoutFlag = data.url.split(' ')[0]; // Extract base URL

        // Remove the --add-to-bulk flag from the original data.url because we don't want that added to the bulk file!
        let cleanedUrl = data.url.replace(/\s+--add-to-bulk\b/, "").trim();

        // Escape special regex characters in URL for proper matching
        let escapedUrl = urlWithoutFlag.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // Regex to match the URL as a standalone line with optional extra arguments
        let regex = new RegExp(`^${escapedUrl}(\\s+--\\S+(\\s+\\S+)*)?$`, "m")

        if (!regex.test(bulkText)) {
            if (config.auto_manage_bulk_files) {
                document.getElementById("bulk_import_text").value = processAndSortUrls(bulkText, data.title, data.author, cleanedUrl);
            } else {
                document.getElementById("bulk_import_text").value += `\n// ${data.title} | ${data.author}\n${cleanedUrl}\n`;
            }

        }

        updateBulkSaveButtonState();
    }

});


// Sort the bulk list into order by media title
function processAndSortUrls(inputText, newTitle, newAuthor, newUrl) {

  // Initialize data structures
  const titleMap = {};
  const mediUXUrls = [];
  const thePosterDBUrls = [];

  // Function to remove leading articles from a title
  const removeLeadingArticles = (title) => {
    const articles = ['a', 'an', 'the'];
    const words = title.toLowerCase().split(' ');
    if (words.length > 1 && articles.includes(words[0])) {
      words.shift(); // Remove the leading article
    }
    return words.join(' ');
  };

  // Function to add a new title and its URL
  const addTitleAndUrl = (title, url) => {
    if (title && url) {
      titleMap[title] = titleMap[title] || [];
      titleMap[title].push(url);
    }
  };

  // Split the input data into lines
  const lines = inputText.split('\n');
  let currentTitle = '';

  // Process each line
  lines.forEach(line => {
    line = line.trim();
    if (line.startsWith('//')) {
      // New title
      currentTitle = line.substring(3).trim();
      titleMap[currentTitle] = [];
    } else if (line === '') {
      // Blank line
      currentTitle = '';
    } else if (line) {
      // URL line
      if (currentTitle) {
        // Associated with a title
        titleMap[currentTitle].push(line);
      } else {
        // Standalone URL
        if (line.includes('mediux.pro')) {
          mediUXUrls.push(line);
        } else if (line.includes('theposterdb.com')) {
          thePosterDBUrls.push(line);
        }
      }
    }
  });

  // Add the new title and URL
  newTitle = newTitle + ' | ' + newAuthor
  addTitleAndUrl(newTitle, newUrl);

  // Format the output
  let output = '';
  // Sort titles alphabetically, ignoring leading articles
  const sortedTitles = Object.keys(titleMap).sort((a, b) => {
    const aTitle = removeLeadingArticles(a);
    const bTitle = removeLeadingArticles(b);
    return aTitle.localeCompare(bTitle);
  });
  // Add title sections
  sortedTitles.forEach(title => {
    output += `// ${title}\n`;
    titleMap[title].forEach(url => {
      output += `${url}\n`;
    });
    output += '\n';
  });
  // Add MediUX URLs section
  if (mediUXUrls.length > 0) {
    output += '// MediUX URLs\n';
    mediUXUrls.forEach(url => {
      output += `${url}\n`;
    });
    output += '\n';
  }
  // Add The Poster DB URLs section
  if (thePosterDBUrls.length > 0) {
    output += '// The Poster DB URLs\n';
    thePosterDBUrls.forEach(url => {
      output += `${url}\n`;
    });
    output += '\n';
  }

  return output;
}


// ==================================================
// Configuration - load and save
// ==================================================

// Button handler for save configuration
document.getElementById("save_config_button").addEventListener("click", async function(event) {
    event.preventDefault(); // Prevent actual form submission
    const form = document.getElementById("config_form");
    if (!form.checkValidity()) {
        form.classList.add("was-validated");
        return; // Prevent further execution if form is invalid
    }
    // Form is valid: make sure highlights are cleared if user successfully saves
    const tvLibraries = tvPicker ? tvPicker.getValue() : [];
    const movieLibraries = moviePicker ? moviePicker.getValue() : [];

    if (tvLibraries.length + movieLibraries.length > 0) {
        form.classList.remove("was-validated");
        saveConfig();
    } else {
        updateStatus("Select at least one show or movie library", "danger", false, false, "x-circle");
    }
});


function getCanonicalConfig(config) {
    const result = {};

    Object.keys(config).sort().forEach(key => {
        // Omit the "schedules" key since bulk import schedules are
        // managed by the Bulk Import tab and not in the Settings tab
        if (key === "schedules") return;

        if (Array.isArray(config[key])) {
            // Sort lists so that list order changes don't trigger a config 
            // changed state where the buttons get enabled unnecessarily
            result[key] = [...config[key]].sort()
        } else {
            result[key] = config[key]
        }
    });

    return result;
}

function getCurrentConfigForm() {
    const current_form = {};

    current_form.base_url = document.getElementById("plex_base_url").value.trim();
    current_form.token = document.getElementById("plex_token").value.trim();
    current_form.kometa_base = document.getElementById("kometa_base").value.trim();
    current_form.temp_dir = document.getElementById("temp_dir").value.trim();
    current_form.bulk_txt = document.getElementById("bulk_import_file").value;
    
    // Save the Apprise notification channels (URL plus the events each one is subscribed to)
    current_form.apprise_urls = collectAppriseChannels();

    // Collect movie and TV library lists from TomSelect pickers
    current_form.tv_library = tvPicker ? tvPicker.getValue() : [];
    current_form.movie_library = moviePicker ? moviePicker.getValue() : [];

    // Checkbox for tracking artwork IDs
    current_form.track_artwork_ids = document.getElementById("track_artwork_ids").checked;

    // Checkbox for saving artwork to Kometa asset directory
    current_form.save_to_kometa = document.getElementById("save_to_kometa").checked;

    // Checkbox for staging assets
    current_form.stage_assets = document.getElementById("stage_assets").checked;

    // Checkbox for managing bulk files
    current_form.auto_manage_bulk_files = document.getElementById("auto_manage_bulk_files").checked;

    // Checkbox for reset overlay for Kometa
    current_form.reset_overlay = document.getElementById("reset_overlay").checked;

    // Checkbox for skipping artwork with locked fields in Plex
    current_form.skip_locked_artwork = document.getElementById("skip_locked_artwork").checked;

    // Checkbox for matching artwork against the local libraries before fetching poster pages
    current_form.local_library_matching = document.getElementById("local_library_matching").checked;
    
    // Checkbox for caching ThePosterDB user scrapes
    current_form.cache_user_scrapes = document.getElementById("cache_user_scrapes").checked;

    // ThePosterDB user cache expiration threshold
    current_form.user_cache_refresh_days = parseInt(document.getElementById("user_cache_refresh_days").value) || 0;

    // Timeouts and retries
    current_form.plex_connect_timeout = parseInt(document.getElementById("plex_connect_timeout").value) || 10;
    current_form.kometa_download_timeout = parseInt(document.getElementById("kometa_download_timeout").value) || 10;
    current_form.upload_retry_attempts = parseInt(document.getElementById("upload_retry_attempts").value) || 3;
    current_form.upload_retry_backoff_seconds = parseFloat(document.getElementById("upload_retry_backoff_seconds").value) || 1;

    // How late a missed scheduled run can be and still be caught up on startup
    current_form.catch_up_window_minutes = parseInt(document.getElementById("catch_up_window_minutes").value) || 0;

    // Checkbox for taking an artist's newer artwork for posters we applied
    current_form.allow_artist_updates = document.getElementById("allow_artist_updates").checked;

    // Get selected mediux filters
    current_form.mediux_filters = Array.from(document.querySelectorAll('[id^="m_filter-"]:checked'))
        .map(checkbox => checkbox.value);

    // Get selected tpdb filters
    current_form.tpdb_filters = Array.from(document.querySelectorAll('[id^="p_filter-"]:checked'))
        .map(checkbox => checkbox.value);

    // Save schedules (Ensure it's an array)
    current_form.schedules = Array.isArray(schedules) ? schedules : [];

    // Authentication settings
    current_form.auth_enabled = document.getElementById("auth_enabled").checked;
    current_form.auth_username = document.getElementById("auth_username").value.trim();
    current_form.auth_password = document.getElementById("auth_password").value;

    // Webhook settings
    current_form.enable_webhooks = document.getElementById("enable_webhooks").checked;
    current_form.webhook_token = document.getElementById("webhook_token").value.trim();
    current_form.webhook_tpdb_users = tpdbUserPicker ? tpdbUserPicker.getValue() : [];
    current_form.webhook_apply_delay = parseInt(document.getElementById("webhook_apply_delay").value, 10) || 30;

    return current_form
}

// Save configuration
function saveConfig() {
    const save_config = getCurrentConfigForm();

    // Process every possible condition of auth enable/disable and same/different username and password/no password provided
    // If auth is enabled and a password is NOT provided
    if (save_config.auth_enabled && !save_config.auth_password) {
        // If the username provided is the same, proceed saving the configuration
        if (save_config.auth_username === config.auth_username) {
            socket.emit("save_config", { instance_id: instanceId, config: save_config });
        // If the username has changed and a password is not provided, don't proceed
        } else if (save_config.auth_enabled != config.auth_username) {
            updateStatus("Password must be provided when changing authentication account", "danger", false, false, "x-circle");
        // Proceed saving the configuration with a new username/password combination
        } else {
            socket.emit("display_message", { "instance_id": instanceId, "message": "Changing username and providing password", "level": "log"});
            socket.emit("save_config", { instance_id: instanceId, config: save_config });
        }
    } else if (save_config.auth_enabled && save_config.auth_password) {
        // Clear the password fill and save the config
        document.getElementById("auth_password").value = ""
        socket.emit("save_config", { instance_id: instanceId, config: save_config })
    } else {
        // If the auth cehckbox is off, proceed to disable authentication
        document.getElementById("auth_username").value = ""
        socket.emit("save_config", { instance_id: instanceId, config: save_config });
    }

    // Prevent duplicate event listeners
    socket.once("save_config", (data) => {
        if (validResponse(data, true)) {
            if (data.saved) {
                config = data.config;
                socket.emit("display_message", {
                    level: "status",
                    instance_id: instanceId,
                    message: "Configuration updated",
                    color: "success",
                    icon: "check2-circle",
                    broadcast: true
                });
                configureTabs(true);
                initialConfig = JSON.stringify(getCanonicalConfig(getCurrentConfigForm()));
                toggleConfigButtons();
            } else {
                updateStatus("Configuration could not be saved", "danger", false, false, "x-circle");
                configureTabs(true);
            }
        }
    });
}

socket.on("update_ui", (data) => {
    if (validResponse(data, true)) {
        updateConfigUI(data.config);
    }
});

socket.on("toggle_config_buttons", () => {
    toggleConfigButtons();
});


function updateConfigUI(config) {

    document.getElementById("plex_base_url").value = config.base_url;
    document.getElementById("plex_token").value = config.token;
    document.getElementById("bulk_import_file").value = config.bulk_txt;
    
    // Load TV libraries
    if (Array.isArray(config.tv_library)) {
        // Add options first so Tom Select knows about them
        config.tv_library.forEach(lib => tvPicker.addOption({ value: lib, text: lib }));
        // Set active values (chips)
        tvPicker.setValue(config.tv_library);
    }
    // Load Movie Libraries
    if (Array.isArray(config.movie_library)) {
        // Add options first
        config.movie_library.forEach(lib => moviePicker.addOption({ value: lib, text: lib }));
        // Set active values (chips)
        moviePicker.setValue(config.movie_library);
    }            
    updateLibraryPickers();
    
    document.getElementById("track_artwork_ids").checked = config.track_artwork_ids;
    document.getElementById("save_to_kometa").checked = config.save_to_kometa;
    document.getElementById("stage_assets").checked = config.stage_assets;
    document.getElementById("kometa_base").value = config.kometa_base;
    document.getElementById("temp_dir").value = config.temp_dir || "";
    document.getElementById("auto_manage_bulk_files").checked = config.auto_manage_bulk_files;
    document.getElementById("reset_overlay").checked = config.reset_overlay;
    document.getElementById("skip_locked_artwork").checked = config.skip_locked_artwork;
    document.getElementById("local_library_matching").checked = config.local_library_matching;
    document.getElementById("cache_user_scrapes").checked = config.cache_user_scrapes;
    document.getElementById("user_cache_refresh_days").value = config.user_cache_refresh_days ?? 7;
    document.getElementById("plex_connect_timeout").value = config.plex_connect_timeout ?? 10;
    document.getElementById("kometa_download_timeout").value = config.kometa_download_timeout ?? 10;
    document.getElementById("upload_retry_attempts").value = config.upload_retry_attempts ?? 3;
    document.getElementById("upload_retry_backoff_seconds").value = config.upload_retry_backoff_seconds ?? 1;
    document.getElementById("catch_up_window_minutes").value = config.catch_up_window_minutes ?? 0;
    document.getElementById("allow_artist_updates").checked = config.allow_artist_updates;
    document.getElementById("option-add-to-bulk").checked = config.auto_manage_bulk_files;
    
    // Populate Apprise URLs
    const container = document.getElementById("apprise_urls_container");
    if (container) {
        container.innerHTML = "";
        
        if (Array.isArray(config.apprise_urls) && config.apprise_urls.length > 0) {
            const numUrls = config.apprise_urls.length
            let thisUrl = 0
            config.apprise_urls.forEach(url => {
                thisUrl += 1
                if (thisUrl < numUrls) {
                    createAppriseUrlRow(url);
                } else {
                    createAppriseUrlRow(url, last=true);
                }
            });
        } else {
            createAppriseUrlRow();
        }
    }
    
    // Load authentication settings
    document.getElementById("auth_enabled").checked = config.auth_enabled || false;
    document.getElementById("auth_username").value = config.auth_username || "";
    
    // Load webhook settings
    document.getElementById("enable_webhooks").checked = config.enable_webhooks || false;
    document.getElementById("webhook_token").value = config.webhook_token || "";
    if (Array.isArray(config.webhook_tpdb_users) && tpdbUserPicker) {
        // Clear existing options
        tpdbUserPicker.clearOptions();
        // Add options first
        config.webhook_tpdb_users.forEach(user => tpdbUserPicker.addOption({ value: user, text: user }));
        // Set active values (chips)
        tpdbUserPicker.setValue(config.webhook_tpdb_users, true);
    };
    document.getElementById("webhook_apply_delay").value = config.webhook_apply_delay ?? 30;
    
    // Toggle Kometa settings visibility
    toggleKometaSettings();
    
    // Toggle Add to Bulk checkbox visibility
    toggleAddToBulkCheckbox();
    
    // Toggle auth settings visibility
    toggleAuthSettings();
    
    // Toggle webhook settings visibility
    toggleWebhookSettings();
    
    // Make sure Plex options visibility is set correctly on load
    togglePlexOptions();
    
    // Make sure temp option visibility is set correctly on load
    toggleTempCheckbox();
    
    // Make sure scraper stage option visibility is set correctly on load
    toggleScraperStageCheckbox();
    
    // Make sure skip locked artwork option visibility is set correctly on load
    toggleSkipLockedCheckbox();

    // Make sure user asset cache expiry field visibility is seet correctly on load
    toggleUserCacheExpiryField();
    
    // Show/hide logout button based on auth enabled
    if (config.auth_enabled) {
        document.getElementById("logout-link").style.display = "block";
    } else {
        document.getElementById("logout-link").style.display = "none";
    }
    
    if (Array.isArray(config.mediux_filters)) {
        document.querySelectorAll('[id^="m_filter-"]').forEach(checkbox => {
            checkbox.checked = config.mediux_filters.includes(checkbox.value);
        });
    }
    
    if (Array.isArray(config.tpdb_filters)) {
        document.querySelectorAll('[id^="p_filter-"]').forEach(checkbox => {
            checkbox.checked = config.tpdb_filters.includes(checkbox.value);
        });
    }
    
    schedules = config.schedules;
    
    loadBulkFileList(); // For the switcher
    loadRunHistory();
};

// Load configuration
function loadConfig(silent=false, restore=false) {
    socket.emit("load_config", { instance_id: instanceId });

    socket.once("load_config", (data) => { // Use 'once' to prevent duplicate listeners
        if (validResponse(data) && data.config) {
            config = data.config;
            updateConfigUI(config)
            configureTabs(silent);
            initialConfig = JSON.stringify(getCanonicalConfig(getCurrentConfigForm()));
            document.getElementById("config_form").addEventListener("change", toggleConfigButtons);
            document.getElementById("config_form").querySelectorAll(".form-control").forEach(element => {
                element.addEventListener("input", toggleConfigButtons);
            });
            toggleConfigButtons();
            if (restore) {
                updateStatus("Configuration restored successfully", "success", false, false, "check2-circle");
                const passwordField = document.getElementById("auth_password");
                if (passwordField) passwordField.value = '';
            }
        }
    });
}

function toggleConfigButtons() {
    const currentConfig = JSON.stringify(getCanonicalConfig(getCurrentConfigForm()));

    if (currentConfig === initialConfig) {
        disableElement(["save_config_button", "restore_config"], true);
    } else {
        disableElement(["save_config_button", "restore_config"], false);

    }
}

// ==================================================
// Switch the bulk import file to use
// ==================================================

function saveBulkChangesModal(filename) {
    return new Promise((resolve) => {
        const modalElement = document.getElementById("yesNoCancelModal");

        // Update modal message and title
        document.getElementById("yesNoCancelModalLabel").innerText = "Before you load " + filename;
        document.getElementById("yesNoCancelModalMessage").innerText = "Do you want to save changes to " + currentBulkImport + " first?";

        // Update buttons with choices
        document.getElementById("yesButton").innerHTML = '<i class="bi bi-floppy2"></i>&ensp;Save&nbsp;'
        document.getElementById("noButton").innerHTML = '<i class="bi bi-trash3"></i>&ensp;Discard&nbsp;'
        document.getElementById("cancelButton").innerHTML = '<i class="bi bi-x-circle"></i>&ensp;Cancel&nbsp;'

        // Show modal
        const modal = new bootstrap.Modal(modalElement);
        modal.show();

        // Handle button clicks
        document.getElementById("yesButton").onclick = () => {
            modal.hide();
            resolve("yes");
        };

        // Handle button clicks
        document.getElementById("noButton").onclick = () => {
            modal.hide();
            resolve("no");
        };

        document.getElementById("cancelButton").onclick = () => {
            modal.hide();
            resolve("cancel");
        };
    });
}

function startScrape() {
    var form = document.getElementById('scraperForm');

    // Check if the form is valid
    if (form.checkValidity()) {
        form.classList.remove('was-validated');
        // Proceed with scraping if form is valid

        // Collect checked input fields with ids starting with "option-"
        let options = [];
        document.querySelectorAll('[id^="option-"]:checked').forEach(checkbox => {
            options.push(checkbox.value);
        });

        // Collect checked checkboxes with ids starting with "filter-"
        let filters = [];
        if(!document.getElementById("scraper-filters-global").checked) {
            document.querySelectorAll('[id^="filter-"]:checked').forEach(checkbox => {
                filters.push(checkbox.value);
            });
        }

        const year = document.getElementById("year").value;
        const url = document.getElementById("scrape_url").value;
        socket.emit("start_scrape", { url: url, year: year, options: options, filters: filters, instance_id: instanceId });
    } else {
        // Trigger Bootstrap validation styles
        form.classList.add('was-validated');
    }
}

function stopScrape() {
    socket.emit("display_message", {
        instance_id: instanceId,
        message: "Cancelation requested by user, please wait...",
        color: "danger",
        sticky: true,
        spinner: true,
        level: "status",
        broadcast: true
    });
    socket.emit("stop_scrape", { instance_id: instanceId });
}

// Function to check for changes and enable/disable the save button
function updateBulkSaveButtonState() {

    const bulkTextArea = document.getElementById("bulk_import_text");
    const saveButton = document.getElementById("save_bulk_button");

    if (bulkTextArea.value !== bulkTextAsLoaded) {
        saveButton.disabled = false; // Enable button if text has changed
        saveButton.classList.add("btn-success");
        saveButton.classList.remove("btn-secondary");
    } else {
        saveButton.disabled = true;  // Disable button if no changes
        saveButton.classList.remove("btn-success");
        saveButton.classList.add("btn-secondary");
    }
}

// Attach event listener to track changes

// ==================================================
// ThePosterDB Options
// ==================================================

function toggleThePosterDBElements() {
        const urlInput = document.getElementById("scrape_url");
        if (!urlInput) return;

        const url = urlInput.value;
        const elements = document.querySelectorAll(".theposterdb");
        const filts = document.querySelectorAll('[id^="tpdb-"');

        // Define the regex pattern from the input
        const pattern = /^https:\/\/theposterdb\.com\/set\/\d+$/;

        // Validate the URL before showing elements
        if (pattern.test(url)) {
            elements.forEach(el => el.style.display = "block");
            filts.forEach(filt => filt.style.display = "none");
        } else {
            elements.forEach(el => {
                el.style.display = "none";
                // Uncheck checkboxes inside hidden elements
                el.querySelectorAll("input[type='checkbox']").forEach(checkbox => {
                    checkbox.checked = false;
                });
            });
            filts.forEach(filt => filt.style.display = "block");
        }

    }

// Run function on input change
if (scrapeUrlInput) {
    scrapeUrlInput.addEventListener("input", toggleThePosterDBElements);
}

function configureTabs(afterSave = false) {
        document.getElementById('scraping-log-tab').classList.add("show");
        document.getElementById('run-history-tab').classList.add("show");
        document.getElementById('about-tab').classList.add("show");
        if (config.base_url && config.token) {
            document.getElementById('bulk-import-tab').classList.add("show");
            document.getElementById('scraper-tab').classList.add("show");
            document.getElementById('uploader-tab').classList.add("show");
            if (!afterSave) {
                document.getElementById('config').classList.remove("show","active");
                document.getElementById('config-tab').classList.remove("active");
                document.getElementById('scraper').classList.add("show","active");
                document.getElementById('scraper-tab').classList.add("active");
            }
        }
}

/* Loading the bulk import file */

function loadBulkFile(bulkImport = null) {

    if (!bulkImport) {bulkImport = config.bulk_txt;}

    socket.emit("load_bulk_import", { instance_id: instanceId, filename: bulkImport });

    socket.once("load_bulk_import", (data) => {

        const textArea = document.getElementById("bulk_import_text");

        if(validResponse(data)) {

                if (data.loaded) {
                    textArea.value = data.bulk_import_text;
                    currentBulkImport = data.filename;
                    bulkTextAsLoaded = data.bulk_import_text;

                    // Select the correct option in the dropdown
                    const selectElement = document.getElementById("switch_bulk_file");
                    for (const option of selectElement.options) {
                        if (option.value === data.filename) {
                            option.selected = true;
                            break;
                        }
                    }

                    updateBulkSaveButtonState();
                    handleDefaultCheckbox();
                    updateSchedulerIcon();
                } else {
                    updateStatus("Bulk import file could not be loaded","danger", false, false, "x-circle")
                }


        }
    });

}

function checkBulkImportFileToSave() {

    saveBulkImport(currentBulkImport);

}

/* Loading the list of available bulk files */

function loadBulkFileList() {

    socket.emit("load_bulk_filelist", { instance_id: instanceId });

    socket.once("load_bulk_filelist", (data) => {
        if (validResponse(data)) {
            const selectElement = document.getElementById("switch_bulk_file");

            let selectedFile = currentBulkImport || config.bulk_txt; // Get the selected file from config

            // Clear existing options
            selectElement.innerHTML = "";

            if (data.bulk_files.length > 0) {
                // Populate the dropdown with filenames
                data.bulk_files.forEach((filename) => {
                    const option = document.createElement("option");
                    option.value = filename;
                    option.textContent = filename;

                    // Preselect the option if it matches the config.bulk_txt value
                    if (filename === selectedFile) {
                        option.selected = true;
                        if (!document.getElementById("bulk_import_text").value) {
                            loadBulkFile(filename);
                        }
                    }
                    selectElement.appendChild(option);
                });

                // Check if the selected file is the default file and update the checkbox icon
                const defaultCheckbox = document.getElementById("default_bulk_file_icon");
                if (selectedFile === document.getElementById("bulk_import_file").value) {
                    // Set the icon to filled if the selected file is the default
                    defaultCheckbox.classList.remove("bi-check-circle");
                    defaultCheckbox.classList.add("link-primary");
                    defaultCheckbox.classList.add("bi-check-circle-fill");
                    defaultCheckbox.classList.add("disabled");
                } else {
                    // Otherwise, set the icon to unfilled
                    defaultCheckbox.classList.remove("link-primary");
                    defaultCheckbox.classList.remove("bi-check-circle-fill");
                    defaultCheckbox.classList.add("bi-check-circle");
                    defaultCheckbox.classList.remove("disabled");
                }
            } else {
                // Show placeholder when no files exist
                const placeholder = document.createElement("option");
                placeholder.disabled = true;
                placeholder.selected = true;
                placeholder.value = "bulk_import.txt";
                placeholder.textContent = "Will create bulk_import.txt when saved";
                selectElement.appendChild(placeholder);
            }
        }
    });
}

/* Loading the run history */

const RUN_HISTORY_OUTCOME_LABELS = {
    success: { text: "Completed", className: "text-success", icon: "check-circle-fill", iconColor: "success" },
    partial: { text: "Completed with errors", className: "text-warning", icon: "exclamation-circle-fill", iconColor: "warning" },
    stopped: { text: "Stopped", className: "text-warning", icon: "stop-circle-fill", iconColor: "orange" },
    failed: { text: "Failed", className: "text-danger", icon: "x-circle-fill", iconColor: "danger" },
    skipped: { text: "Skipped", className: "text-muted", icon: "fast-forward-circle-fill", iconColor: "info" }
};

const RUN_HISTORY_TYPE_LABELS = {
    bulk: "Bulk import",
    scrape: "Scrape",
    upload: "Upload",
    webhook: "Webhook"
};

const RUN_HISTORY_TRIGGER_LABELS = {
    manual: "Manual",
    scheduled: "Scheduled",
    cli: "Command line",
    radarr: "Radarr",
    sonarr: "Sonarr"
};

function formatRunDuration(startedAt, endedAt) {
    const start = new Date(startedAt);
    const end = new Date(endedAt);
    const seconds = Math.max(0, Math.round((end - start) / 1000));
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    return minutes > 0 ? `${minutes}m ${remainder}s` : `${remainder}s`;
}

document.addEventListener("DOMContentLoaded", () => {
    const typeFilter = document.getElementById("run_history_type");
    if (typeFilter) {
        typeFilter.addEventListener("change", loadRunHistory);
    }
});

function loadRunHistory() {

    const typeFilter = document.getElementById("run_history_type");
    const runType = typeFilter ? typeFilter.value : "";

    socket.emit("load_run_history", { instance_id: instanceId, run_type: runType });

    socket.once("load_run_history", (data) => {
        if (!validResponse(data)) { return; }

        const body = document.getElementById("run_history_body");
        body.innerHTML = "";

        const runs = data.runs || [];

        if (runs.length === 0) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");
            cell.colSpan = 11;
            cell.className = "text-muted";
            cell.textContent = runType ? "No runs of this type recorded yet." : "No runs recorded yet.";
            row.appendChild(cell);
            body.appendChild(row);
            return;
        }

        runs.forEach((run) => {
            const row = document.createElement("tr");
            const outcome = RUN_HISTORY_OUTCOME_LABELS[run.outcome] || { text: run.outcome, className: "" };

            const cells = [
                new Date(run.started_at).toLocaleString(),
                RUN_HISTORY_TYPE_LABELS[run.run_type] || run.run_type,
                run.label,
                RUN_HISTORY_TRIGGER_LABELS[run.trigger] || run.trigger,
                outcome.text,
                run.assets_processed,
                run.success_count,
                run.cached_count,
                run.locked_count,
                run.error_count,
                formatRunDuration(run.started_at, run.ended_at)
            ];

            // Indexes match the header row: detail columns collapse on narrow screens
            const narrowHidden = [3, 5, 6, 7, 8, 10];
            cells.forEach((value, index) => {
                const cell = document.createElement("td");
                cell.textContent = value;
                if (index === 4) { cell.className = outcome.className; }
                if (narrowHidden.includes(index)) { cell.classList.add("d-none", "d-md-table-cell"); }
                row.appendChild(cell);
            });

            body.appendChild(row);
        });
    });
}

function saveBulkImport(filename, nowLoad = null) {

    const textArea = document.getElementById("bulk_import_text");

    const fileData = {
        filename: filename,
        content: textArea.value,
        now_load: nowLoad,
        instance_id: instanceId
    };

    // Emit the event to Flask via Socket.IO
    socket.emit("save_bulk_import", fileData);

    // And wait for a response
    socket.once("save_bulk_import", data => {
        if (validResponse(data)) {
            if (data.saved == true) {
                loadBulkFileList();
                bulkTextAsLoaded = textArea.value
                updateBulkSaveButtonState()
                if (data.now_load) {
                    loadBulkFile(data.now_load);
                }
            }
        }
    });
}

function runBulkImport() {
    socket.emit("start_bulk_import",{
        instance_id: instanceId,
        bulk_list: document.getElementById("bulk_import_text").value,
        filename: currentBulkImport || document.getElementById("switch_bulk_file").value || "bulk_import.txt",
        notify: document.getElementById("bulk_notify").checked
    });
}

// Validation

(function () {
    'use strict';
    // Fetch all forms we want to apply custom Bootstrap validation styles to
    var forms = document.querySelectorAll('.needs-validation');

    // Loop over them and prevent submission if invalid
    Array.prototype.slice.call(forms)
        .forEach(function (form) {
        form.addEventListener('submit', function (event) {
            if (!form.checkValidity()) {
                event.preventDefault();
                event.stopPropagation();
            }
            form.classList.add('was-validated');
        }, false);
    });
})();

/* =============================================
   Bulk file handling rename, delete, uploading
   ============================================*/

// Set up variables

function bulkFileSwitched() {

    const selectedFile = bulkFileSwitcher.value;
    if (!selectedFile) return; // Do nothing if no file is selected

    const bulkTextArea = document.getElementById("bulk_import_text");

    if (bulkTextArea.value !== bulkTextAsLoaded) {
        // If content has changed, show the modal
        saveBulkChangesModal(selectedFile).then((confirmed) => {
            if (confirmed === "yes") {
                saveBulkImport(currentBulkImport, selectedFile);
            } else if (confirmed === "no") {
                loadBulkFile(selectedFile);
            } else if (confirmed === "cancel") {
                // User canceled, revert to previous selection
                this.value = currentBulkImport;
                handleDefaultCheckbox()
            }
        });
    } else {
        // If no changes, just load the new file
        loadBulkFile(selectedFile);
    }

}

function inheritGlobalFiltersForScraper() {
    if (document.getElementById("scraper-filters-global").checked) {
        document.getElementById("scraper-filters").classList.remove("show");
    } else {
        // If the "As set by global filters" checkbox is turned off, turn off each individual filter checkbox
        document.querySelectorAll('[id^="filter-"]:checked').forEach(checkbox => {
            checkbox.checked = false;
        });
        document.getElementById("scraper-filters").classList.add("show");
    }
}

function inheritGlobalFiltersForUploads() {
    if (document.getElementById("upload-filters-global").checked) {
        document.getElementById("upload-filters").classList.remove("show");
    } else {
        // If the "As set by global filters" checkbox is turned off, turn off each individual filter checkbox
        document.querySelectorAll('[id^=upload-filter-]:checked').forEach(checkbox => {
            checkbox.checked = false;
        });        
        document.getElementById("upload-filters").classList.add("show");
    }
}

function handleDefaultCheckbox() {
    // Handle default checkbox when the file is selected
    const bulkImportFileField = document.getElementById("bulk_import_file");
    const defaultCheckbox = document.getElementById("default_bulk_file");
    const defaultIcon = document.getElementById("default_bulk_file_icon");
    const selectedFile = document.getElementById("switch_bulk_file").value;

    // Update the default checkbox and icon based on the selected file
    if (selectedFile === bulkImportFileField.value) {
        defaultCheckbox.checked = true;
        defaultIcon.classList.add("link-primary");
        defaultIcon.classList.remove("bi-check-circle");
        defaultIcon.classList.add("bi-check-circle-fill");
        defaultIcon.classList.add("disabled"); // Disable the icon

    } else {
        defaultCheckbox.checked = false;
        defaultIcon.classList.remove("link-primary");
        defaultIcon.classList.remove("bi-check-circle-fill");
        defaultIcon.classList.add("bi-check-circle");
        defaultIcon.classList.remove("disabled"); // Enable the icon
    }
}

// Function to handle renaming the bulk file
document.getElementById("rename_icon").addEventListener("click", function () {
    const selectElement = document.getElementById("switch_bulk_file");
    const filename = selectElement.value;

    if (filename) {
        // Hide the select and display the text box for renaming
        selectElement.classList.add("d-none");

        // Create a text input for renaming
        const renameInputGroup = document.createElement("div");
        renameInputGroup.classList.add("input-group", "me-3");
        const renameInput = document.createElement("input");
        renameInput.type = "text";
        renameInput.id = "rename_input";
        renameInput.value = filename.slice(0, -4);  // Strip .txt for editing
        renameInput.classList.add("form-control");

        const suffixText = document.createElement("span");
        suffixText.classList.add("input-group-text", "text-muted");
        suffixText.textContent = ".txt";

        renameInputGroup.appendChild(renameInput);
        renameInputGroup.appendChild(suffixText);

        // Insert the rename input group
        selectElement.parentNode.insertBefore(renameInputGroup, selectElement.nextSibling);

        // Add Cancel X button
        const cancelButton = document.createElement("button");
        cancelButton.innerHTML = '<i class="bi bi-x-circle h4 text-danger"></i>';
        cancelButton.classList.add("btn", "btn-link", "ms-2");

        // Append the cancel button next to the input
        renameInputGroup.appendChild(cancelButton);

        cancelButton.addEventListener("click", function () {
            renameInputGroup.remove(); // Remove the input box
            cancelButton.remove(); // Remove the cancel button
            selectElement.classList.remove("d-none"); // Show the select box again
            selectElement.value = filename; // Restore the original value
        });

        // Focus the input field and set the cursor to the end of the text
        renameInput.focus();
        renameInput.setSelectionRange(renameInput.value.length, renameInput.value.length);  // Set the cursor at the end of the text

        renameInput.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {  // Check if the pressed key is Enter
                event.preventDefault();  // Prevent the default behavior (e.g., form submission)
                renameInput.blur();  // Manually trigger the blur event
            }
        });

        renameInput.addEventListener("blur", function () {

            const newFilename = renameInput.value + ".txt"; // Ensure .txt is appended
            if (newFilename && newFilename !== filename) {
                // Emit rename event
                socket.emit("rename_bulk_file", {
                    instance_id: instanceId,
                    old_filename: filename,
                    new_filename: newFilename
                });

                // Wait for response
                socket.once("rename_bulk_file", (data) => {
                    if (validResponse(data)) {
                        if (data.renamed) {

                            // Set the currently loaded file
                            currentBulkImport = data.new_filename

                            // Carry any schedules over to the new filename
                            schedules.forEach(s => {
                                if (s.file === data.old_filename) {
                                    s.file = data.new_filename;
                                }
                            });
                            updateSchedulerIcon();

                            // If the renamed file is the default, update the config
                            const bulkImportFileField = document.getElementById("bulk_import_file");
                            const selectElement = document.getElementById("switch_bulk_file");
                            if (bulkImportFileField.value === filename) {
                                bulkImportFileField.value = data.new_filename; // Update the hidden field
                            }

                            // Update the file list if renamed
                            loadBulkFileList();

                            // Now restore the select box
                            renameInputGroup.remove(); // Remove the input box
                            cancelButton.remove(); // Remove the cancel button
                            selectElement.classList.remove("d-none"); // Show the select box again
                        } else {
                            updateStatus(`${filename} was not renamed`, "danger");
                        }
                    }
                });
            } else {
                // No change, just restore the select box
                renameInputGroup.remove();
                cancelButton.remove();
                selectElement.classList.remove("d-none");
                selectElement.value = filename; // Restore the original value
            }
        });

    }
});

// Function to handle deleting the bulk file
document.getElementById("delete_icon").addEventListener("click", function () {
    const selectElement = document.getElementById("switch_bulk_file");
    const filename = selectElement.value;

    // Get the value of the default bulk file from the hidden field
    const defaultBulkFile = document.getElementById("bulk_import_file").value;

    // Prevent deleting if the selected file is the default file
    if (filename === defaultBulkFile) {
        updateStatus("You cannot delete the default bulk import file", "danger", false, false, "x-circle");
        return; // Exit the function if it's the default file
    }

    if (filename) {
        if (confirm(`Are you sure you want to permanetly delete ${filename}?`)) {
            socket.emit("delete_bulk_file", {
                instance_id: instanceId,
                filename: filename
            });

            // Wait for response
            socket.once("delete_bulk_file", (data) => {
                if (validResponse(data)) {
                    if (data.deleted) {
                        // Get the value of the default bulk file from the hidden field
                        const defaultBulkFile = document.getElementById("bulk_import_file").value;
                        currentBulkImport = null
                        bulkTextAsLoaded = null
                        loadBulkFileList(); // Reload the file list if deleted
                        loadBulkFile(defaultBulkFile);
                        updateBulkSaveButtonState();
                        // The server removes the file's schedules authoritatively;
                        // mirror it in the local list.
                        schedules = schedules.filter(s => s.file !== data.filename);
                        updateSchedulerIcon();
                    }
                }
            });
        }
    }
});

// Function to handle creating a new bulk file
document.getElementById("create_icon").addEventListener("click", function () {
    // Create a new bulk import file
    socket.emit("create_bulk_file", { instance_id: instanceId });

    socket.once("create_bulk_file", (data) => {
        if (data.created) {
            updateStatus("Created " + data.filename, "success", false, false, "check2-circle");
            // Store the filename to load after refresh
            const newFilename = data.filename;
            // The backend will emit load_bulk_filelist, so we just need to handle it
            socket.once("load_bulk_filelist", (listData) => {
                if (validResponse(listData)) {
                    const selectElement = document.getElementById("switch_bulk_file");
                    // Clear existing options
                    selectElement.innerHTML = "";

                    if (listData.bulk_files && listData.bulk_files.length > 0) {
                        // Populate the dropdown with filenames
                        listData.bulk_files.forEach((filename) => {
                            const option = document.createElement("option");
                            option.value = filename;
                            option.textContent = filename;
                            // Preselect the newly created file
                            if (filename === newFilename) {
                                option.selected = true;
                            }
                            selectElement.appendChild(option);
                        });
                        // Load the newly created file
                        loadBulkFile(newFilename);
                    }
                }
            });
        } else {
            updateStatus("Failed to create new bulk file", "danger", false, false, "x-circle");
        }
    });
});

// Function to handle downloading the current bulk file
document.getElementById("download_icon").addEventListener("click", function () {
    const filename = currentBulkImport || document.getElementById("switch_bulk_file").value;
    if (filename) {
        downloadBulkImportFile(filename)
        socket.emit("display_message", { "instance_id": instanceId, "message": `📥 ${filename} • File successfully downloaded`, "level": "log" });
        updateStatus(filename + " successfully downloaded", "success", false, false, "check2-circle");
    }
});

function downloadBulkImportFile(filename) {
    const file = new Blob([document.getElementById("bulk_import_text").value], { type: 'text/plain' });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(file);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

// Function to handle uploading a bulk file
document.getElementById("upload_icon").addEventListener("click", function () {
    document.getElementById("bulk_import_upload").value = "";
    document.getElementById("bulk_import_upload").click(); // Trigger file input click
});

function uploadBulkImportFile(event) {
    const fileInput = event.target;

    if (fileInput.files.length > 0) {
        const file = fileInput.files[0];

        if (!file.name.endsWith('.txt')) {
            console.error("Invalid file type. Only .txt files are allowed.");
            socket.emit("display_message", { "instance_id": instanceId, "message": "🚫 " + file.name + " • Invalid file type. Only .txt files are allowed.", "level": "log" });
            updateStatus("Invalid file type. Only .txt files are allowed.", "danger", false, false, "x-circle");
            return;
        }

        // Get the select box element
        const selectBox = document.getElementById("switch_bulk_file");

        // Check if the file already exists in the select box
        let fileExists = false;
        for (let option of selectBox.options) {
            if (option.value === file.name) {
                fileExists = true;
                break;
            }
        }

        // If the file exists, ask the user if they want to overwrite it
        if (fileExists) {
            const confirmOverwrite = confirm("File '" + file.name + "' already exists. Would you like to overwrite it?");
            if (!confirmOverwrite) {
                return;
            }
        }

        // Proceed with reading and processing the file
        const reader = new FileReader();
        reader.onload = function(e) {
            const text = e.target.result;

            const bulkTextArea = document.getElementById("bulk_import_text");

            if (bulkTextArea.value !== bulkTextAsLoaded) {
                // If content has changed, show the modal
                saveBulkChangesModal(file.name).then((confirmed) => {
                    if (confirmed === "yes") {
                        saveBulkImport(currentBulkImport);
                    }

                    if (confirmed === "cancel") {
                        return
                    } else {
                        bulkTextArea.value = text;
                        bulkTextAsLoaded = text;
                        currentBulkImport = file.name;
                        saveBulkImport(file.name);
                    }
                });
            } else {
                bulkTextArea.value = text;
                bulkTextAsLoaded = text;
                currentBulkImport = file.name;
                saveBulkImport(file.name);
            }
        };
        reader.readAsText(file);
    } else {
        console.error("No file selected");
    }
}

// Listen for clicks on the "Default bulk file" icon
document.getElementById("default_bulk_file_icon").addEventListener("click", function () {
    const selectElement = document.getElementById("switch_bulk_file");
    const selectedFile = selectElement.value;

    // Only allow setting default if the selected file is different from the current default
    if (selectedFile && document.getElementById("bulk_import_file").value !== selectedFile) {
        // Set the default bulk import file to the selected file
        document.getElementById("bulk_import_file").value = selectedFile; // Update the hidden field

        // Change the icon to checked
        this.classList.remove("bi-check-circle");
        this.classList.add("bi-check-circle-fill");
        this.classList.add("link-primary");

        // Disable the icon to prevent further changes
        this.classList.add("disabled");

        socket.emit("display_message", { "instance_id": instanceId, "message": `✅ Default bulk import file set to '${selectedFile}'`, "level": "log" });
        // Save the configuration change
        saveConfig();
    }
});


// Drag and drop functionality

dropArea.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropArea.classList.add("highlight");
});

dropArea.addEventListener("dragleave", () => {
    dropArea.classList.remove("highlight");
});

dropArea.addEventListener("drop", (e) => {
    e.preventDefault();
    dropArea.classList.remove("highlight");

    const file = e.dataTransfer.files[0];
    const form = document.getElementById("upload_form");

    if (!form.checkValidity()) {
        form.classList.add('was-validated');
        return;
    }
    if (file && file.name.endsWith(".zip")) {
        uploadFile(file);
    } else {
        alert("Please drop a valid ZIP file.");
    }
});

dropArea.addEventListener("click", () => {
    const form = document.getElementById("upload_form");
    
    if (!form.checkValidity()) {
        form.classList.add('was-validated');
        return;
    }
    let input = document.createElement("input");
    input.type = "file";
    input.accept = ".zip";
    input.onchange = (e) => {
        let file = e.target.files[0];
        if (file) uploadFile(file);
    };
    input.click();
});

function uploadFile(file) {
    socket.emit("display_message", {
        "instance_id": instanceId,
        "message": `Uploading '${file.name}'...`,
        "title": "uploadFile",
        "level": "debug"
    });
    socket.emit("display_message", {
        "instance_id": instanceId,
        "message": `📤 ${file.name} • Upload initiated`,
        "level": "log",
        "broadcast": true
    });

    const reader = new FileReader();

    let offset = 0;
    let isAborted = false;

    reader.onload = function (event) {
        const arrayBuffer = event.target.result;
        const totalChunks = Math.ceil(arrayBuffer.byteLength / CHUNK_SIZE);
        let startTime = performance.now();

        function arrayBufferToBase64(buffer) {
            return new Promise((resolve) => {
                const blob = new Blob([buffer]);
                const reader = new FileReader();
                reader.onloadend = () => {
                    let base64Data = reader.result.split(",")[1]; // Extract only the Base64 part
                    resolve(base64Data);
                };
                reader.readAsDataURL(blob);
            });
        }

        function sendChunk() {
            if (isAborted) return;

            if (offset >= arrayBuffer.byteLength) {
                console.log("All chunks sent, emitting upload_complete event.");

                // Collect checked input fields with ids starting with "upload-option-"
                let options = [];
                document.querySelectorAll('[id^="upload-option-"]:checked').forEach(checkbox => {
                    options.push(checkbox.value);
                });   
                
                // Collect checked checkboxes with ids starting with "upload-filter-"
                let filters = [];
                if (!document.getElementById("upload-filters-global").checked) {
                    document.querySelectorAll('[id^=upload-filter-]:checked').forEach(checkbox => {
                        filters.push(checkbox.value);
                    });
                }

                const plex_year = document.getElementById("plex_year").value;
                const plex_title = document.getElementById("plex_title").value;

                socket.emit("upload_complete", {
                    instance_id: instanceId,
                    fileName: file.name,
                    options: options,
                    filters: filters,
                    plex_title: plex_title,
                    plex_year: plex_year
                });

                return; // Ensure no further execution in this function
            }

            const chunk = arrayBuffer.slice(offset, offset + CHUNK_SIZE);

            arrayBufferToBase64(chunk).then(base64Chunk => {
                if (isAborted) return;
                
                let currentTime = performance.now();
                let totalSize = arrayBuffer.byteLength / 1000000;
                socket.emit("upload_artwork_chunk", {
                    instance_id: instanceId,
                    fileName: file.name,
                    chunkData: base64Chunk,
                    chunkIndex: offset / CHUNK_SIZE,
                    totalChunks: totalChunks,
                    totalSize: totalSize,
                    startTime: startTime,
                    currentTime: currentTime
                }, (ack) => {
                    if (ack === "ok") {
                        if (isAborted) return;

                        offset += CHUNK_SIZE; // Offset is in bytes
                        sendChunk();
                    } else if (ack === "abort") {
                        isAborted = true;
                        return;
                    } else {
                        console.error("Backend failed to acknowledge chunk.")
                    }
                });
            });
        }
        sendChunk();
    };
    reader.readAsArrayBuffer(file);
}

socket.on("upload_progress", function (data) {
    if(validResponse(data)) {
        progressBar(data.progress, `${progress}%`);
    }
});

socket.on("upload_complete", function (data) {
    if(validResponse(data)) {
        progressBar(100,"Upload complete!");
    }
});

// =====================
// Scheduler
// =====================

    let editingScheduleId = null; // Set while the form is editing an existing schedule rather than adding a new one
    let editingScheduleLastRun = null;
    let editingScheduleLastRunStatus = null;

    function describeSchedule(s) {
        let text = "";
        if (s.time) {
            text = `Daily at ${s.time}`;
        } else {
            const unit = s.interval_value === 1 ? s.interval_unit.replace(/s$/, "") : s.interval_unit;
            text = `Every ${s.interval_value} ${unit}`;
        }

        if (s.next_run) {
            let status_badge = ""
            const formattedNextRun = formatDateTime(s.next_run);
            const formattedLastRun = formatDateTime(s.last_run)
            if (formattedNextRun){
                text = `${text} <span class="badge text-body-secondary bg-body-tertiary border ms-2 fw-normal fs-7">${formattedNextRun}</span>`;
            }
            if (s.last_run_status) {
                const outcome = RUN_HISTORY_OUTCOME_LABELS[s.last_run_status]
                const colorClass = s.last_run_status === "never_run" 
                    ? "secondary" 
                    : (outcome?.iconColor || "secondary");
                const iconClass = s.last_run_status === "never_run"
                    ? "bi bi-question-circle-fill"
                    : `bi bi-${outcome?.icon || "bi bi-question-circle-fill"}`;
                const titleText = outcome ? `${outcome.text} (${formattedLastRun})` : "Never run";
                const status_badge = `<i class="text-${colorClass} ${iconClass} ms-2 align-middle" title="${titleText}"></i>`;
                text = `${text}${status_badge}`
            }
        }
        return text;
    }

    function getSchedulesForFile(fileName) {
        return schedules.filter(s => s.file === fileName);
    }

    socket.on("get_schedules", (data) => {
        if (validResponse(data, true)) {
            schedules = data.schedules
            updateSchedulerIcon();
        } else {
            console.log("Unable to obtain schedules from backend")
        }
    });

    // Show the time selector when the clock icon is clicked
    scheduleIcon.addEventListener("click", function () {
        socket.emit("get_schedules", {instance_id: instanceId})

        const iconRect = scheduleIcon.getBoundingClientRect();
        const boxWidth = timeSelectBox.offsetWidth || 300; // Fallback width

        // Vertical placement below icon
        timeSelectBox.style.top = `${iconRect.bottom + window.scrollY + 10}px`;

        // Horizontal placement bounded to screen edges (15px padding)
        let leftPos = iconRect.right + window.scrollX - boxWidth + 13;
        leftPos = Math.max(15, Math.min(leftPos, window.innerWidth - boxWidth - 15));
        timeSelectBox.style.left = `${leftPos}px`;
        timeSelectBox.style.right = 'auto';

        // Align arrow directly under the clock icon center
        const arrow = document.getElementById("tooltip_arrow");
        if (arrow) {
            const arrowOffset = (iconRect.left + window.scrollX + (iconRect.width / 2)) - leftPos;
            arrow.style.left = `${Math.max(15, Math.min(arrowOffset, boxWidth - 25))}px`;
            arrow.style.right = 'auto';
        }

        // Reset the state of selected schedules
        resetScheduleForm();
        
        // Toggle visibility
        timeSelectBox.classList.toggle("show-tooltip");

    });

    document.addEventListener("click", function (event) {
        if (!timeSelectBox.contains(event.target) && !scheduleIcon.contains(event.target)) {
            resetScheduleForm();
            timeSelectBox.classList.remove("show-tooltip");
        }
    });

    // Toggle between the "daily at a time" and "every N hours/days" inputs
    scheduleTypeSelect.addEventListener("change", function () {
        const isDaily = scheduleTypeSelect.value === "daily";

        scheduleTimeGroup.classList.toggle("d-none", !isDaily);
        scheduleIntervalGroup.classList.toggle("d-none", isDaily);
        runNowLabel.classList.toggle("d-none", isDaily);
        runNowCheckbox.checked = !isDaily;
        
        // Initialize tooltip if switching to interval schedule
        if (!isDaily) {
            const tooltipIcon = document.getElementById("run_now_info_icon");
            if (tooltipIcon) {
                // Dispose of any old/stale instance created while hidden
                const existingInstance = bootstrap.Tooltip.getInstance(tooltipIcon);
                if (existingInstance) {
                    existingInstance.dispose();
                }
                // Create fresh instance NOW that the element has non-zero dimensions!
                new bootstrap.Tooltip(tooltipIcon, {
                    html: true,
                    sanitize: false,
                    container: 'body', // Appends to <body> so z-index/popover clipping is bypassed
                    trigger: 'hover'
                });
            }
        }
    });

    function resetScheduleForm() {
        const fileSchedules = getSchedulesForFile(currentBulkImport);
        fileSchedules.forEach(s => {
            const row = document.getElementById(s.id);
            if (row){
                row.classList.remove("bg-body-secondary");
                row.classList.remove("border-primary");
            };
        });
        editingScheduleId = null;
        editingScheduleLastRun = null;
        editingScheduleLastRunStatus = null;
        setTimeBtn.innerHTML = '<i class="bi bi-plus-lg"></i>';
        setTimeBtn.classList.add("btn-primary");
        setTimeBtn.classList.remove("btn-success");
        scheduleTypeSelect.value = "daily";
        scheduleTimeGroup.classList.remove("d-none");
        scheduleIntervalGroup.classList.add("d-none");
        scheduleTimeInput.value = "";
        scheduleIntervalValueInput.value = 1;
        scheduleIntervalUnitSelect.value = "hours";
        runNowLabel.classList.add("d-none");
        runNowCheckbox.checked = true;
    }

    function editSchedule(s) {
        editingScheduleId = s.id;
        editingScheduleLastRun = s.last_run;
        editingScheduleLastRunStatus = s.last_run_status;
        setTimeBtn.innerHTML = '<i class="bi bi-arrow-counterclockwise"></i>';
        setTimeBtn.classList.remove("btn-primary");
        setTimeBtn.classList.add("btn-success");
        if (s.time) {
            scheduleTypeSelect.value = "daily";
            scheduleTimeGroup.classList.remove("d-none");
            scheduleIntervalGroup.classList.add("d-none");
            scheduleTimeInput.value = s.time;
            runNowLabel.classList.add("d-none");
        } else {
            scheduleTypeSelect.value = "interval";
            scheduleTimeGroup.classList.add("d-none");
            scheduleIntervalGroup.classList.remove("d-none");
            scheduleIntervalValueInput.value = s.interval_value;
            scheduleIntervalUnitSelect.value = s.interval_unit;
            runNowLabel.classList.remove("d-none");
            runNowCheckbox.checked = true;
        }
    }

    // Handle adding or updating a schedule
    setTimeBtn.addEventListener("click", function () {
        const payload = { instance_id: instanceId, file: currentBulkImport };
        if (editingScheduleId) {
            payload.id = editingScheduleId;
            payload.last_run = editingScheduleLastRun;
            payload.last_run_status = editingScheduleLastRunStatus;
        } else {
            payload.last_run_status = "never_run";
        }

        if (scheduleTypeSelect.value === "daily") {
            if (!scheduleTimeInput.value) return;
            payload.time = scheduleTimeInput.value;
        } else {
            const intervalValue = parseInt(scheduleIntervalValueInput.value, 10);
            if (!intervalValue || intervalValue < 1) return;
            payload.interval_value = intervalValue;
            payload.interval_unit = scheduleIntervalUnitSelect.value;
            payload.run_now = runNowCheckbox.checked
        }

        socket.emit("add_schedule", payload);

        // Wait for response on add schedule
        socket.once("add_schedule", (data) => {
            if (validResponse(data)) {
                if (data.added) {
                    schedules = schedules.filter(s => s.id !== data.id);
                    schedules.push({
                        id: data.id,
                        file: data.file,
                        time: data.time,
                        interval_value: data.interval_value,
                        interval_unit: data.interval_unit,
                        next_run: data.next_run,
                        last_run_status: data.last_run_status
                    });
                    updateSchedulerIcon();
                }
            }
        });
    });

    // Handle removing a schedule from the list
    function deleteSchedule(scheduleId) {
        // Uses the ack callback (rather than a shared "once" listener) so that
        // deleting several schedules in a row - e.g. all of a file's schedules
        // when the file itself is deleted - matches each response to its own
        // request instead of every listener consuming the first reply.
        socket.emit("delete_schedule", { instance_id: instanceId, id: scheduleId }, (data) => {
            if (data && data.deleted) {
                schedules = schedules.filter(s => s.id !== data.id);
                updateSchedulerIcon();
            }
        });
    }

    function formatDateTime(isoString) {
        if (!isoString) return "";
        
        try {
            const date = new Date(isoString);
            if (isNaN(date.getTime())) return "";

            const today = new Date();
            
            const tomorrow = new Date(today);
            tomorrow.setDate(tomorrow.getDate() + 1);
            
            const yesterday = new Date(today);
            yesterday.setDate(yesterday.getDate() - 1);

            const isToday = date.toDateString() === today.toDateString();
            const isTomorrow = date.toDateString() === tomorrow.toDateString();
            const isYesterday = date.toDateString() === yesterday.toDateString();

            // Format time as HH:MM
            const hours = String(date.getHours()).padStart(2, '0');
            const minutes = String(date.getMinutes()).padStart(2, '0');
            const timeStr = `${hours}:${minutes}`;

            if (isToday) {
                return `Today at ${timeStr}`;
            } else if (isTomorrow) {
                return `Tomorrow at ${timeStr}`;
            } else if (isYesterday) {
                return `Yesterday at ${timeStr}`;
            }

            // Format date as "Aug 14, 23:58"
            const monthNames = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
            const month = monthNames[date.getMonth()];
            const day = date.getDate();

            return `${month} ${day}, ${timeStr}`;
        } catch (e) {
            // Fallback: strip ISO microseconds and timezone if regex/date fails
            return isoString.replace("T", " ").replace(/\.\d+/, "").slice(0, 16);
        }
    }

    function renderScheduleList() {
        scheduleListEl.innerHTML = "";
        const fileSchedules = getSchedulesForFile(currentBulkImport);

        if (!fileSchedules.length) return;

        const title = document.createElement("label");
        title.innerHTML = '<i class="bi bi-calendar-check"></i>&ensp;Current schedules';
        scheduleListEl.appendChild(title);
        
        fileSchedules.forEach((s, i, arr) => {
            
            const item = document.createElement("li");
            item.id = s.id;
            item.className = "list-group-item d-flex justify-content-between align-items-center";

            const isFirst = i === 0;
            const isLast = i === arr.length - 1;

            if (isFirst) item.classList.add("mt-2", "rounded-top");
            if (isLast) item.classList.add("mb-2", "rounded-bottom");

            const label = document.createElement("span");
            label.innerHTML = describeSchedule(s);
            label.setAttribute("role", "button");
            label.addEventListener("click", () => {
                if (s.id != editingScheduleId) {
                    activeRow = document.getElementById(editingScheduleId);
                    if (activeRow) {
                        activeRow.classList.remove("bg-body-secondary");
                        activeRow.classList.remove("border-primary");
                    };
                    label.parentElement.classList.toggle("bg-body-secondary");
                    label.parentElement.classList.toggle("border-primary");
                    editSchedule(s);
                } else {
                    resetScheduleForm();
                }
            });

            const deleteBtn = document.createElement("i");
            deleteBtn.className = "bi bi-trash3 text-danger delete-schedule-btn";
            deleteBtn.setAttribute("role", "button");
            deleteBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                deleteSchedule(s.id);
            });

            item.appendChild(label);
            item.appendChild(deleteBtn);
            scheduleListEl.appendChild(item);
        });
    }

    function updateSchedulerIcon(){
        const fileSchedules = getSchedulesForFile(currentBulkImport);
        renderScheduleList();

        if (fileSchedules.length > 0) {
            scheduleIcon.classList.remove("bi-clock");
            scheduleIcon.classList.add("bi-clock-fill"); // Change to filled icon
            scheduleIcon.classList.add("text-success"); // Turn icon green
        } else {
            scheduleIcon.classList.add("bi-clock"); // Change to unfilled icon
            scheduleIcon.classList.remove("bi-clock-fill");
            scheduleIcon.classList.remove("text-success"); // Remove green color
        }

        resetScheduleForm();
    }



function updateApp() {
    document.getElementById("version_notifier").classList.add("d-none");
    socket.emit("update_app", { instance_id: instanceId});
}

socket.on("update_failed", function(data) {
    alert("Update failed: " + data.error);
});


socket.on("backend_restarting", function() {
    console.log("Backend restarting, refreshing frontend too...");
    updateStatus("Backend restarting, refreshing frontend too...", "warning", true, true, "arrow-counterclockwise")
    setTimeout(() => {
        location.reload();  // Reload the page
    }, 3000);  // Delay for 3 seconds to ensure restart
});

// Detect when the WebSocket connection is lost
socket.on("disconnect", function() {
    console.log("WebSocket disconnected, attempting to reconnect...");
    updateStatus("Connection to server lost, reconnecting...", "warning", true, true, "arrow-counterclockwise")
    // Refresh the page to reconnect to the WebSocket
    setTimeout(() => {
        location.reload();  // Reload to attempt reconnection
    }, 3000);  // Delay for 3 seconds before refresh to allow connection retry
});

// ==================================================
// Authentication Settings Toggle
// ==================================================

function toggleAuthSettings() {
    const authEnabled = document.getElementById("auth_enabled").checked;
    const authSettings = document.getElementById("auth_settings");
    if (authEnabled) {
        authSettings.style.display = "block";
    } else {
        authSettings.style.display = "none";
    }
}

// Add event listener for auth_enabled checkbox
document.getElementById("auth_enabled").addEventListener("change", toggleAuthSettings);

// ==================================================
// Webhook Settings Toggle
// ==================================================

function toggleWebhookSettings() {
    const enabled = document.getElementById("enable_webhooks").checked;
    document.getElementById("webhook_settings").style.display = enabled ? "block" : "none";
    // When enabling with an empty token, pre-fill a random one. getRandomValues works in
    // insecure (plain http) contexts, unlike crypto.randomUUID.
    const tokenField = document.getElementById("webhook_token");
    if (enabled) {
        tokenField.setAttribute("required", "");
        if (tokenField.dataset.originalValue) {
            tokenField.value = tokenField.dataset.originalValue;
        }
    } else {
        tokenField.removeAttribute("required");
        tokenField.classList.remove("is-invalid", "is-valid");
        if (!tokenField.dataset.originalValue) {
            tokenField.dataset.originalValue = tokenField.value;
        }
        tokenField.value='';
    }
}

function generateRandomToken() {
    return Array.from(crypto.getRandomValues(new Uint8Array(16)))
        .map(b => b.toString(16).padStart(2, "0"))
        .join("");
}

document.getElementById("generate_webhook_token").addEventListener("click", function () {
    document.getElementById("webhook_token").value = generateRandomToken();
    toggleConfigButtons();
})

document.getElementById("enable_webhooks").addEventListener("change", toggleWebhookSettings);

// ==================================================
// Kometa Settings Toggle
// ==================================================

function toggleKometaSettings() {
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const kometaSettings = document.getElementById("kometa_settings");
    const kometaBase = document.getElementById("kometa_base");
    const dockerWarning = document.getElementById("docker_warning");
    const kometaTimeout = document.getElementById("kometa_timeout_container");
    const uploadTimeoutLabel = document.getElementById("plex_timeout_label");
    const uploadRetryLabel = document.getElementById("upload_retry_label");

    if (saveToKometa) {
        kometaSettings.style.display = "block";
        kometaTimeout.classList.remove("d-none");
        uploadTimeoutLabel.innerHTML='<i class="bi bi-plugin"></i>&ensp;Plex connect timeout:';
        uploadRetryLabel.textContent="download";
        if (docker) {
            if (dockerWarning) {
                dockerWarning.classList.remove("d-none");
            }
        } else {
            if (dockerWarning) {
                dockerWarning.classList.add("d-none");
            }
        }
        if (kometaBase) {
            // Make the Kometa base directory field required
            kometaBase.required = true;
            // Optionally clear any previous invalid state so the user can re-validate
            kometaBase.classList.remove('is-invalid');
        }
    } else {
        if (dockerWarning) {
            dockerWarning.classList.add("d-none");
        }
        kometaSettings.style.display = "none";
        kometaTimeout.classList.add("d-none");
        uploadTimeoutLabel.innerHTML='<i class="bi bi-cloud-upload"></i>&ensp;Plex connect/upload timeout:';
        uploadRetryLabel.textContent="upload";
        if (kometaBase) {
            kometaBase.required = false;
            // Clear invalid styling when hiding
            kometaBase.classList.remove('is-invalid');
        }
    }
    // Update the label for the "force" option depending on Kometa mode
    const forceLabel = document.querySelector('label[for="option-force"]');
    const forceLabelUpload = document.querySelector('label[for="upload-option-force"]');
    if (forceLabel) {
        if (saveToKometa) {
            forceLabel.textContent = 'Force save the artwork, replacing any existing asset';
            forceLabelUpload.textContent = 'Force save the artwork, replacing any existing asset';
        } else {
            forceLabel.textContent = 'Force upload the artwork, even if it\'s locked or it already exists';
            forceLabelUpload.textContent = 'Force upload the artwork, even if it\'s locked or it already exists';
        }
    }

    // Check if temp option should be shown, the Plex options should be hidden, and the stage option in the scraper tab should be hidden
    toggleTempCheckbox();
    togglePlexOptions();
    toggleScraperStageCheckbox();
    toggleSkipLockedCheckbox();
}

function toggleSkipLockedCheckbox() {
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const globalSkipLocked = document.getElementById("skip_locked_artwork");
    const skipLockedScraperOption = document.getElementById("option-skip-locked");
    const skipLockedUploadOption = document.getElementById("upload-option-skip-locked");
    const globalAllowArtistUpdates = document.getElementById("allow_artist_updates");
    const allowArtistUpdatesScrapeOption = document.getElementById("option-allow-artist-updates");
    const trackArtworkIDs = document.getElementById("track_artwork_ids").checked;
    
    // Hide and uncheck the skip locked option if Kometa is enabled
    if (saveToKometa) {
        skipLockedScraperOption.parentElement.style.display = "none";
        skipLockedScraperOption.checked = false;
        skipLockedUploadOption.parentElement.style.display = "none";
        skipLockedUploadOption.checked = false;
        globalAllowArtistUpdates.parentElement.style.display = "none";
        globalAllowArtistUpdates.checked = false;
        allowArtistUpdatesScrapeOption.parentElement.style.display = "none";
        allowArtistUpdatesScrapeOption.checked = false;
    } else {
        if (globalSkipLocked.checked) {
            skipLockedScraperOption.parentElement.style.display = "none";
            skipLockedScraperOption.checked = true;
            skipLockedUploadOption.parentElement.style.display = "none";
            skipLockedUploadOption.checked = true;
            globalAllowArtistUpdates.parentElement.style.display = trackArtworkIDs ? "block" : "none";
            allowArtistUpdatesScrapeOption.parentElement.style.display = globalAllowArtistUpdates.checked ? "none" : "block";
        } else {
            skipLockedScraperOption.parentElement.style.display = "block";
            skipLockedScraperOption.checked = false;
            skipLockedUploadOption.parentElement.style.display = "block";
            skipLockedUploadOption.checked = false;
            globalAllowArtistUpdates.parentElement.style.display = "none";
            globalAllowArtistUpdates.checked = false;
            allowArtistUpdatesScrapeOption.parentElement.style.display = "none";
            allowArtistUpdatesScrapeOption.checked = false;
        }
    }
}

// Add event listener for global skip locked artwork checkbox
document.getElementById("skip_locked_artwork").addEventListener("change", toggleSkipLockedCheckbox);
document.getElementById("track_artwork_ids").addEventListener("change", toggleSkipLockedCheckbox);
document.getElementById("allow_artist_updates").addEventListener("change", toggleSkipLockedCheckbox);

function toggleScraperStageCheckbox() {
    const globalStageSetting = document.getElementById("stage_assets").checked;
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const scraperStageOption = document.getElementById("option-stage");
    const scraperStageOptionUpload = document.getElementById("upload-option-stage");

    // Hide and uncheck the scraper stage option if global stage setting is enabled
    if (globalStageSetting) {
        scraperStageOption.parentElement.style.display = "none";
        scraperStageOption.checked = false;
        scraperStageOptionUpload.parentElement.style.display = "none";
        scraperStageOptionUpload.checked = false;
    } else {
        if (saveToKometa) {
            scraperStageOption.parentElement.style.display = "block";
            scraperStageOptionUpload.parentElement.style.display = "block";
        } else {
            scraperStageOption.parentElement.style.display = "none";
            scraperStageOption.checked = false;
            scraperStageOptionUpload.parentElement.style.display = "none";
            scraperStageOptionUpload.checked = false;
        }
    }
}

function toggleTempCheckbox() {
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const tempDir = document.getElementById("temp_dir").value.trim();
    const tempCheckbox = document.getElementById("option-temp");
    const tempCheckboxUpload = document.getElementById("upload-option-temp");
    
    // Only show temp option in the scraper tab if Kometa is enabled AND temp dir has a value
    if (saveToKometa && tempDir) {
        tempCheckbox.parentElement.style.display = "block";
        tempCheckboxUpload.parentElement.style.display = "block";
    } else {
        // Hide and uncheck the option when conditions aren't met
        tempCheckbox.parentElement.style.display = "none";
        tempCheckbox.checked = false;
        tempCheckboxUpload.parentElement.style.display = "none";
        tempCheckboxUpload.checked = false;
    }
}

function togglePlexOptions() {
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const trackArtworkIDs = document.getElementById("track_artwork_ids").parentElement;
    const skipLocked = document.getElementById("skip_locked_artwork").parentElement;
    const resetOverlay = document.getElementById("reset_overlay").parentElement;

    // Ony show the Track Artwork IDs and Reset Overlay options if Kometa is disabled
    if (!saveToKometa) {
        trackArtworkIDs.style.display = "block";
        resetOverlay.style.display = "block";
        skipLocked.style.display = "block";
    } else {
        trackArtworkIDs.style.display = "none";
        resetOverlay.style.display = "none";
        skipLocked.style.display = "none";
        document.getElementById("skip_locked_artwork").checked = false; // Uncheck the skip locked option if Kometa is enabled
        document.getElementById("track_artwork_ids").checked = true;
    }
}

// Add event listener for save_to_kometa checkbox
document.getElementById("save_to_kometa").addEventListener("change", toggleKometaSettings);

// Add event listener for auto_manage_bulk_files checkbox
document.getElementById("auto_manage_bulk_files").addEventListener("change", toggleAddToBulkCheckbox);

function toggleAddToBulkCheckbox() {
    const autoManageBulkFiles = document.getElementById("auto_manage_bulk_files").checked;
    const addToBulkCheckbox = document.getElementById("option-add-to-bulk")
    const addToBulk = addToBulkCheckbox.parentElement;
    if (autoManageBulkFiles) {
        // Hides the scraper-level add-to-bulk checkbox if the global settings is enabled
        addToBulkCheckbox.checked = true;
        addToBulk.classList.add("d-none");
    } else {
        // Shows the scraper-level add-to-bulk cehckbox if the global setting is disabled
        addToBulkCheckbox.checked = false;
        addToBulk.classList.remove("d-none");
    }
}

// Add event listener for temp_dir input to toggle temp option visibility
document.getElementById("temp_dir").addEventListener("input", toggleTempCheckbox);

// Add event listener for stage_assets checkbox
document.getElementById("stage_assets").addEventListener("change", toggleScraperStageCheckbox);

document.getElementById("cache_user_scrapes").addEventListener("change", toggleUserCacheExpiryField);

function toggleUserCacheExpiryField() {
    const userCacheToggle = document.getElementById("cache_user_scrapes");
    const cacheExpiryContainer = document.getElementById("cache_expiry_container");

    if (userCacheToggle.checked) {
        cacheExpiryContainer.classList.remove("d-none");
    } else {
        cacheExpiryContainer.classList.add("d-none");
    }
}

// Notification events a channel can be subscribed to, mirrors core/enums.py NotificationEvent
const NOTIFICATION_EVENTS = [
    { value: "run_started", label: "Started" },
    { value: "run_completed", label: "Completed cleanly" },
    { value: "run_completed_with_errors", label: "Completed with errors" },
    { value: "run_failed_to_start", label: "Failed to start" },
    { value: "run_skipped", label: "Skipped" },
    { value: "run_cancelled", label: "Cancelled" },
];

// Events a newly added channel is subscribed to, matches core/constants.py DEFAULT_NOTIFICATION_EVENTS
const DEFAULT_NOTIFICATION_EVENTS = ["run_started", "run_completed", "run_completed_with_errors", "run_cancelled"];

let appriseRowCounter = 0;

// Creates a single Apprise URL input row, with a delete button and per-event notification toggles
function createAppriseUrlRow(channel = {}, last = false) {
    const container = document.getElementById("apprise_urls_container");
    const url = channel.url || "";
    const events = Array.isArray(channel.events) ? channel.events : DEFAULT_NOTIFICATION_EVENTS;
    const rowId = appriseRowCounter++;

    const row = document.createElement("div");
    row.className = "apprise-url-row";

    const eventChecks = NOTIFICATION_EVENTS.map(event => `
            <div class="form-check form-check-inline">
                <input class="form-check-input apprise-event-checkbox" type="checkbox" value="${event.value}"
                       id="apprise_event_${rowId}_${event.value}" ${events.includes(event.value) ? "checked" : ""}>
                <label class="form-check-label small" for="apprise_event_${rowId}_${event.value}">${event.label}</label>
            </div>`).join("");

    row.innerHTML = `
        <div class="position-relative apprise-url-input-wrap">
            <input type="text"
                   class="form-control input-monospace apprise-url-input ${last ? 'has-two-inline-btns' : 'has-inline-btn'}"
                   placeholder="discord://{botname}@{WebhookID}/{WebhookToken}"
                   spellcheck="false"
                   autocomplete="off"
                   autocorrect="off"
                   autocapitalize="off">
            <div class="apprise-row-actions">
                <button type="button" class="btn-inline-icon add-apprise-url-btn" title="Add another URL">
                    <i class="bi bi-plus-circle"></i>
                </button>
                <button type="button" class="btn-inline-icon remove-apprise-url-btn" title="Remove URL">
                    <i class="bi bi-x-circle"></i>
                </button>
            </div>
        </div>
        <div class="apprise-event-checks d-flex flex-wrap mb-2">${eventChecks}</div>
    `;

    // Event listener to add a row
    row.querySelector(".add-apprise-url-btn").addEventListener("click", () => {
        createAppriseUrlRow();
        const inputs = document.querySelectorAll(".apprise-url-input");
        inputs[inputs.length - 1].focus();
        inputs[inputs.length - 1].addEventListener("input", toggleConfigButtons);
    });

    // Event listener to remove this row
    row.querySelector(".remove-apprise-url-btn").addEventListener("click", () => {
        row.remove();
        // Keep at least one empty row if all are deleted
        if (container.children.length === 0) {
            createAppriseUrlRow();
        }
        toggleConfigButtons();
    });

    // Assign as a property, not interpolated into innerHTML: a quote in the
    // URL would truncate the attribute and corrupt the channel on next save.
    row.querySelector(".apprise-url-input").value = url;

    container.appendChild(row);
    toggleConfigButtons();
}

// Reads the URL and subscribed events out of every Apprise channel row currently in the DOM
function collectAppriseChannels() {
    return Array.from(document.querySelectorAll(".apprise-url-row"))
        .map(row => {
            const url = row.querySelector(".apprise-url-input").value.trim();
            const events = Array.from(row.querySelectorAll(".apprise-event-checkbox:checked")).map(checkbox => checkbox.value);
            return { url, events };
        })
        .filter(channel => channel.url !== "");
}

let tooltipTimeout = null;

function toggleNotification() {
    const checkbox = document.getElementById("bulk_notify");
    const button = document.getElementById("notify_toggle");
    const icon = document.getElementById("notify_icon");
    
    // Toggle state
    checkbox.checked = !checkbox.checked;

    if (checkbox.checked) {
        // Active State (Enabled)
        button.classList.remove("btn-secondary");
        button.classList.add("btn-success");
        icon.classList.remove("bi-bell-slash");
        icon.classList.add("bi-bell");
        newTitle = "Notifications enabled";
    } else {
        // Inactive State (Disabled)
        button.classList.remove("btn-success");
        button.classList.add("btn-secondary");
        icon.classList.remove("bi-bell");
        icon.classList.add("bi-bell-slash");        
        newTitle = "Notifications disabled";
    }
    
    let tooltip = bootstrap.Tooltip.getInstance(button);
    if (!tooltip) {
        tooltip = new bootstrap.Tooltip(button, { trigger: 'manual' });
    }
    
    if (tooltipTimeout) clearTimeout(tooltipTimeout);

    tooltip.setContent({ '.tooltip-inner': newTitle });
    tooltip.show()

    tooltipTimeout = setTimeout(() => {
        tooltip.hide();
    }, 1000);    
}