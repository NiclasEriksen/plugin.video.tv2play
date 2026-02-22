import xbmcvfs
import pickle
import xbmc
import os

from resources.lib.logging import LOG
from resources.lib.globals import G

class CookieFile():
    def __init__(self, path, file_name):
        self.path = path
        self.file_name = file_name
        self.file_path = os.path.join(path, file_name)

    def save(self, cookie_jar):
        """Save a cookie jar to file and in-memory storage"""
        if not xbmcvfs.exists(self.path):
            xbmcvfs.mkdirs(self.path)
        with xbmcvfs.File(self.file_path, 'wb') as cookie_file:
            cookie_file.write(pickle.dumps(cookie_jar))

    def delete(self):
        """Delete cookies for an account from the disk"""
        if xbmcvfs.exists(self.file_path):
            xbmcvfs.delete(self.file_path)

    def load(self):
        """Load cookies for a given account"""
        if not xbmcvfs.exists(self.file_path):
            return
        with xbmcvfs.File(self.file_path, 'rb') as cookie_file:
            cookie_jar = pickle.loads(cookie_file.readBytes())
        return cookie_jar
