
// ==================================================
// App initialisation and startup
// ==================================================

let config = {};
let statusTimeout; // Store timeout reference
const socket = io();
const instanceId = getInstanceId();
const scrapeUrlInput = document.getElementById("scrape_url");
const bootstrapColors = ['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'];


document.addEventListener("DOMContentLoaded", function () {
    updateLog("> New session started with ID: " + instanceId)
    loadConfig()
    toggleThePosterDBElements();
});


function generateUUID() {
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

function getInstanceId() {
    let instanceId = localStorage.getItem("instanceId");
    if (!instanceId) {
        instanceId = generateUUID();
        localStorage.setItem("instanceId", instanceId);
    }
    return instanceId;
}

// ==================================================
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
    if (data.instance_id === instanceId) {
        element_disable(data.element, data.mode);
    }
});
// ==================================================


// ==================================================
function updateStatus(message, color = "info", sticky = false, spinner = false, icon = false) {

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
    if (data.instance_id === "broadcast" || data.instance_id === instanceId) {
        updateStatus(data.message, data.color, data.sticky, data.spinner, data.icon);
    }
});
// ==================================================


// ==================================================
function updateLog(message, color = null, artwork_title = null) {
    let statusElement = document.getElementById("session_log");

    // Get current timestamp
    let timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });

    // Prepend the new message with timestamp
    statusElement.innerHTML = '<div class="log_message">[' + timestamp +'] ' + message + '</div>' + statusElement.innerHTML;
}
socket.on("log_update", (data) => {
    if (data.instance_id === "broadcast" || data.instance_id === instanceId) {
        updateLog(data.message, data.artwork_title);
    }
});
// ==================================================


socket.on("progress_bar", (data) => {

    const bar_container = document.getElementById("progress_bar_container")
    const bar = document.getElementById("progress_bar")
    if (data.percent <= 100) {
        bar_container.classList.add("show")
        bar.style.width = data.percent + "%"
        bar_container.ariaValueNow = data.message
        bar.innerHTML = data.message || ""

        if (data.percent == 100) {
            barTimer = setTimeout(() => {
                bar_container.classList.remove('show'); // Fade out the progress bar after a second
            }, 1000);
        }
    }
})


socket.on("add_to_bulk_list", (data) => {
    let bulkText = document.getElementById("bulk_import_text").value;
    let urlWithoutFlag = data.url.replace(" --add-to-bulk", "").trim();

    // Regex to match the URL as part of a line, even if extra arguments and values exist
    let regex = new RegExp("^${urlWithoutFlag}(\\s+--\\S+(\\s+\\S+)*)?$", "m");

    if (!regex.test(bulkText)) {
        document.getElementById("bulk_import_text").value += "\n// " + data.title + "\n" + urlWithoutFlag + "\n";
    }
});



// ==================================================
// Save configuration
// ==================================================

// Button handler
document.getElementById("save_config_button").addEventListener("click", function(event) {
    event.preventDefault(); // Prevent actual form submission
    saveConfig();
});

// Save configuration
function saveConfig() {

    const form = document.getElementById("config_form");

    if (form.checkValidity()) {
        // Form is valid, proceed with saving config
        const save_config = {};

        save_config.base_url = document.getElementById("plex_base_url").value.trim();
        save_config.token = document.getElementById("plex_token").value.trim();
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

        // Get selected mediux filters
        save_config.mediux_filters = Array.from(document.querySelectorAll('[id^="m_filter-"]:checked'))
            .map(checkbox => checkbox.value);

        // Get selected tpdb filters
        save_config.tpdb_filters = Array.from(document.querySelectorAll('[id^="p_filter-"]:checked'))
            .map(checkbox => checkbox.value);

        socket.emit("save_config", { instance_id: instanceId, config: save_config });

        socket.on("save_config", (data) => {
            if (data.saved) {
                updateStatus("Configuration saved","success", false, false, "check-circle")
            } else {
                updateStatus("Configuration could not be saved","danger", false, false, "cross-circle")
            }
        });

    } else {
        form.classList.add("was-validated");
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
    var form = document.getElementById('scraperForm');

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
        document.querySelectorAll('[id^="filter-"]:checked').forEach(checkbox => {
            filters.push(checkbox.value);
        });

        const url = document.getElementById("scrape_url").value;
        socket.emit("start_scrape", { url: url, options: options, filters: filters, instance_id: instanceId });
    } else {
        // Trigger Bootstrap validation styles
        form.classList.add('was-validated');
    }
}

/* Check whether bulk import has been edited and enable the button if it has */

// Function to check for changes and enable/disable the save button
function checkBulkTextChanged() {
    const bulkTextArea = document.getElementById("bulk_import_text");
    const saveButton = document.getElementById("save_bulk_button");

    if (bulkTextArea.value !== bulkTextAsLoaded) {
        saveButton.disabled = false; // Enable button if text has changed
    } else {
        saveButton.disabled = true;  // Disable button if no changes
    }
}

// Attach event listener to track changes
document.getElementById("bulk_import_text").addEventListener("input", checkBulkTextChanged);



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


function loadConfig() {
    socket.emit("load_config", { instance_id: instanceId });
}

