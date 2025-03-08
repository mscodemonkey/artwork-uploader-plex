import time
import utils
from options import Options

class PlexUploader:

    def __init__(self, upload_target, artwork_type, artwork_id):
        self.upload_target = upload_target
        self.artwork_type = artwork_type
        self.artwork_id = artwork_id.upper() + "ID:"  # This will be BID, CID, PID, SID or EID - for [B]ackgrounds, show [C]overs, [P]osters, [S]eason covers or [T]itle cards for [E]pisodes
        self.description = "item"
        self.label = None
        self.artwork = None
        self.options = Options()
        self.type = None
        self.track_artwork_ids = True

    def set_artwork(self, artwork):
        self.artwork = artwork
        if artwork['id'] == "Upload":
            self.type = "file"
            self.label = self.artwork_id + artwork['checksum']
        else:
            self.type = "url"
            self.label = self.artwork_id + utils.calculate_md5(self.artwork["url"])

    def set_description(self, description):
        self.description = description

    def set_options(self, options):
        if isinstance(options, Options):
            self.options = options

    def upload_to_plex(self):
        try:
            if self.artwork_exists_on_plex() is False or self.options.force:
                if self.artwork_id == "BID:":
                    if self.type == "file":
                        self.upload_target.uploadPoster( filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadPoster( url = self.artwork["url"])
                else:
                    if self.type == "file":
                        self.upload_target.uploadPoster( filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadPoster( url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)
                if self.artwork["source"] == "theposterdb":
                    time.sleep(6)
                return f'✓ {self.description} | {self.artwork_type} {"forced update" if self.options.force else "updated"} in {self.upload_target.librarySectionTitle}'
            else:
                return f'- {self.description} | {self.artwork_type} unchanged in {self.upload_target.librarySectionTitle}'
        except Exception as e:
            return f'x {self.description} | failed to update {self.artwork_type} in {self.upload_target.librarySectionTitle} - More info: {str(e)}'

    def artwork_exists_on_plex(self):
        existing_artwork = False

        for label in self.upload_target.labels:
            existing_label = str(label)  # Convert the label object to a string if it's not already
            if existing_label.startswith(self.artwork_id): # Only check this type of ID, could be multiple IDs per item (e.g. background + cover)
                if existing_label == self.label:
                    existing_artwork = True
                    if not self.track_artwork_ids:
                        self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're no longer tracking the artwork IDs
                else:
                    self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're replacing the artwork

        return existing_artwork

