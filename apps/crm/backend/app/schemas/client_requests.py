"""«Создать заявку» (CRM-03, W16-D1-2; SPEC-v3 §3.1 шаг 2): тело и ответ действия из лида и из
клиента."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.domain.consent import ConsentMethod


class RequestCompanyIn(BaseModel):
    """Новый клиент — компания с ИНН (ИНН необязателен: найдётся позже по реквизитам)."""

    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=32)


class RequestContactIn(BaseModel):
    """Контакт заявки: существующий контакт клиента (`contact_id`) или новый — имя и хотя бы один
    канал.

    E-mail не обязателен. `use_lead_telegram` — Telegram лида, из которого создаётся заявка,
    становится каналом нового контакта (обычный путь: лид пишет в бота).
    """

    contact_id: int | None = None
    full_name: str | None = Field(default=None, max_length=255)
    position: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    use_lead_telegram: bool = False

    @model_validator(mode="after")
    def _existing_or_named(self) -> "RequestContactIn":
        if self.contact_id is None and not (self.full_name and self.full_name.strip()):
            raise ValueError("choose a contact or enter a name")
        return self


class RequestConsentIn(BaseModel):
    """Согласие на обработку данных, полученное вне бота (звонок, письмо, бумага) — отметка
    сотрудника (D-8)."""

    method: ConsentMethod
    comment: str | None = Field(default=None, max_length=500)


class RequestCreate(BaseModel):
    """«Создать заявку»: клиент (существующий или новая компания), контакт с каналом, суть,
    срочность, письмо."""

    # Ключ идемпотентности формы (UUID, задаёт клиент — форма «Создать заявку» один раз на
    # открытие): повтор с тем же ключом — та же заявка (200), без второй строки, задачи и письма ВХ.
    request_key: uuid.UUID
    client_id: int | None = None
    company: RequestCompanyIn | None = None
    contact: RequestContactIn
    summary: str = Field(min_length=1, max_length=5000)
    urgency: Literal["normal", "urgent"] = "normal"
    # Письмо на имя директора, загруженное в EDS до заявки (`POST /files` EDS через BFF): id файла
    # EDS.
    letter_file_id: uuid.UUID | None = None
    consent: RequestConsentIn | None = None


class RequestCreated(BaseModel):
    """Итог: клиент и заявка CRM; в ERP заявка уходит задачей — `erp_request_status` и номер ЗВ
    появятся позже (`GET /clients/{id}`, события ERP)."""

    client_id: int
    deal_id: int
    lead_id: int | None = None
    erp_request_status: Literal["pending", "done", "failed"] = "pending"
    # False — повтор с тем же `request_key`: заявка уже была создана (ответ 200, а не 201).
    created: bool = True


class RequestRetried(BaseModel):
    """«Повторить отправку в ERP» (B-082): заявка снова `pending`, задача поставлена."""

    deal_id: int
    client_id: int
    erp_request_status: Literal["pending", "done", "failed"] = "pending"
