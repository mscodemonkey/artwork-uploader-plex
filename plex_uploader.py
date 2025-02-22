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

    def set_artwork(self, artwork):
        self.artwork = artwork
        self.label = self.artwork_id + utils.calculate_md5(self.artwork["url"])

    def set_description(self, description):
        self.description = description

    def set_options(self, options):
        if isinstance(options, Options):
            self.options = options

    def upload_to_plex(self):
        try:
            if self.artwork_exists_on_plex() == False or self.options.force:
                if self.artwork_id == "BID:":
                    self.upload_target.uploadArt(self.artwork["url"])
                else:
                    self.upload_target.uploadPoster(self.artwork["url"])
                self.upload_target.addLabel(self.label)
                if self.artwork["source"] == "theposterdb":
                    time.sleep(6)
              #  print(f'✓ {self.description} | {self.artwork_type} {"forced update" if self.options.force else "updated"} in {self.upload_target.librarySectionTitle}')
                return f'✓ {self.description} | {self.artwork_type} {"forced update" if self.options.force else "updated"} in {self.upload_target.librarySectionTitle}'
            else:
               # print(f'- {self.description} | {self.artwork_type} unchanged in {self.upload_target.librarySectionTitle}')
                return f'- {self.description} | {self.artwork_type} unchanged in {self.upload_target.librarySectionTitle}'
        except Exception as e:
          #  print(f'x {self.description} | failed to update {self.artwork_type} in {self.upload_target.librarySectionTitle}')
            return f'x {self.description} | failed to update {self.artwork_type} in {self.upload_target.librarySectionTitle}'

    def artwork_exists_on_plex(self):
        existing_artwork = False

        for label in self.upload_target.labels:
            existing_label = str(label)  # Convert the label object to a string if it's not already
            if existing_label.startswith(self.artwork_id): # Only check this type of ID, could be multiple IDs per item (e.g. background + cover)
                if existing_label == self.label:
                    existing_artwork = True
                else:
                    self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're replacing the artwork

        return existing_artwork

