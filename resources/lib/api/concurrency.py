import requests
import os
import pickle
from resources.lib.logging import LOG
from xbmc import Player
import time
import uuid

class ConcurrencyMeta:
    def __init__(self, meta=None):
        self.client_id = str( uuid.uuid4() )
        self.lock_id = None
        self.sequence_token = None
        self.encrypted_lock = None
        if meta != None:
            self.lock_id = meta[3]["content"]
            self.sequence_token = meta[4]["content"]
            self.encrypted_lock = meta[5]["content"]

    def set_meta(self, meta):
        LOG.info("META: " + str(meta))
        if len(meta) == 0:
            return
        self.lock_id = meta[3]["content"]
        self.sequence_token = meta[4]["content"]
        self.encrypted_lock = meta[5]["content"]


    def get_unlock_data(self):
        return {
                "clientId": self.client_id, 
                "encryptedLock": self.encrypted_lock,
                "id": self.lock_id,
                "sequenceToken": self.sequence_token
            }

class ConcurrencyLock:
    def __init__(self, file_path):
        self.url = "https://concurrency.delivery.theplatform.eu/concurrency/web/Concurrency/?schema=1.0&form=json"
        self.file_path = file_path
        self.__load()

    def get_client_id(self):
        if self.concurrencyMeta == None:
            self.__load()
        return self.concurrencyMeta.client_id
        
    def set_meta(self, meta):
        """
            Sets the meta data and saves it into a file.
        """
        if self.concurrencyMeta == None:
            self.__load()
        self.concurrencyMeta.set_meta(meta)
        self.__save()

    def __save(self):
        assert self.concurrencyMeta != None
        with open(self.file_path, "wb") as concurrency_file:
            concurrency_file.write(pickle.dumps(self.concurrencyMeta))

    def __delete(self):
        if os.path.exists(self.file_path):
            os.remove(self.file_path)

    def __load(self):
        if not os.path.exists(self.file_path):
            self.concurrencyMeta = ConcurrencyMeta()
            self.__save()
        with open(self.file_path, "rb") as concurrency_file:
            self.concurrencyMeta = pickle.load(concurrency_file)

    def is_locked(self):
        if self.concurrencyMeta == None:
            self.__load()
        return self.concurrencyMeta.encrypted_lock != None

    def unlock(self, session):
        if self.concurrencyMeta == None:
            self.__load()
        if self.concurrencyMeta != None:
            data = {
                "unlock": self.concurrencyMeta.get_unlock_data()
            }
            response = requests.post(self.url, json=data)
            self.__delete()
            return response.status_code
        return 0


    
