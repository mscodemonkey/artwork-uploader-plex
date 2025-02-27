

        function generateUUID() {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }

        function getInstanceId() {
            let instanceId = localStorage.getItem("instanceId");
            if (!instanceId) {
                instanceId = crypto.randomUUID();
                localStorage.setItem("instanceId", instanceId);
            }
            return instanceId;
        }



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
                    console.warn(`Element with ID "${id}" not found.`);
                }
            });
        }

        let config = {};
        const socket = io();
        const instanceId = getInstanceId();
        let currentBulkImport;
        let statusTimeout; // Store timeout reference
        const bootstrapColors = ['primary', 'secondary', 'success', 'danger', 'warning', 'info', 'light', 'dark'];


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
                statusEl.classList.add(`text-bg-${color}`);
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


        function updateLog(message, color = null, artwork_title = null) {
            let statusElement = document.getElementById("session_log");

            // Get current timestamp
            let timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });

            // Prepend the new message with timestamp
            statusElement.innerHTML = '<div class="log_message">[' + timestamp +'] ' + message + '</div>' + statusElement.innerHTML;
        }

        // Modify your socket listener to check the message's tag or instanceId
        socket.on("element_disable", (data) => {
            if (data.instance_id === instanceId) {
                element_disable(data.element, data.mode);
            }
        });

        socket.on("status_update", (data) => {
            if (data.instance_id === "broadcast" || data.instance_id === instanceId) {
                updateStatus(data.message, data.color, data.sticky, data.spinner, data.icon);
            }
        });

        socket.on("log_update", (data) => {
            if (data.instance_id === "broadcast" || data.instance_id === instanceId) {
                updateLog(data.message, data.artwork_title);
            }
        });

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
            let regex = new RegExp(`^${urlWithoutFlag}(\\s+--\\S+(\\s+\\S+)*)?$`, "m");

            if (!regex.test(bulkText)) {
                document.getElementById("bulk_import_text").value += "\n// " + data.title + "\n" + urlWithoutFlag + "\n";
            }
        });


            document.getElementById("save_config_button").addEventListener("click", function(event) {

                event.preventDefault(); // Prevent actual form submission
                const form = document.getElementById("config_form"); // Replace with your actual form ID

                console.log("Saving...")

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

                } else {
                    form.classList.add("was-validated");
                }
            });

        socket.on("save_config", (data) => {
            if (data.saved) {
                updateStatus("Configuration saved","success", false, false, "check-circle")
            } else {
                updateStatus("Configuration could not be saved","danger", false, false, "cross-circle")
            }
        });

        document.getElementById("bulk_import_file").addEventListener("change", function () {
            const selectedFile = this.value; // Get selected file from dropdown
            if (!selectedFile) return; // Do nothing if no file is selected

            showLoadBulkImportModal(selectedFile).then((confirmed) => {
                if (confirmed) {
                    loadBulkImport(selectedFile);
                }
            });
        });

