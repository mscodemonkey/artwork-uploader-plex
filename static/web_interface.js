
// ==================================================
// App initialisation and startup
// ==================================================

let config = {};
let statusTimeout; // Store timeout reference
let schedules = [];
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
    let statusElement = document.getElementById("scraping_log");

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


    checkBulkTextChanged();

});


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

        // Checkbox for managing bulk files
        save_config.auto_manage_bulk_files = document.getElementById("auto_manage_bulk_files").checked;

        // Get selected mediux filters
        save_config.mediux_filters = Array.from(document.querySelectorAll('[id^="m_filter-"]:checked'))
            .map(checkbox => checkbox.value);

        // Get selected tpdb filters
        save_config.tpdb_filters = Array.from(document.querySelectorAll('[id^="p_filter-"]:checked'))
            .map(checkbox => checkbox.value);

        // Save schedules
        save_config.schedules = schedules;

        socket.emit("save_config", { instance_id: instanceId, config: save_config });

        socket.on("save_config", (data) => {
            if (data.saved) {
                config = data.config;
                updateStatus("Configuration saved","success", false, false, "check-circle")
                configureTabs(true);
            } else {
                updateStatus("Configuration could not be saved","danger", false, false, "cross-circle")
                configureTabs(true);
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

        const year = document.getElementById("year").value;
        const url = document.getElementById("scrape_url").value;
        socket.emit("start_scrape", { url: url, year: year, options: options, filters: filters, instance_id: instanceId });
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
        document.getElementById("auto_manage_bulk_files").checked = data.config.auto_manage_bulk_files
        document.getElementById("option-add-to-bulk").checked = data.config.auto_manage_bulk_files
        document.querySelectorAll('[id^="m_filter-"]').forEach(checkbox => {
            checkbox.checked = data.config.mediux_filters.includes(checkbox.value);
        });
        document.querySelectorAll('[id^="p_filter-"]').forEach(checkbox => {
            checkbox.checked = data.config.tpdb_filters.includes(checkbox.value);
        });
        schedules = data.config.schedules;

        console.log(schedules);

        loadBulkFileList(); // For the switcher
        configureTabs();
    }
});

function configureTabs(afterSave = false) {
        if (config.base_url && config.token) {
            document.getElementById('bulk-import-tab').classList.add("show");
            document.getElementById('scraper-tab').classList.add("show");
            document.getElementById('scraping-log-tab').classList.add("show");
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

function loadBulkImport(bulkImport = null) {
    if (!bulkImport) {bulkImport = config.bulk_txt;}
    // console.log("Loading bulk file - " + bulkImport)
    socket.emit("load_bulk_import", { instance_id: instanceId, filename: bulkImport });
}

socket.on("load_bulk_import", (data) => {

    const textArea = document.getElementById("bulk_import_text");
    // console.log("Loader complete, returned " + data.loaded + " / " + data.filename + " / " + data.bulk_import_text)
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
            handleDefaultCheckbox();
            setupSchedulerIcon();
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
    socket.on("save_bulk_import", data => {
        if (data.instance_id === instanceId) {
            if (data.saved == true) {
                loadBulkFileList();
                bulkTextAsLoaded = textArea.value
                checkBulkTextChanged()
                if (data.now_load) {
                    //console.log("Saved, now loading " + data.now_load)
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
            } else if (confirmed === "cancel") {
                // User canceled, revert to previous selection
                this.value = currentBulkImport;
                handleDefaultCheckbox()
            }
        });
    } else {
        // If no changes, just load the new file
        loadBulkImport(selectedFile);
    }



});


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
                        // Get the value of the default bulk file from the hidden field
                        const defaultBulkFile = document.getElementById("bulk_import_file").value;
                        currentBulkImport = null
                        bulkTextAsLoaded = null
                        loadBulkFileList(); // Reload the file list if deleted
                        loadBulkImport(defaultBulkFile);
                        checkBulkTextChanged()
                    }
                }
            });
        }
    }
});


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

        // Save the configuration change
        saveConfig();
    }
});

// Drag and drop

        const dropArea = document.getElementById("drop-area");
        const progressContainer = document.getElementById("progress-container");
        const progressBar = document.getElementById("progress-bar");
        const progressText = document.getElementById("progress-text");


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
            if (file && file.name.endsWith(".zip")) {
                uploadFile(file);
            } else {
                alert("Please drop a valid ZIP file.");
            }
        });

        dropArea.addEventListener("click", () => {
            let input = document.createElement("input");
            input.type = "file";
            input.accept = ".zip";
            input.onchange = (e) => {
                let file = e.target.files[0];
                if (file) uploadFile(file);
            };
            input.click();
        });


