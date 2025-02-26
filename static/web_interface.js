
        const socket = io();

        function generateUUID() {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                var r = Math.random() * 16 | 0, v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        }

        const instance_id = generateUUID();

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


        function updateLog(message, color = null) {
            let statusElement = document.getElementById("session_log");

            // Get current timestamp
            let timestamp = new Date().toLocaleTimeString("en-GB", { hour12: false });

            // Prepend the new message with timestamp
            statusElement.innerHTML = '<div class="log_message">[' + timestamp +'] ' + message + '</div>' + statusElement.innerHTML;
        }

        // Modify your socket listener to check the message's tag or instanceId
        socket.on("element_disable", (data) => {
            if (data.instance_id === "broadcast" || data.instance_id === instance_id) {
                element_disable(data.element, data.mode);
            }
        });

        socket.on("status_update", (data) => {
            if (data.instance_id === "broadcast" || data.instance_id === instance_id) {
                updateStatus(data.message, data.color, data.sticky, data.spinner, data.icon);
            }
        });

        socket.on("log_update", (data) => {
            if (data.instance_id === "broadcast" || data.instance_id === instance_id) {
                updateLog(data.message);
            }
        });

            document.getElementById("save_config_button").addEventListener("click", function(event) {

                event.preventDefault(); // Prevent actual form submission
                const form = document.getElementById("config_form"); // Replace with your actual form ID

                console.log("Saving...")

                if (form.checkValidity()) {
                    // Form is valid, proceed with saving config
                    const config = {};

                    config.base_url = document.getElementById("plex_base_url").value.trim();
                    config.token = document.getElementById("plex_token").value.trim();
                    config.bulk_txt = document.getElementById("bulk_import_file").value.trim();

                    // Convert comma-separated library inputs to arrays
                    config.tv_library = document.getElementById("tv_library").value
                        .split(",")
                        .map(item => item.trim())
                        .filter(item => item !== ""); // Remove empty values

                    config.movie_library = document.getElementById("movie_library").value
                        .split(",")
                        .map(item => item.trim())
                        .filter(item => item !== ""); // Remove empty values

                    // Checkbox for tracking artwork IDs
                    config.track_artwork_ids = document.getElementById("track_artwork_ids").checked;

                    // Get selected mediux filters
                    config.mediux_filters = Array.from(document.querySelectorAll('[id^="m_filter-"]:checked'))
                        .map(checkbox => checkbox.value);

                    // Get selected tpdb filters
                    config.tpdb_filters = Array.from(document.querySelectorAll('[id^="p_filter-"]:checked'))
                        .map(checkbox => checkbox.value);

                    console.log("Really saving" + config)

                    socket.emit("save_config", { instance_id: instance_id, config: config });

                } else {
                    form.classList.add("was-validated");
                }
            });


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
                socket.emit("start_scrape", { url: url, options: options, filters: filters, instance_id: instance_id });
            } else {
                // Trigger Bootstrap validation styles
                form.classList.add('was-validated');
            }
        }

        document.addEventListener("DOMContentLoaded", function () {

            updateLog("> New session started with ID: " + instance_id)

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
            socket.emit("load_config", { instance_id: instance_id });
        }

        socket.on("load_config", (data) => {
            if (data.instance_id === instance_id) {
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
            }
        });




        function saveBulkImport() {
            const content = document.getElementById("bulk_import_text").value;
            socket.emit("save_bulk_import", { content: content });
        }

        function uploadBulkImportFile(event) {
            const file = event.target.files[0];
            if (file) {
                console.log("File selected:", file.name); // Debugging
                const reader = new FileReader();
                reader.onload = function(e) {
                    document.getElementById("bulk_import_text").value = e.target.result;
                };
                reader.readAsText(file);
            } else {
                console.error("No file selected");
            }
        }

        function runBulkImport() {
            socket.emit("start_bulk_import",{instance_id: instance_id, bulk_list: document.getElementById("bulk_import_text").value});
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
