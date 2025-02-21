# A URL item stored with its options (force, add sets, add posters, filters, year)
class URLItem:
    def __init__(self, url, options):

        """
        :rtype: object
        """

        self.url = url
        self.options = options