const CHUNK_SIZE = 1024 * 64; // 64 KB per chunk

function uploadFile(file) {
    const reader = new FileReader();
    let offset = 0; // Track progress

    reader.onload = function (event) {
        const arrayBuffer = event.target.result;
        const totalChunks = Math.ceil(arrayBuffer.byteLength / CHUNK_SIZE);

        function sendChunk() {
            progressContainer.style.display = "block"
            if (offset >= arrayBuffer.byteLength) {
                socket.emit("upload_complete", { fileName: file.name });
                return;
            }


            const chunk = arrayBuffer.slice(offset, offset + CHUNK_SIZE);
            const base64Chunk = btoa(String.fromCharCode(...new Uint8Array(chunk)));

         //   socket.emit("upload_artwork_chunk", {message:"Working"})

            socket.emit("upload_artwork_chunk", {
                instance_id: instanceId,
                fileName: file.name,
                chunkData: base64Chunk,
                chunkIndex: offset / CHUNK_SIZE,
                totalChunks: totalChunks
            });

            offset += CHUNK_SIZE;
            let progress = Math.round((offset / arrayBuffer.byteLength) * 100);

            progressBar.style.width = progress + "%";
            progressText.textContent = progress + "%";
            setTimeout(sendChunk, 10); // Avoid blocking the event loop
        }

        sendChunk();
    };

    reader.readAsArrayBuffer(file);
}

        socket.on("upload_progress", function (data) {
            let percent = data.progress;
            progressBar.style.width = percent + "%";
            progressText.textContent = percent + "%";
        });

        socket.on("upload_complete", function (data) {
            progressBar.style.width = "100%";
            progressText.textContent = "Upload complete!";
            setTimeout(() => progressContainer.style.display = "none", 2000);
        });


// =====================
// Scheduler
// =====================


    const scheduleIcon = document.getElementById("schedule_icon");
    const setTimeBtn = document.getElementById("set_time");
    const cancelTimeBtn = document.getElementById("cancel_time");
    const cancelContainer = document.getElementById("cancel_container");
    const scheduleTimeInput = document.getElementById("schedule_time");
    const timeSelectBox = document.getElementById("time_select_box");

    function updateOrAddSchedule(fileName, newTime, jobReference = null) {
        const schedule = schedules.find(s => s.file === fileName);
        if (schedule) {
            schedule.time = newTime;
            schedule.jobReference = jobReference;
        } else {
            schedules.push({ file: fileName, time: newTime });
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
            socket.emit("add_schedule",{instance_id:instanceId, file: currentBulkImport, time: selectedTime})
        }
    });

    // Handle cancelling the schedule
    cancelTimeBtn.addEventListener("click", function () {
        socket.emit("delete_schedule",{instance_id:instanceId, file: currentBulkImport})
    });



    // Wait for response on add schedule
    socket.on("add_schedule", (data) => {
        if (instanceId == data.instance_id) {
            if (data.added) {
                updateOrAddSchedule(data.file, data.time, data.jobReference);
                setupSchedulerIcon();
                timeSelectBox.classList.remove("show-tooltip");
            }
        }
    });

    // Wait for response
    socket.on("delete_schedule", (data) => {
        if (instanceId == data.instance_id) {
            if (data.deleted) {
                // Get the value of the default bulk file from the hidden field
                console.log(schedules)
                updateOrAddSchedule(data.file, null, null)
                console.log(schedules)
                setupSchedulerIcon();
            } else {

            }
        timeSelectBox.classList.remove("show-tooltip");
        }
    });


    function setupSchedulerIcon(){
        let details = getScheduleDetails(currentBulkImport);
        // console.log(schedules)
        if (details && details['time']) {
            scheduleIcon.classList.remove("bi-clock");
            scheduleIcon.classList.add("bi-clock-fill"); // Change to filled icon
            cancelContainer.style.display = "inline-block"; // Show cancel button
            scheduleTimeInput.value = details['time']
            scheduleIcon.classList.add("text-success")
        } else {
            scheduleIcon.classList.add("bi-clock");
            scheduleIcon.classList.remove("bi-clock-fill"); // Change to filled icon
            scheduleIcon.classList.remove("text-success")
            scheduleTimeInput.value = ""
            cancelContainer.style.display = "none"; // Hide cancel button
        }
    }

    function getScheduleDetails(fileName) {
        return schedules.find(s => s.file === fileName);
    }
