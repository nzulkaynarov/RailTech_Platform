"""Модели сервиса. Новая модель импортируется здесь — иначе Alembic её не увидит."""

from app.models.ai import AiSuggestion, DocflowSettings
from app.models.approvals import ApprovalRoute, ApprovalStep
from app.models.base import Base
from app.models.dictionaries import DictionaryItem
from app.models.documents import Document, DocumentPayment, DocumentVersion
from app.models.employee import Employee, SsoJti
from app.models.files import FileVersion, StoredFile
from app.models.idempotency import IdempotencyKey
from app.models.instructions import Acquaintance, Instruction, InstructionExtension
from app.models.journal import JournalEntry
from app.models.letterhead import DocumentMailing, DocumentRender, Letterhead, LetterheadLogo
from app.models.letters import Letter
from app.models.numbering import NumberCounter, NumberLabel
from app.models.project_documents import ProjectDocument
from app.models.resolution_templates import ResolutionTemplate
from app.models.signing import SigningAuthority, SigningAuthorityEvent

__all__ = [
    "Acquaintance",
    "AiSuggestion",
    "ApprovalRoute",
    "ApprovalStep",
    "Base",
    "DictionaryItem",
    "DocflowSettings",
    "Document",
    "DocumentMailing",
    "DocumentPayment",
    "DocumentRender",
    "DocumentVersion",
    "Employee",
    "FileVersion",
    "IdempotencyKey",
    "Instruction",
    "InstructionExtension",
    "JournalEntry",
    "Letter",
    "Letterhead",
    "LetterheadLogo",
    "NumberCounter",
    "NumberLabel",
    "ProjectDocument",
    "ResolutionTemplate",
    "SigningAuthority",
    "SigningAuthorityEvent",
    "SsoJti",
    "StoredFile",
]
