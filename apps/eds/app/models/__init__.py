"""Модели сервиса. Новая модель импортируется здесь — иначе Alembic её не увидит."""

from app.models.approvals import ApprovalRoute, ApprovalStep
from app.models.base import Base
from app.models.documents import Document, DocumentVersion
from app.models.employee import Employee, SsoJti
from app.models.files import FileVersion, StoredFile
from app.models.idempotency import IdempotencyKey
from app.models.journal import JournalEntry
from app.models.letters import Letter
from app.models.numbering import NumberCounter
from app.models.project_documents import ProjectDocument

__all__ = [
    "ApprovalRoute",
    "ApprovalStep",
    "Base",
    "Document",
    "DocumentVersion",
    "Employee",
    "FileVersion",
    "IdempotencyKey",
    "JournalEntry",
    "Letter",
    "NumberCounter",
    "ProjectDocument",
    "SsoJti",
    "StoredFile",
]
