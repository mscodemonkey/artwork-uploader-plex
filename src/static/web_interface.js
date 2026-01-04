// ==================================================
// App initialisation and startup
// ==================================================

let config = {};                // Current configuration
let statusTimeout;              // Store timeout reference
let schedules = [];             // Scheduled imports
let currentBulkImport = '';     // Current bulk import file
let bulkTextAsLoaded = '';      // File contents when loaded, to determine changes
let barTimer = null;            // Timer for progress bar

const socket = io();
const instanceId = getInstanceId();

const CHUNK_SIZE = 1024 * 64; // 64 KB per chunk for uploads


// UI References
const scrapeUrlInput = document.getElementById("scrape_url");
const dropArea = document.getElementById("drop-area");
const scheduleIcon = document.getElementById("schedule_icon");
const setTimeBtn = document.getElementById("set_time");
const cancelTimeBtn = document.getElementById("cancel_time");
const setContainer = document.getElementById("set_container");
const cancelContainer = document.getElementById("cancel_container");
const scheduleTimeInput = document.getElementById("schedule_time");
const timeSelectBox = document.getElementById("time_select_box");
const bulkFileSwitcher = document.getElementById("switch_bulk_file");

// Event listeners
document.addEventListener("DOMContentLoaded", function () {
    updateLog("📍 New session started with ID: " + instanceId)
    loadConfig()
    toggleThePosterDBElements();
});

// Specific event listeners
document.getElementById("switch_bulk_file").addEventListener("change", bulkFileSwitched);
document.getElementById("bulk_import_text").addEventListener("input", updateBulkSaveButtonState);
document.getElementById("scraper-filters-global").addEventListener("change", inheritGlobalFiltersForScraper);
document.getElementById("upload-filters-global").addEventListener("change", inheritGlobalFiltersForUploads);
document.getElementById("btnUpdate").addEventListener("click", updateApp);

// ==================================================
// General helper functions
// ==================================================

// Check incoming socket message is for this instance
function validResponse(data, broadcast = false) {
    return data.instance_id === instanceId || (broadcast && data.broadcast);
}


// Generate a UUID to create an instance ID in local storage
function getInstanceId() {
    // Fallback for browsers that don't support crypto.randomUUID()
    const fallbackUUID = () => 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
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

// Disable frontend elements from backend
function element_disable(element_ids, mode = true) {
    if (!element_ids) return;  // Exit if no element_ids provided

    // Ensure it's always treated as an array
    let elements = Array.isArray(element_ids) ? element_ids : [element_ids];

    // Loop through each element ID and disable/enable it
    elements.forEach(id => {
        let element = document.getElementById(id);
        if (element) {
            element.disabled = mode;
        } else {
            console.warn('Element with ID "${id}" not found.');
        }
    });
}

socket.on("element_disable", (data) => {
    if (validResponse(data)) {
        element_disable(data.element, data.mode);
    }
});


// Update the status bar
function updateStatus(message, color = "info", sticky = false, spinner = false, icon = '') {

    const statusEl = document.getElementById("status");
    const spinnerEl = document.getElementById("status_spinner"); // Get the spinner element
    const messageEl = document.getElementById("status_message");
    const iconEl = document.getElementById("status_icon");

    if (!statusEl) return;

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
            statusEl.classList.remove('show'); // Fade out the status after 3 seconds
        }, 5000);
    }

}

socket.on("status_update", (data) => {
    if (validResponse(data, true)) {
        updateStatus(data.message, data.color, data.sticky, data.spinner, data.icon);
    }
});


// Update the log page
function updateLog(message, color = null, artwork_title = null) {
    let statusElement = document.getElementById("scraping_log");

    // Get current timestamp
    let timestamp = new Date().toLocaleTimeString("en-GB", {hour12: false});

    // Prepend the new message with timestamp
    statusElement.innerHTML = '<div class="log_message">[' + timestamp + '] ' + message + '</div>' + statusElement.innerHTML;
}

socket.on("log_update", (data) => {
    if (validResponse(data, true)) {
        updateLog(data.message, data.artwork_title);
    }
});