function showLoadBulkImportModal(filename) {
    return new Promise((resolve) => {
        const modalElement = document.getElementById("loadBulkImportModal");

        // Update modal message with selected filename
        document.getElementById("loadModalMessage").innerText = `Do you want to load "${filename}" now?`;

        // Show modal
        const modal = new bootstrap.Modal(modalElement);
        modal.show();

        // Handle button clicks
        document.getElementById("confirmLoad").onclick = () => {
            modal.hide();
            resolve(true);
        };

        document.getElementById("cancelLoad").onclick = () => {
            modal.hide();
            resolve(false);
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

        document.addEventListener("DOMContentLoaded", function () {

            updateLog("> New session started with ID: " + instanceId)

            loadConfig()

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
            const scrapeUrlInput = document.getElementById("scrape_url");
            if (scrapeUrlInput) {
                scrapeUrlInput.addEventListener("input", toggleThePosterDBElements);
            }

            // Run on page load (ensuring elements exist first)
            toggleThePosterDBElements();
        });

        function loadConfig() {
            socket.emit("load_config", { instance_id: instanceId });
        }

        socket.on("load_config", (data) => {
            if (data.instance_id === instanceId && data.config) {

                config = data.config;

                document.getElementById("plex_base_url").value = data.config.base_url
                document.getElementById("plex_token").value = data.config.token
                loadBulkFileList()
                document.getElementById("tv_library").value = data.config.tv_library.join(", ")
                document.getElementById("movie_library").value = data.config.movie_library.join(", ")
                document.getElementById("track_artwork_ids").checked = data.config.track_artwork_ids
                document.querySelectorAll('[id^="m_filter-"]').forEach(checkbox => {
                    checkbox.checked = data.config.mediux_filters.includes(checkbox.value);
                });
                document.querySelectorAll('[id^="p_filter-"]').forEach(checkbox => {
                    checkbox.checked = data.config.tpdb_filters.includes(checkbox.value);
                });
            }
        });

        function loadBulkImport(bulkImport = null) {
            if (!bulkImport) {bulkImport = config.bulk_txt;}
            console.log(bulkImport)
            socket.emit("load_bulk_import", { instance_id: instanceId, filename: bulkImport });
        }

        socket.on("load_bulk_import", (data) => {
            console.log(data.instance_id, instanceId)
            if (data.instance_id === instanceId) {
                if (data.loaded) {
                    const textArea = document.getElementById("bulk_import_text");
                    textArea.value = data.bulk_import_text;
                    updateStatus("Bulk import file '" + data.filename + "' was loaded","success", false, false, "check-circle")
                } else {
                    updateStatus("Bulk import file could not be loaded","danger", false, false, "cross-circle")
                }
            }
        });

        function checkBulkImportFileToSave() {
            let filename = document.getElementById("bulk_import_file").value;

            if (currentBulkImport && (filename !== currentBulkImport.name)) {

                // Show modal and wait for user choice
                showSaveBulkImportModal(currentBulkImport.name, filename).then((choice) => {
                    filename = choice;
                    console.log("User choice was : " + filename);

                    // Call the function that saves the file here if needed
                    saveBulkImport(filename);
                });
            } else {
                saveBulkImport(filename);
            }
        }

        function loadBulkFileList() {
            socket.emit("load_bulk_filelist", { instance_id: instanceId });
        }

        socket.on("load_bulk_filelist", (data) => {
            if (data.instance_id === instanceId) {
                const selectElement = document.getElementById("bulk_import_file");

                // Clear existing options
                selectElement.innerHTML = "";

                let selectedFile = config.bulk_txt || ""; // Get the selected file from config

                if (data.bulk_files.length > 0) {
                    // Populate the dropdown with filenames
                    data.bulk_files.forEach(filename => {
                        const option = document.createElement("option");
                        option.value = filename;
                        option.textContent = filename;

                        // Preselect the option if it matches the config.bulk_txt value
                        if (filename === selectedFile) {
                            option.selected = true;
                            if (!document.getElementById("bulk_import_text").value) {loadBulkImport(filename)}
                        }
                        selectElement.appendChild(option);
                   });
                } else {
                    // Show placeholder when no files exist
                    const placeholder = document.createElement("option");
                    placeholder.disabled = true;
                    placeholder.selected = true;
                    placeholder.value = "bulk_import.txt"
                    placeholder.textContent = "Will create bulk_import.txt when saved";
                    selectElement.appendChild(placeholder);
                }
            }
        });

        function saveBulkImport(filename) {
            console.log("File to save is: " + filename);
            const textArea = document.getElementById("bulk_import_text");

            const fileData = {
                filename: filename,
                content: textArea.value
            };

            // Emit the event to Flask via Socket.IO
            socket.emit("save_bulk_import", fileData);
        }

        function uploadBulkImportFile(event) {

            const fileInput = event.target;
            const fileName = fileInput.files.length > 0 ? fileInput.files[0].name : "Upload a file";
            document.getElementById("bulk_import_label").innerText = fileName;

            const file = event.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = function(e) {
                    document.getElementById("bulk_import_text").value = e.target.result;
                };
                reader.readAsText(file);
                currentBulkImport = file.name
            } else {
                console.error("No file selected");
            }
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

        function showSaveBulkImportModal(current_bulk_import, default_bulk_import) {
            return new Promise((resolve) => {
        const modalElement = document.getElementById("saveBulkImportModal");

        // Update modal text with variable values
        document.getElementById("saveModalMessage").innerText = `Do you want to save as "${currentBulkImport}" rather than "${default_bulk_import}"?`;
        document.getElementById("currentFileName").innerText = currentBulkImport;
        document.getElementById("defaultFileName").innerText = default_bulk_import;

        // Show modal
        const modal = new bootstrap.Modal(modalElement);
        modal.show();

        // Handle button clicks
        document.getElementById("saveAsCurrent").onclick = () => {
            modal.hide();
            resolve(currentBulkImport);
        };

        document.getElementById("useDefault").onclick = () => {
            modal.hide();
            resolve(default_bulk_import);
        };
    });
}


