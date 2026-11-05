from django.conf import settings
from django.core.files.uploadhandler import FileUploadHandler, StopUpload


class ImportLimitHandler(FileUploadHandler):
    """Bound total uploaded bytes before Django spools files to disk."""
    def __init__(self, request=None):
        super().__init__(request)
        self.received = 0

    def receive_data_chunk(self, raw_data, start):
        if self.request.path == "/api/imports/validate":
            self.received += len(raw_data)
            if self.received > settings.IMPORT_MAX_BYTES:
                self.request.import_upload_too_large = True
                raise StopUpload(connection_reset=False)
        return raw_data

    def file_complete(self, file_size):
        return None