// Update the progress bar, showing and hiding as required
function progress_bar(percent, message = "") {

    const bar_container = document.getElementById("progress_bar_container")
    const bar = document.getElementById("progress_bar")

    percent = percent > 100 ? 100 : percent;

    if (percent <= 100) {
        if (barTimer) {
            clearTimeout(barTimer); // Cancel the previous timeout
        }
        bar_container.classList.add("show")
        bar.style.width = percent + "%"
        bar_container.ariaValueNow = message
        bar.innerHTML = message || ""
    }

    if (percent === 100) {
        barTimer = setTimeout(() => {
            bar_container.classList.remove('show'); // Fade out the progress bar after a second
        }, 2000);
    }
}

socket.on("progress_bar", (data) => {
    if (validResponse(data)) {
        progress_bar(data.percent, data.message)
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
                document.getElementById("bulk_import_text").value = processAndSortUrls(bulkText, data.title, cleanedUrl);
            } else {
                document.getElementById("bulk_import_text").value += `\n// ${data.title}\n${cleanedUrl}\n`;
            }

        }

        updateBulkSaveButtonState();
    }

});


// Sort the bulk list into order by media title
function processAndSortUrls(inputText, newTitle, newUrl) {

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
document.getElementById("save_config_button").addEventListener("click", function (event) {
    event.preventDefault(); // Prevent actual form submission
    saveConfig();
});

// Save configuration
function saveConfig() {
    const form = document.getElementById("config_form");

    if (!form.checkValidity()) {
        form.classList.add("was-validated");
        return; // Prevent further execution if form is invalid
    }

    // Form is valid, proceed with saving config
    const save_config = {};

    save_config.base_url = document.getElementById("plex_base_url").value.trim();
    save_config.token = document.getElementById("plex_token").value.trim();
    save_config.kometa_base = document.getElementById("kometa_base").value.trim();
    save_config.temp_dir = document.getElementById("temp_dir").value.trim();
    toggleTempCheckbox();
    save_config.bulk_txt = document.getElementById("bulk_import_file").value;

    // Convert comma-separated library inputs to arrays
    save_config.tv_library = document.getElementById("tv_library").value
        .split(",")
        .map(item => item.trim())
        .filter(item => item !== ""); // Remove empty values

    save_config.movie_library = document.getElementById("movie_library").value
        .split(",")
        .map(item => item.trim())
        .filter(item => item !== ""); // Remove empty values

    // Checkbox for tracking artwork IDs
    save_config.track_artwork_ids = document.getElementById("track_artwork_ids").checked;

    // Checkbox for saving artwork to Kometa asset directory
    save_config.save_to_kometa = document.getElementById("save_to_kometa").checked;

    // Checkbox for staging assets
    save_config.stage_assets = document.getElementById("stage_assets").checked;
    toggleScraperStageCheckbox();

    // Checkbox for staging specials
    save_config.stage_specials = document.getElementById("stage_specials").checked;

    // Checkbox for staging collections
    save_config.stage_collections = document.getElementById("stage_collections").checked;

    // Checkbox for managing bulk files
    save_config.auto_manage_bulk_files = document.getElementById("auto_manage_bulk_files").checked;

    // Checkbox for reset overlay for Kometa
    save_config.reset_overlay = document.getElementById("reset_overlay").checked;

    // Get selected mediux filters
    save_config.mediux_filters = Array.from(document.querySelectorAll('[id^="m_filter-"]:checked'))
        .map(checkbox => checkbox.value);

    // Get selected tpdb filters
    save_config.tpdb_filters = Array.from(document.querySelectorAll('[id^="p_filter-"]:checked'))
        .map(checkbox => checkbox.value);

    // Save schedules (Ensure it's an array)
    save_config.schedules = Array.isArray(schedules) ? schedules : [];

    // Authentication settings
    save_config.auth_enabled = document.getElementById("auth_enabled").checked;
    save_config.auth_username = document.getElementById("auth_username").value.trim();
    // Don't send password in save_config - it's handled separately

    // Check if we need to set a new password
    const newPassword = document.getElementById("auth_password").value;
    if (save_config.auth_enabled && newPassword) {
        // First set the password
        socket.emit("set_password", {
            instance_id: instanceId,
            username: save_config.auth_username,
            password: newPassword
        });
        // Clear the password field
        document.getElementById("auth_password").value = "";

        // Wait a moment then save config
        setTimeout(() => {
            socket.emit("save_config", {instance_id: instanceId, config: save_config});
        }, 500);
    } else {
        socket.emit("save_config", {instance_id: instanceId, config: save_config});
    }

    // Prevent duplicate event listeners
    socket.once("save_config", (data) => {
        if (validResponse(data)) {
            if (data.saved) {
                config = data.config;
                updateStatus("Configuration saved", "success", false, false, "check-circle");
                configureTabs(true);
            } else {
                updateStatus("Configuration could not be saved", "danger", false, false, "cross-circle");
                configureTabs(true);
            }
        }
    });
}


// Load configuration
function loadConfig() {
    socket.emit("load_config", {instance_id: instanceId});

    socket.once("load_config", (data) => { // Use 'once' to prevent duplicate listeners
        if (validResponse(data) && data.config) {
            config = data.config;
            document.getElementById("plex_base_url").value = data.config.base_url;
            document.getElementById("plex_token").value = data.config.token;
            document.getElementById("bulk_import_file").value = data.config.bulk_txt;
            document.getElementById("tv_library").value = data.config.tv_library.join(", ");
            document.getElementById("movie_library").value = data.config.movie_library.join(", ");
            document.getElementById("track_artwork_ids").checked = data.config.track_artwork_ids;
            document.getElementById("save_to_kometa").checked = data.config.save_to_kometa;
            document.getElementById("stage_assets").checked = data.config.stage_assets;
            document.getElementById("stage_specials").checked = data.config.stage_specials;
            document.getElementById("stage_collections").checked = data.config.stage_collections;
            document.getElementById("kometa_base").value = data.config.kometa_base;
            document.getElementById("temp_dir").value = data.config.temp_dir || "";
            document.getElementById("auto_manage_bulk_files").checked = data.config.auto_manage_bulk_files;
            document.getElementById("reset_overlay").checked = data.config.reset_overlay;
            document.getElementById("option-add-to-bulk").checked = data.config.auto_manage_bulk_files;

            // Load authentication settings
            document.getElementById("auth_enabled").checked = data.config.auth_enabled || false;
            document.getElementById("auth_username").value = data.config.auth_username || "";

            // Toggle Kometa settings visibility
            toggleKometaSettings();

            // Toggle auth settings visibility
            toggleAuthSettings();

            // Make sure Plex options visibility is set correctly on load
            togglePlexOptions();

            // Make sure temp option visibility is set correctly on load
            toggleTempCheckbox();

            // Make sure scraper stage option visibility is set correctly on load
            toggleScraperStageCheckbox();

            // Show/hide logout button based on auth enabled
            if (data.config.auth_enabled) {
                document.getElementById("logout-link").style.display = "block";
            } else {
                document.getElementById("logout-link").style.display = "none";
            }

            if (Array.isArray(data.config.mediux_filters)) {
                document.querySelectorAll('[id^="m_filter-"]').forEach(checkbox => {
                    checkbox.checked = data.config.mediux_filters.includes(checkbox.value);
                });
            }

            if (Array.isArray(data.config.tpdb_filters)) {
                document.querySelectorAll('[id^="p_filter-"]').forEach(checkbox => {
                    checkbox.checked = data.config.tpdb_filters.includes(checkbox.value);
                });
            }

            schedules = data.config.schedules;
            console.log(schedules);

            loadBulkFileList(); // For the switcher
            configureTabs();
        }
    });
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
        document.getElementById("yesButton").innerText = "Yes, save changes"
        document.getElementById("noButton").innerText = "No, lose changes"
        document.getElementById("cancelButton").innerText = "Cancel"

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
    const form = document.getElementById('scraperForm');
    const logTab = document.querySelector('#scraping-log-tab');

    // Check if the form is valid
    if (form.checkValidity()) {
        // Proceed with scraping if form is valid

        // Collect checked input fields with ids starting with "option-"
        let options = [];
        document.querySelectorAll('[id^="option-"]:checked').forEach(checkbox => {
            options.push(checkbox.value);
        });

        // Collect checked checkboxes with ids starting with "filter-"
        let filters = [];
        if (!document.getElementById("scraper-filters-global").checked) {
            document.querySelectorAll('[id^="filter-"]:checked').forEach(checkbox => {
                filters.push(checkbox.value);
            });
        }

        const year = document.getElementById("year").value;
        const url = document.getElementById("scrape_url").value;
        socket.emit("start_scrape", {
            url: url,
            year: year,
            options: options,
            filters: filters,
            instance_id: instanceId
        });
        // Switch to the log tab
        bootstrap.Tab.getOrCreateInstance(logTab).show();
    } else {
        // Trigger Bootstrap validation styles
        form.classList.add('was-validated');
    }
}

// Function to check for changes and enable/disable the save button
function updateBulkSaveButtonState() {

    const bulkTextArea = document.getElementById("bulk_import_text");
    const saveButton = document.getElementById("save_bulk_button");

    saveButton.disabled = bulkTextArea.value === bulkTextAsLoaded;
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

    // Define the regex pattern from the input
    const pattern = /^https:\/\/theposterdb\.com\/set\/\d+$/;

    // Validate the URL before showing elements
    if (pattern.test(url)) {
        elements.forEach(el => el.style.display = "block");
    } else {
        elements.forEach(el => {
            el.style.display = "none";
            // Uncheck checkboxes inside hidden elements
            el.querySelectorAll("input[type='checkbox']").forEach(checkbox => {
                checkbox.checked = false;
            });
        });
    }

}

// Run function on input change
if (scrapeUrlInput) {
    scrapeUrlInput.addEventListener("input", toggleThePosterDBElements);
}

function configureTabs(afterSave = false) {
    if (config.base_url && config.token) {
        document.getElementById('bulk-import-tab').classList.add("show");
        document.getElementById('scraper-tab').classList.add("show");
        document.getElementById('scraping-log-tab').classList.add("show");
        document.getElementById('uploader-tab').classList.add("show");
        if (!afterSave) {
            document.getElementById('config').classList.remove("show", "active");
            document.getElementById('config-tab').classList.remove("active");
            document.getElementById('scraper').classList.add("show", "active");
            document.getElementById('scraper-tab').classList.add("active");
        }
    }
}

/* Loading the bulk import file */

function loadBulkFile(bulkImport = null) {

    if (!bulkImport) {
        bulkImport = config.bulk_txt;
    }

    socket.emit("load_bulk_import", {instance_id: instanceId, filename: bulkImport});

    socket.once("load_bulk_import", (data) => {

        const textArea = document.getElementById("bulk_import_text");

        if (validResponse(data)) {

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
                //                    updateStatus("Bulk import file '" + data.filename + "' was loaded","success", false, false, "check-circle")
            } else {
                updateStatus("Bulk import file could not be loaded", "danger", false, false, "cross-circle")
            }


        }
    });

}

