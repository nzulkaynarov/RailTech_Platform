"""Проверка размера загружаемого файла: пустой и слишком большой — разные подкоды ошибки."""

from app.domain.errors import Reason, ValidationFailedError


def check_file_size(size: int, max_bytes: int) -> None:
    if size == 0:
        raise ValidationFailedError("file is empty", reason=Reason.FILE_EMPTY, field="file")
    if size > max_bytes:
        raise ValidationFailedError(
            f"file is larger than {max_bytes // (1024 * 1024)} MB",
            reason=Reason.FILE_TOO_LARGE,
            field="file",
            max_bytes=max_bytes,
        )
