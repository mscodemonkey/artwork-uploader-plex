import os
from typing import Union, Optional
import time

from plexapi.video import Movie, Show, Season, Episode
from plexapi.collection import Collection

from utils import utils
from utils.notifications import debug_me
from models.options import Options
from core.enums import ScraperSource, ArtworkIDPrefix
from core.constants import TPDB_RATE_LIMIT_DELAY, KOMETA_OVERLAY_LABEL
from models.artwork_types import AnyArtwork

class PlexUploader:

    def __init__(
        self,
        upload_target: Union[Movie, Show, Season, Episode, Collection],
        artwork_type: str,
        artwork_id: str
    ) -> None:
        self.upload_target: Union[Movie, Show, Season, Episode, Collection] = upload_target
        self.artwork_type: str = artwork_type
        self.artwork_id: str = artwork_id.upper() + "ID:"  # This will be BID, CID, PID, SID or EID - for [B]ackgrounds, show [C]overs, [P]osters, [S]eason covers or [T]itle cards for [E]pisodes
        self.description: str = "item"
        self.label: Optional[str] = None
        self.artwork: Optional[AnyArtwork] = None
        self.options: Options = Options()
        self.type: Optional[str] = None
        self.track_artwork_ids: bool = True
        self.reset_overlay: bool = False

    def set_artwork(self, artwork: AnyArtwork) -> None:
        self.artwork = artwork
        if artwork['id'] == ScraperSource.UPLOAD.value:
            self.type = "file"
            self.label = self.artwork_id + artwork['checksum']
        else:
            self.type = "url"
            self.label = self.artwork_id + utils.calculate_md5(self.artwork["url"].split('&_cb=')[0])  # Remove any cache buster before calculating the MD5

    def set_description(self, description: str) -> None:
        self.description = description

    def set_options(self, options: Options) -> None:
        if isinstance(options, Options):
            self.options = options

    def process_overlay_label(self) -> None:
        if self.reset_overlay:
            for label in self.upload_target.labels:
                if str(label) == KOMETA_OVERLAY_LABEL:
                    self.upload_target.removeLabel(label, False)  # Remove the Overlay label
                    self.upload_target.reload()

    def upload_to_plex(self) -> str:
        try:
            if self.artwork_exists_on_plex() is False or self.options.force:

                self.process_overlay_label()

                if self.artwork_id == "BID:":
                    if self.type == "file":
                        self.upload_target.uploadArt( filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadArt( url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)
                else:
                    if self.type == "file":
                        self.upload_target.uploadPoster( filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadPoster( url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)
                if self.artwork["source"] == ScraperSource.THEPOSTERDB.value and self.type == "url":
                    time.sleep(TPDB_RATE_LIMIT_DELAY)
                return f'{"♻️" if self.options.force else "✅"} {self.description} | {self.artwork_type} {"forced update" if self.options.force else "updated"} in {self.upload_target.librarySectionTitle}'
            else:
                return f'⏩ {self.description} | {self.artwork_type} unchanged in {self.upload_target.librarySectionTitle}'
        except Exception as e:
            return f'❌ {self.description} | failed to update {self.artwork_type} in {self.upload_target.librarySectionTitle} - More info: {str(e)}'

    def artwork_exists_on_plex(self) -> bool:
        existing_artwork = False

        for label in self.upload_target.labels:
            existing_label = str(label)  # Convert the label object to a string if it's not already
            if existing_label.startswith(self.artwork_id): # Only check this type of ID, could be multiple IDs per item (e.g. background + cover)
                if existing_label == self.label:
                    existing_artwork = True
                    if not self.track_artwork_ids:
                        self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're no longer tracking the artwork IDs
                        self.upload_target.reload()
                else:
                    self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're replacing the artwork
                    self.upload_target.reload()

        return existing_artwork

