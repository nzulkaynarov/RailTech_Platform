"""Состояния FSM клиентского бота, общие для нескольких роутеров."""

from aiogram.fsm.state import State, StatesGroup


class PhoneForm(StatesGroup):
    """Бот показал клавиатуру номера: «Не сейчас» перехватываем только в этом состоянии."""

    pending = State()
