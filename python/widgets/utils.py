import os
import json

class PrefFile:
    def __init__(self):
        self.root_dir = os.path.expanduser("~")
        self.pref_file = os.path.join(self.root_dir, "Documents", ".p4syncpref")
        
        self.read()

    def write(self, data=None):
        if not data:
            data = self.data
        with open(self.pref_file, "w") as file_obj:
            json.dump(data, file_obj, indent=4)

    def read(self):
        if not os.path.isfile(self.pref_file):
            self.data = {}
            self.write(self.data)
        with open(self.pref_file, "r") as file_obj:
            self.data = json.load(file_obj)
            return self.data

