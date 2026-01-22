import apprise

from utils.notifications import debug_me

class NotifyService:

    def __init__(self, urls):
        debug_me(f"Initializing NotifyService with URLs: {urls}", "NotifyService/__init__")
        self.apobj = apprise.Apprise()
        for url in urls:
            self.apobj.add(url)

    def send_notification(self, title, message):
        self.apobj.notify(
            body=message,
            title=title
        )

