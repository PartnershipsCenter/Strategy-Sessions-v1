from io import BytesIO

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveClient:
    def __init__(self, service_account_key_path: str):
        credentials = service_account.Credentials.from_service_account_file(
            service_account_key_path, scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=credentials)

    def _find_folder(self, name: str, parent_id: str | None = None) -> str | None:
        """Find a folder by name under a parent. Returns folder ID or None."""
        query_parts = [
            f"name = '{name}'",
            f"mimeType = '{FOLDER_MIME}'",
            "trashed = false",
        ]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")

        result = (
            self._service.files()
            .list(q=" and ".join(query_parts), spaces="drive", fields="files(id)", pageSize=1)
            .execute()
        )
        files = result.get("files", [])
        return files[0]["id"] if files else None

    def _get_or_create_folder(self, name: str, parent_id: str | None = None) -> str:
        """Find or create a folder. Returns the folder ID."""
        existing = self._find_folder(name, parent_id)
        if existing:
            return existing

        metadata: dict = {"name": name, "mimeType": FOLDER_MIME}
        if parent_id:
            metadata["parents"] = [parent_id]

        folder = self._service.files().create(body=metadata, fields="id").execute()
        return folder["id"]

    def ensure_date_folder(self, year: int, month: int) -> str:
        """Ensure Transcripts/YYYY/MM/ folder structure exists. Returns the month folder ID."""
        transcripts_id = self._get_or_create_folder("Transcripts")
        year_id = self._get_or_create_folder(str(year), parent_id=transcripts_id)
        month_id = self._get_or_create_folder(f"{month:02d}", parent_id=year_id)
        return month_id

    def upload_transcript(self, folder_id: str, filename: str, content: str) -> dict:
        """Upload a text transcript to a folder. Returns file metadata with id and webViewLink."""
        media = MediaIoBaseUpload(
            BytesIO(content.encode("utf-8")),
            mimetype="text/plain",
            resumable=False,
        )
        return (
            self._service.files()
            .create(
                body={"name": filename, "parents": [folder_id]},
                media_body=media,
                fields="id, webViewLink",
            )
            .execute()
        )

    def share_folder_with_user(self, folder_id: str, email: str) -> None:
        """Share a folder (and its children) with a user by email."""
        self._service.permissions().create(
            fileId=folder_id,
            body={"type": "user", "role": "writer", "emailAddress": email},
            sendNotificationEmail=False,
        ).execute()

    def ensure_shared_root(self, email: str) -> str:
        """Ensure the Transcripts root folder exists and is shared with the user."""
        transcripts_id = self._get_or_create_folder("Transcripts")
        self.share_folder_with_user(transcripts_id, email)
        return transcripts_id
