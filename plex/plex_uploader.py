import time
from typing import Union, Optional
from plexapi.video import Movie, Show, Season, Episode
from plexapi.collection import Collection
from utils import utils
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
        self.artwork_id: str = artwork_id  # This will be BID, SAID, CID, PID, SID or EID - for [B]ackgrounds, [S]quare[A]rt, show [C]overs, [P]osters, [S]eason covers or [T]itle cards for [E]pisodes
        self.description: str = "item"
        self.label: Optional[str] = None
        self.artwork: Optional[AnyArtwork] = None
        self.options: Options = Options()
        self.type: Optional[str] = None
        self.track_artwork_ids: bool = True
        self.reset_overlay: bool = False
        self.skip_locked: bool = False
        self.allow_artist_updates: bool = False
        self.artist_assets: Optional[dict] = None  # {md5(asset url): asset id} for the artist being processed
        self.confirm_match = None
        self.stale_labels: list = []

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
            if self.skip_locked and not self.options.force and self.artwork_field_is_locked():
                # A locked field is normally left alone. But if we applied its current artwork
                # from this same artist and the artist has since posted a newer version,
                # allow_artist_updates lets that one update flow through - a hand-set custom (no
                # matching label) or another artist's poster is still protected.
                if not (self.allow_artist_updates and self.candidate_supersedes_current()):
                    return f'🔒 {self.description} | {self.artwork_type} locked, skipped in {self.upload_target.librarySectionTitle}'
            if self.artwork_exists_on_plex() is False or self.options.force:

                if self.confirm_match is not None and not self.confirm_match():
                    return f'⚠️ {self.description} | {self.artwork_type} skipped in {self.upload_target.librarySectionTitle} - artwork is for a different title'
                self.process_overlay_label()

                if self.artwork_id == ArtworkIDPrefix.BACKGROUND.value:
                    if self.type == "file":
                        self.upload_target.uploadArt(filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadArt(url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)

                elif self.artwork_id == ArtworkIDPrefix.SQUARE_ART.value:
                    if self.type == "file":
                        self.upload_target.uploadSquareArt(filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadSquareArt(url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)

                else:
                    if self.type == "file":
                        self.upload_target.uploadPoster(filepath = self.artwork['path'])
                    else:
                        self.upload_target.uploadPoster(url = self.artwork["url"])
                    if self.track_artwork_ids:
                        self.upload_target.addLabel(self.label)
                # Remove the labels for the artwork we just replaced only AFTER the new one is on
                # the item, so a failed upload leaves the old label in place and the item stays
                # recognisable as ours, rather than looking like artwork set by hand
                self.remove_stale_labels()
                if self.artwork["source"] == ScraperSource.THEPOSTERDB.value and self.type == "url":
                    time.sleep(TPDB_RATE_LIMIT_DELAY)
                return f'{"♻️" if self.options.force else "✅"} {self.description} | {self.artwork_type} {"forced update" if self.options.force else "updated"} in {self.upload_target.librarySectionTitle}'
            else:
                return f'⏩ {self.description} | {self.artwork_type} unchanged in {self.upload_target.librarySectionTitle}'
        except Exception as e:
            return f'❌ {self.description} | Failed to update {self.artwork_type} in {self.upload_target.librarySectionTitle}: {str(e)}'

    def artwork_exists_on_plex(self) -> bool:
        existing_artwork = False
        self.stale_labels = []

        for label in self.upload_target.labels:
            existing_label = str(label)  # Convert the label object to a string if it's not already
            if existing_label.startswith(self.artwork_id): # Only check this type of ID, could be multiple IDs per item (e.g. background + cover)
                if existing_label == self.label:
                    existing_artwork = True
                    if not self.track_artwork_ids:
                        self.upload_target.removeLabel(existing_label, False)  # Remove the existing label as we're no longer tracking the artwork IDs
                        self.upload_target.reload()
                else:
                    self.stale_labels.append(existing_label)  # Defer removal until the replacement is on the item (see remove_stale_labels)

        return existing_artwork

    def artwork_field_is_locked(self) -> bool:
        # Backgrounds lock the art field, square art locks squareArt, all poster types lock thumb
        locked_field = "art" if self.artwork_id == ArtworkIDPrefix.BACKGROUND.value else "squareArt" if self.artwork_id == ArtworkIDPrefix.SQUARE_ART.value else "thumb"
        for field in self.upload_target.fields:
            if field.name == locked_field and field.locked:
                return True
        return False

    def remove_stale_labels(self) -> None:
        # Remove same-type labels for artwork we've now replaced. Called after the new artwork and
        # its label are on the item, so a failed upload never strips the old label.
        for existing_label in self.stale_labels:
            self.upload_target.removeLabel(existing_label, False)
            self.upload_target.reload()
        self.stale_labels = []

    def current_artwork_id(self) -> Optional[int]:
        """The asset id of the artwork currently on this item of our type, if we applied it from
           the artist being processed. None if it was set by hand or by a different artist."""
        if not self.artist_assets:
            return None
        for label in self.upload_target.labels:
            existing_label = str(label)
            if existing_label.startswith(self.artwork_id):
                return self.artist_assets.get(existing_label[len(self.artwork_id):])
        return None

    def candidate_supersedes_current(self) -> bool:
        """True when the artwork we're about to apply is a same-or-newer asset from the same
           artist that applied the current artwork. Only ever moves forward to a newer asset id,
           so the nightly run converges on the artist's latest instead of flip-flopping."""
        candidate = self.artwork.get("id") if self.artwork else None
        if not (isinstance(candidate, (int, str)) and str(candidate).isdigit()):
            return False  # file uploads and non-numeric ids can't be compared by asset id
        current_id = self.current_artwork_id()
        return current_id is not None and int(candidate) >= current_id