function checkBulkImportFileToSave() {

    saveBulkImport(currentBulkImport);

}

/* Loading the list of available bulk files */

function loadBulkFileList() {

    socket.emit("load_bulk_filelist", {instance_id: instanceId});

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
            if (data.saved === true) {
                loadBulkFileList();
                bulkTextAsLoaded = textArea.value
                updateBulkSaveButtonState()
                if (data.now_load) {
                    //console.log("Saved, now loading " + data.now_load)
                    loadBulkFile(data.now_load);
                }
            }
        }
    });
}

function runBulkImport() {
    const logTab = document.querySelector('#scraping-log-tab');
    // Switch to the log tab
    bootstrap.Tab.getOrCreateInstance(logTab).show();

    socket.emit("start_bulk_import", {
        instance_id: instanceId,
        bulk_list: document.getElementById("bulk_import_text").value,
        filename: currentBulkImport || document.getElementById("switch_bulk_file").value || "bulk_import.txt"
    });
}

// Validation

(function () {
    'use strict';
    // Fetch all forms we want to apply custom Bootstrap validation styles to
    const forms = document.querySelectorAll('.needs-validation');

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
        document.getElementById("scraper-filters").classList.add("show");
    }
}

function inheritGlobalFiltersForUploads() {
    if (document.getElementById("upload-filters-global").checked) {
        document.getElementById("upload-filters").classList.remove("show");
    } else {
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

            //console.log("Blur event triggered"); // Debugging line
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
        alert("You cannot delete the default bulk file.");
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
                        updateBulkSaveButtonState()
                    }
                }
            });
        }
    }
});