socket.on("load_config", (data) => {
    if (data.instance_id === instanceId && data.config) {
        config = data.config;
        document.getElementById("plex_base_url").value = data.config.base_url
        document.getElementById("plex_token").value = data.config.token
        document.getElementById("bulk_import_file").value = data.config.bulk_txt
        document.getElementById("tv_library").value = data.config.tv_library.join(", ")
        document.getElementById("movie_library").value = data.config.movie_library.join(", ")
        document.getElementById("track_artwork_ids").checked = data.config.track_artwork_ids
        document.querySelectorAll('[id^="m_filter-"]').forEach(checkbox => {
            checkbox.checked = data.config.mediux_filters.includes(checkbox.value);
        });
        document.querySelectorAll('[id^="p_filter-"]').forEach(checkbox => {
            checkbox.checked = data.config.tpdb_filters.includes(checkbox.value);
        });
        loadBulkFileList(); // For the switcher
    }
});


/* Loading the bulk import file */

function loadBulkImport(bulkImport = null) {
    if (!bulkImport) {bulkImport = config.bulk_txt;}
    console.log("Loading bulk file - " + bulkImport)
    socket.emit("load_bulk_import", { instance_id: instanceId, filename: bulkImport });
}

socket.on("load_bulk_import", (data) => {

    const textArea = document.getElementById("bulk_import_text");
    console.log("Loader complete, returned " + data.loaded + " / " + data.filename + " / " + data.bulk_import_text)
    if (data.instance_id === instanceId) {
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

            checkBulkTextChanged();
            //                    updateStatus("Bulk import file '" + data.filename + "' was loaded","success", false, false, "check-circle")
        } else {
            updateStatus("Bulk import file could not be loaded","danger", false, false, "cross-circle")
        }
    }
});

function checkBulkImportFileToSave() {

    saveBulkImport(currentBulkImport);

}



/* Loading the list of available bulk files */

function loadBulkFileList() {
    socket.emit("load_bulk_filelist", { instance_id: instanceId });

    socket.on("load_bulk_filelist", (data) => {
        if (data.instance_id === instanceId) {
            const selectElements = document.querySelectorAll(".bulk_import_file"); // Select all matching elements

            let selectedFile = currentBulkImport || config.bulk_txt; // Get the selected file from config

            selectElements.forEach((selectElement) => {
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
                                loadBulkImport(filename);
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
            });
        }
    });
}

function saveBulkImport(filename, nowLoad = null) {

    console.log("File to save is: " + filename);
    const textArea = document.getElementById("bulk_import_text");

    const fileData = {
        filename: filename,
        content: textArea.value,
        now_load: nowLoad

    };

    // Emit the event to Flask via Socket.IO
    socket.emit("save_bulk_import", fileData);

    // And wait for a response
    socket.on("save_bulk_import", data => {
        if (data.instance_id === instanceId) {
            if (data.saved == true) {
                loadBulkFileList();
                if (data.now_load) {
                    console.log("Saved, now loading " + data.now_load)
                    loadBulkImport(data.now_load);
                }
            }
        }
    });
}





function runBulkImport() {
    socket.emit("start_bulk_import",{instance_id: instanceId, bulk_list: document.getElementById("bulk_import_text").value});
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
let currentBulkImport = '';
let bulkTextAsLoaded = '';

// Function to handle changing the bulk import file
document.getElementById("switch_bulk_file").addEventListener("change", function () {
    const selectedFile = this.value;
    if (!selectedFile) return; // Do nothing if no file is selected

    const bulkTextArea = document.getElementById("bulk_import_text");

    if (bulkTextArea.value !== bulkTextAsLoaded) {
        // If content has changed, show the modal
        saveBulkChangesModal(selectedFile).then((confirmed) => {
            if (confirmed === "yes") {
                saveBulkImport(currentBulkImport, selectedFile);
            } else if (confirmed === "no") {
                loadBulkImport(selectedFile);
            }
        });
    } else {
        // If no changes, just load the new file
        loadBulkImport(selectedFile);
    }

    // Handle default checkbox when the file is selected
    const bulkImportFileField = document.getElementById("bulk_import_file");
    const defaultCheckbox = document.getElementById("default_bulk_file");
    const defaultIcon = document.getElementById("default_bulk_file_icon");

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
});

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

            console.log("Blur event triggered"); // Debugging line
            const newFilename = renameInput.value + ".txt"; // Ensure .txt is appended
            if (newFilename && newFilename !== filename) {
                // Emit rename event
                socket.emit("rename_bulk_file", {
                    instance_id: instanceId,
                    old_filename: filename,
                    new_filename: newFilename
                });

                // Wait for response
                socket.on("rename_bulk_file", (data) => {
                    if (instanceId == data.instance_id) {
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
            socket.on("delete_bulk_file", (data) => {
                if (instanceId == data.instance_id) {
                    if (data.deleted) {
                        currentBulkImport = null
                        loadBulkFileList(); // Reload the file list if deleted
                    }
                }
            });
        }
    }
});


// Function to handle uploading a bulk file
document.getElementById("upload_icon").addEventListener("click", function () {
    document.getElementById("bulk_import_upload").click(); // Trigger file input click
});

function uploadBulkImportFile(event) {

    //        const fileInput = event.target;
    //        const fileName = fileInput.files.length > 0 ? fileInput.files[0].name : "Upload a file";
    //        document.getElementById("bulk_import_label").innerText = fileName;

    const file = event.target.files[0];
    if (file && file.name.endsWith('.txt')) {
        const reader = new FileReader();
        reader.onload = function(e) {
            const text = e.target.result;
            document.getElementById("bulk_import_text").value = text;
            currentBulkImport = file.name
            saveBulkImport(file.name);
            //               socket.emit("upload_bulk_file", { filename: file.name, content: text });
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




