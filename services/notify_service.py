import apprise
from typing import Optional

class NotifyService:

    def __init__(self):
        self.apobj = apprise.Apprise()

    def add_url(self, url: str):
        self.apobj.add(url)

    def clear_urls(self):
        self.apobj.clear()

    def send_notification(self, title, message) -> Optional[bool]:
        return self.apobj.notify(
            body=message,
            title=title
        )

