import os

from celery import Celery
from celery.signals import after_setup_logger, after_setup_task_logger

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

app = Celery("core")

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object("django.conf:settings", namespace="CELERY")

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# ARCH-01: also register the off-thread AI job runner (sourcing/tasks_ai.py) —
# autodiscover_tasks() only imports `<app>.tasks` by default, so without this the
# worker would reject "sourcing.run_ai_job" as an unregistered task.
app.autodiscover_tasks(related_name="tasks_ai")


# FIX-66b: воркер и Beat при старте заменяют обработчики корневого логгера своими (`worker_hijack_root_logger`), и
# фильтры из Django `LOGGING` на них не действуют. Маска секретов вешается на обработчики, которые создал Celery.
def _mask_celery_handlers(logger=None, **_kwargs):
    from core.log_mask import SecretMaskFilter

    if logger is None:
        return
    for handler in logger.handlers:
        if not any(isinstance(f, SecretMaskFilter) for f in handler.filters):
            handler.addFilter(SecretMaskFilter())


after_setup_logger.connect(_mask_celery_handlers, weak=False)
after_setup_task_logger.connect(_mask_celery_handlers, weak=False)
