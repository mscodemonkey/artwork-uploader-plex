
# Command line or bulk file arguments, just a container to pass them around easily

class Options:

    def __init__(self, add_posters=False, add_sets=False, force=False, filters=None, exclude=None, year=None):

        if filters is None:
            filters = []
        self.add_posters = add_posters
        self.add_sets = add_sets
        self.force = force
        self.filters = filters
        self.exclude = exclude
        self.year = year

    def has_filter(self, filter_type):
        return self.filters and filter_type in self.filters

    def has_no_filters(self):
        return not self.filters

    def clear_filters(self):
        self.filters = []

    def is_excluded(self, item_id):
        return self.exclude and item_id in self.exclude