// Function to handle uploading a bulk file
document.getElementById("create_icon").addEventListener("click", function () {
    // Create a new bulk import file
    socket.emit("create_bulk_file", {instance_id: instanceId});

    socket.once("create_bulk_file", (data) => {
        if (data.created) {
            updateStatus("New bulk file created: " + data.filename, "success", false, false, "check-circle");
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
                //console.log("User chose not to overwrite the file.");
                return;
            }
        }

        // Proceed with reading and processing the file
        const reader = new FileReader();
        reader.onload = function (e) {
            const text = e.target.result;

            const bulkTextArea = document.getElementById("bulk_import_text");

            if (bulkTextArea.value !== bulkTextAsLoaded) {
                // If content has changed, show the modal
                saveBulkChangesModal(file.name).then((confirmed) => {
                    if (confirmed === "yes") {
                        saveBulkImport(currentBulkImport);
                    }

                    if (confirmed !== "cancel") {
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
    // Switch to the log tab
    const logTab = document.querySelector('#scraping-log-tab');
    bootstrap.Tab.getOrCreateInstance(logTab).show();

    socket.emit("display_message", {"message": `Uploading '${file.name}'...`, "title": "uploadFile"});

    const reader = new FileReader();

    let offset = 0;

    reader.onload = function (event) {
        const arrayBuffer = event.target.result;
        const totalChunks = Math.ceil(arrayBuffer.byteLength / CHUNK_SIZE);

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

                socket.emit("display_message", {
                    "message": `Successfully uploaded '${file.name}'`,
                    "title": "uploadFile"
                });
                socket.emit("upload_complete", {
                    instance_id: instanceId,
                    fileName: file.name,
                    options: options,
                    filters: filters,
                    plex_title: plex_title,
                    plex_year: plex_year
                });
                progress_bar(100, "Upload complete!");

                return; // Ensure no further execution in this function
            }

            const chunk = arrayBuffer.slice(offset, offset + CHUNK_SIZE);

            arrayBufferToBase64(chunk).then(base64Chunk => {
                socket.emit("upload_artwork_chunk", {
                    instance_id: instanceId,
                    fileName: file.name,
                    chunkData: base64Chunk,
                    chunkIndex: offset / CHUNK_SIZE,
                    totalChunks: totalChunks
                });

                offset += CHUNK_SIZE;
                let progress = Math.round((offset / arrayBuffer.byteLength) * 100);
                updateStatus(`Uploading '${file.name}'...`, "info", false, false, "cloud-upload");
                progress_bar(progress, `${progress}%`);

                if (offset < arrayBuffer.byteLength) {
                    setTimeout(sendChunk, 10);
                } else {
                    console.log("Final chunk sent, triggering upload_complete...");
                    sendChunk(); // This ensures the final event fires
                }
            });
        }

        sendChunk();
    };

    reader.readAsArrayBuffer(file);
}

socket.on("upload_progress", function (data) {
    if (validResponse(data)) {
        progress_bar(data.progress);
    }
});

socket.on("upload_complete", function (data) {
    if (validResponse(data)) {
        progress_bar(100, "Upload complete!");
    }
});

// =====================
// Scheduler
// =====================

function updateOrAddSchedule(fileName, newTime, jobReference = null) {
    const schedule = schedules.find(s => s.file === fileName);
    if (schedule) {
        schedule.time = newTime;
        schedule.jobReference = jobReference;
    } else {
        schedules.push({file: fileName, time: newTime});
    }
}

// Show the time selector when the clock icon is clicked
scheduleIcon.addEventListener("click", function () {

    const iconRect = scheduleIcon.getBoundingClientRect();

    // Position tooltip relative to the icon
    timeSelectBox.style.top = `${iconRect.bottom + window.scrollY + 10}px`; // Below the icon
    timeSelectBox.style.right = `${window.innerWidth - iconRect.right - window.scrollX - 15}px`; // Align right edge

    // Toggle visibility
    timeSelectBox.classList.toggle("show-tooltip");

});

document.addEventListener("click", function (event) {
    if (!timeSelectBox.contains(event.target) && !scheduleIcon.contains(event.target)) {
        timeSelectBox.classList.remove("show-tooltip");
    }
});

// Handle setting the time
setTimeBtn.addEventListener("click", function () {
    const selectedTime = scheduleTimeInput.value;
    if (selectedTime) {
        socket.emit("add_schedule", {instance_id: instanceId, file: currentBulkImport, time: selectedTime})

        // Wait for response on add schedule
        socket.once("add_schedule", (data) => {
            if (validResponse(data)) {
                if (data.added) {
                    updateOrAddSchedule(data.file, data.time, data.jobReference);
                    updateSchedulerIcon();
                    timeSelectBox.classList.remove("show-tooltip");
                }
            }
        });

    }
});

// Handle cancelling the schedule
cancelTimeBtn.addEventListener("click", function () {
    socket.emit("delete_schedule", {instance_id: instanceId, file: currentBulkImport})

    // Wait for response
    socket.once("delete_schedule", (data) => {
        if (validResponse(data)) {
            if (data.deleted) {
                // Get the value of the default bulk file from the hidden field
                console.log(schedules)
                updateOrAddSchedule(data.file, null, null)
                console.log(schedules)
                updateSchedulerIcon();
            } else {

            }
            timeSelectBox.classList.remove("show-tooltip");
        }
    });

});

function updateSchedulerIcon() {
    let details = getScheduleDetails(currentBulkImport);
    // console.log(schedules)
    if (details && details['time']) {
        scheduleIcon.classList.remove("bi-clock");
        scheduleIcon.classList.add("bi-clock-fill"); // Change to filled icon
        setContainer.classList.remove("show"); // Hide set button
        cancelContainer.classList.add("show"); // Show cancel button
        scheduleTimeInput.value = details['time'];
        scheduleTimeInput.readOnly = true;
        scheduleIcon.classList.add("text-success");
    } else {
        scheduleIcon.classList.add("bi-clock");
        scheduleIcon.classList.remove("bi-clock-fill"); // Change to filled icon
        scheduleIcon.classList.remove("text-success");
        setContainer.classList.add("show"); // Show set button
        cancelContainer.classList.remove("show"); // Hide cancel button
        scheduleTimeInput.value = "";
        scheduleTimeInput.readOnly = false;
    }
}

function getScheduleDetails(fileName) {
    return schedules.find(s => s.file === fileName);
}

// Check for update on page load
socket.emit("check_for_update", {instance_id: instanceId});

socket.on("update_available", function (data) {
    if (validResponse(data)) {
        updateLog("Update available: " + data.version, "info");
        document.getElementById("latest_version").innerText = data.version;
        document.getElementById("version_notifier").style.display = "block";
    }
});

function updateApp() {
    document.getElementById("version_notifier").style.display = "none";
    socket.emit("update_app", {instance_id: instanceId});
}

socket.on("update_failed", function (data) {
    alert("Update failed: " + data.error);
});


socket.on("backend_restarting", function () {
    console.log("Backend restarting, refreshing frontend too...");
    setTimeout(() => {
        location.reload();  // Reload the page
    }, 3000);  // Delay for 2 seconds to ensure restart
});

// Detect when the WebSocket connection is lost
socket.on("disconnect", function () {
    console.log("WebSocket disconnected, attempting to reconnect...");
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
// Kometa Settings Toggle
// ==================================================

function toggleKometaSettings() {
    const saveToKometa = document.getElementById("save_to_kometa").checked;
    const kometaSettings = document.getElementById("kometa_settings");
    const kometaBase = document.getElementById("kometa_base");
    if (saveToKometa) {
        kometaSettings.style.display = "block";
        if (kometaBase) {
            kometaBase.required = true;
            // Optionally clear any previous invalid state so the user can re-validate
            kometaBase.classList.remove('is-invalid');
        }
    } else {
        kometaSettings.style.display = "none";
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
            forceLabel.textContent = 'Force upload the artwork, even if it already exists';
            forceLabelUpload.textContent = 'Force upload the artwork, even if it already exists';
        }
    }

    // Check if temp option should be shown, the Plex options should be hidden, and the stage option in the scraper tab should be hidden
    toggleTempCheckbox();
    togglePlexOptions();
    toggleScraperStageCheckbox();
}

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
    const resetOverlay = document.getElementById("reset_overlay").parentElement;

    // Ony show the Track Artwork IDs and Reset Overlay options if Kometa is disabled
    if (!saveToKometa) {
        trackArtworkIDs.style.display = "block";
        resetOverlay.style.display = "block";
    } else {
        trackArtworkIDs.style.display = "none";
        resetOverlay.style.display = "none";
        document.getElementById("track_artwork_ids").checked = true;
        //    document.getElementById("reset_overlay").checked = false;
    }
}

// Add event listener for save_to_kometa checkbox
document.getElementById("save_to_kometa").addEventListener("change", toggleKometaSettings);

// Add event listener for temp_dir input to toggle temp option visibility
document.getElementById("temp_dir").addEventListener("input", toggleTempCheckbox);

// Add event listener for stage_assets checkbox
document.getElementById("stage_assets").addEventListener("change", toggleScraperStageCheckbox);
