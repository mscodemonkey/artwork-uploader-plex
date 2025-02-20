import plex_utils
from options import Options
from plex_uploader import PlexUploader
from upload_processor_exceptions import CollectionNotFound, MovieNotFound

class UploadProcessor:

    def __init__(self, plex):
        self.plex = plex
        self.options = Options()

    def set_options(self, options):
        self.options = options

    def process_collection_artwork(self, artwork):

        collection_items = self.plex.find_collection(artwork["title"])

        if collection_items:
            for collection_item in collection_items:
                uploader = PlexUploader(collection_item, "poster")
                uploader.set_artwork(artwork)
                uploader.set_description(f"{artwork['title']}")
                uploader.set_options(self.options)
                uploader.upload_to_plex()
        else:
            collection_title = artwork["title"].replace(" Collection", "")
            raise CollectionNotFound(f'{collection_title}: collection not available on Plex')


    def process_movie_artwork(self, artwork):

        movie_items = self.plex.find_in_library("movie", artwork["title"], artwork["year"])

        if movie_items:
            for movie_item in movie_items:

                uploader = PlexUploader(movie_item, "poster")
                uploader.set_artwork(artwork)
                uploader.set_description(f"{artwork['title']}")
                if artwork['year']:
                    uploader.set_description(f"{artwork['title']}({artwork['year']})")
                uploader.set_options(self.options)
                uploader.upload_to_plex()

        else:
            raise MovieNotFound(f'∙ {artwork["title"]} ({artwork["year"]}): movie not available on Plex')



    def process_tv_artwork(self, artwork):

        description = "media"
        upload_target = None
        artwork_type = None

        try:
            description = f"{artwork['title']}, season {artwork['season']:02}, episode {artwork['episode']:02}"
        except TypeError:
            if artwork['episode'] is None or artwork['episode'] == "Cover":
                try:
                    description = f"{artwork['title']}, season {artwork['season']:02}"
                except TypeError:
                    if artwork['season'] is None or artwork["season"] == "Cover":
                        description = f"{artwork['title']}"

        tv_show_items = self.plex.find_in_library("tv", artwork["title"], artwork["year"] )

        if tv_show_items:

            for tv_show in tv_show_items:

                try:
                    if artwork["season"] == "Cover":
                        upload_target = tv_show
                        artwork_type = "cover"

                    elif artwork["season"] == "Backdrop":
                        upload_target = tv_show
                        artwork_type = "background"

                    elif artwork["season"] >= 0:

                        if artwork["episode"] == "Cover":
                            upload_target = tv_show.season(artwork["season"])
                            artwork_type = "season cover"

                        elif artwork["episode"] is None:
                            upload_target = tv_show.season(artwork["season"])
                            artwork_type = "season cover"

                        elif artwork["episode"] >= 0:
                            upload_target = tv_show.season(artwork["season"]).episode(artwork["episode"])
                            artwork_type = "episode card"

                    try:
                        if upload_target:
                            uploader = PlexUploader(upload_target, artwork_type)
                            uploader.set_artwork(artwork)
                            uploader.set_description(description)
                            uploader.set_options(self.options)
                            uploader.upload_to_plex()
                    except Exception as e:
                        print(f"Got an error from uploader ({e})")

                except Exception as e:
                    print(f"∙ {description}: not available in {tv_show.librarySectionTitle}")

        else:
            print(f"∙ {artwork['title']}: show not available on Plex")




