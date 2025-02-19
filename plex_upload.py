import plex_utils
import time

def tv_artwork(poster, tv, options):
    tv_show_items = plex_utils.find_in_library(tv, poster)
    if tv_show_items:
        for tv_show in tv_show_items:

            try:
                if poster["season"] == "Cover":
                    upload_target = tv_show
                    artwork_type = "cover"
                    description = f"{poster['title']}"

#                elif poster["season"] == 0:
#                    upload_target = tv_show.season("Specials")
#                    artwork_type = "season cover"
#                    description = f"{poster['title']}, specials"

                elif poster["season"] == "Backdrop":
                    upload_target = tv_show
                    artwork_type = "background"
                    description = f"{poster['title']}"

                elif poster["season"] >= 0:
                    if poster["episode"] == "Cover":
                        upload_target = tv_show.season(poster["season"])
                        artwork_type = "season cover"
                        description = f"{poster['title']}, season {poster['season']}"

                    elif poster["episode"] is None:
                        upload_target = tv_show.season(poster["season"])
                        artwork_type = "season cover"
                        description = f"{poster['title']} - season {poster['season']}"

                    elif poster["episode"] is not None:
                        try:
                            upload_target = tv_show.season(poster["season"]).episode(poster["episode"])
                            artwork_type = "episode card"
                            description = f"{poster['title']} - season {poster['season']}, episode {poster['episode']}"
                        except:
                            description = f"{poster['title']}, season {poster['season']}, episode {poster['episode']}, not found"


                try:
                    existing_artwork, new_label = plex_utils.find_existing_artwork(upload_target, artwork_type, poster)

                    if existing_artwork == False or options.force:
                        # Upload the new poster
                        if artwork_type != "background":
                            upload_target.uploadPoster(url = poster["url"])
                        else:
                            upload_target.uploadArt(url=poster["url"])

                        upload_target.addLabel(new_label)
                        print(f"✓ Uploaded {artwork_type} for {description} in {tv_show.librarySectionTitle}")

                        if poster["source"] == "posterdb":
                            time.sleep(6)  # too many requests prevention

                        # update_status(f"✓ Uploaded {artwork_type} for {description}", color="#32CD32")

                    else:
                        print(f"- No change of {artwork_type} for {description} in {tv_show.librarySectionTitle}")

                except:
                    print(f"x Failed on {artwork_type} for {description} in {tv_show.librarySectionTitle}")



            except:
                description = f"{poster['title']} - season {poster['season']}, episode {poster['episode']}"
                if poster['episode'] is None:
                    description = f"{poster['title']} - season {poster['season']}"
                    if poster['season'] is None:
                        description = f"{poster['title']}"

                print(f"x No media found on Plex for {description} in {tv_show.librarySectionTitle}")
    else:
        print(f"∙ {poster['title']} not found in any library.")





def movie_poster(poster, movies, options):
    movie_items = plex_utils.find_in_library(movies, poster)

    if movie_items:
        for movie_item in movie_items:
            try:
                existing_artwork, new_label = plex_utils.find_existing_artwork(movie_item, "poster", poster)

                if existing_artwork == False or options.force:
                    # Upload the new poster
                    movie_item.uploadPoster(poster["url"])
                    movie_item.addLabel(new_label)
                    print(f'✓ Uploaded art for {poster["title"]} ({movie_item.year}) in {movie_item.librarySectionTitle} library.')

                    # Rate limit if source is "posterdb"
                    if poster["source"] == "posterdb":
                        time.sleep(6)  # Too many requests prevention

                else:
                    print(f'- No change for {poster["title"]} ({movie_item.year}) in {movie_item.librarySectionTitle} library.')


            except Exception as e:
                print(
                    f'x Unable to upload art for {poster["title"]} ({movie_item.year}) in {movie_item.librarySectionTitle} library. Error: {e}')
    else:
        print(f'∙ {poster["title"]} ({poster["year"]}) not found in any library.')



def collection_poster(poster, movies, options):
    collection_items = plex_utils.find_collection(movies, poster)
    if collection_items:
        for collection in collection_items:
            try:

                existing_artwork, new_label = plex_utils.find_existing_artwork(collection, "poster", poster)

                if existing_artwork == False or options.force:
                    # Upload the new poster
                    collection.uploadPoster(poster["url"])
                    collection.addLabel(new_label)

                    print(f'✓ Uploaded art for {poster["title"]} in {collection.librarySectionTitle} library.')
                    if poster["source"] == "posterdb":
                        time.sleep(6)  # too many requests prevention

                else:
                    print(f'- No change for {poster["title"]} in {collection.librarySectionTitle} library.')

            except:
                print(f'x Unable to upload art for {poster["title"]} in {collection.librarySectionTitle} library.')
    else:
        collection_title = poster["title"].replace(" Collection","")
        print(f'∙ {collection_title} collection not found in any library.')


