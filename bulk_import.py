import notifications
import os

class BulkImport:

    def __init__(self, filename):
        self.filename = filename



    # * Bulk import file I/O functions ---
    def load_bulk_import_file(instance_id, filename=None):

        """Load the bulk import file into the text area."""

        global config

        try:
            # Get the current bulk_txt value from the config
            bulk_import_filename = filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt"
            bulk_imports_path = "bulk_imports/"

            # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
            bulk_import_file = os.path.join(get_exe_dir(), bulk_imports_path, bulk_import_filename)

            if not os.path.exists(bulk_import_file):
                if mode == "cli":
                    print(f"File does not exist: {bulk_import_file}")
                if mode == "web":
                    update_status(instance_id, f"File does not exist: {bulk_import_file}")
                return

            with open(bulk_import_file, "r", encoding="utf-8") as file:
                content = file.read()

            if mode == "web":
                notify_web(instance_id, "load_bulk_import", {"loaded": True, "filename": bulk_import_filename, "bulk_import_text": content})

        except FileNotFoundError:
            notify_web(instance_id, "load_bulk_import", {"loaded": False})
        except Exception as e:
            notify_web(instance_id, "load_bulk_import", {"loaded": False})

    def rename_bulk_import_file(instance_id, old_name, new_name):

        bulk_imports_path = "bulk_imports/"

        print(f"{old_name}, {new_name}")

        if old_name != new_name:
            try:

                # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
                old_filename = os.path.join(get_exe_dir(), bulk_imports_path, old_name)
                new_filename = os.path.join(get_exe_dir(), bulk_imports_path, new_name)
                os.rename(old_filename, new_filename)

                notify_web(instance_id, "rename_bulk_file", {"renamed": True, "old_filename": old_name, "new_filename": new_name})
                update_status(instance_id, f"Renamed to {new_name}", "success")
            except Exception as e:
                print(e)
                notify_web(instance_id, "rename_bulk_file", {"renamed": False, "old_filename": old_name})
                update_status(instance_id, f"Could not rename {old_name}", "warning")

    def delete_bulk_import_file(instance_id, file_name):

        bulk_imports_path = "bulk_imports/"

        if file_name:
            try:

                # Use get_exe_dir() to determine the correct path for both frozen and non-frozen cases
                filename = os.path.join(get_exe_dir(), bulk_imports_path, file_name)
                os.remove(filename)

                notify_web(instance_id, "delete_bulk_file", {"deleted": True, "filename": file_name})
                update_status(instance_id, f"Deleted {file_name}", "success")
            except Exception as e:
                print(e)
                notify_web(instance_id, "delete_bulk_file", {"deleted": False, "filename": file_name})
                update_status(instance_id, f"Could not delete {file_name}", "warning")

    def save_bulk_import_file(instance_id, contents=None, filename=None, now_load=None):
        """Save the bulk import text area content to a file relative to the executable location."""

        if contents:
            try:
                exe_path = get_exe_dir()
                bulk_import_path = "bulk_imports/"
                bulk_import_file = os.path.join(exe_path, bulk_import_path, filename if filename is not None else config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

                os.makedirs(os.path.dirname(bulk_import_file), exist_ok=True)

                print("Saving" + bulk_import_file)

                with open(bulk_import_file, "w", encoding="utf-8") as file:
                    file.write(contents)

                update_status(instance_id, message="Bulk import file " + filename + " saved", color="success")
                notify_web(instance_id, "save_bulk_import", {"saved": True, "now_load": now_load})
            except Exception as e:
                update_status(instance_id, message="Error saving bulk import file", color="danger")
                notify_web(instance_id, "save_bulk_import", {"saved": False, "now_load": now_load})

    def check_for_bulk_import_file(instance_id):
        """Check if any .txt files exist in the bulk_imports folder before creating bulk_import.txt."""
        contents = "## This is a blank bulk import file\n// You can use comments with # or // like this"

        try:
            exe_path = get_exe_dir()
            bulk_import_path = os.path.join(exe_path, "bulk_imports")
            bulk_import_file = os.path.join(bulk_import_path, config.bulk_txt if config.bulk_txt is not None else "bulk_import.txt")

            # Firstly, make sure the bulk_imports folder exists
            os.makedirs(bulk_import_path, exist_ok=True)

            # And that the default bulk file doesn't exist...
            if not os.path.isfile(bulk_import_file):
                with open(bulk_import_file, "w", encoding="utf-8") as file:
                    file.write(contents)

        except Exception as e:
            update_status(instance_id, message="Error creating bulk import file", color="danger")
