
# Command line or bulk file arguments, just a container to pass them around easily

class Options:

    def __init__(self, add_posters=False, add_sets=False, force=False):
        self.add_posters = add_posters
        self.add_sets = add_sets
        self.force = force