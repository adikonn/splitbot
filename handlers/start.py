"""/start, заявка на вступление (JoinFSM) и глобальная отмена FSM.

Этот роутер НЕ защищён AccessMiddleware — сюда попадают и незарегистрированные.
"""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from config import Config
from db.database import Database
from db.repositories import UserRepo
from keyboards.common import BTN_CANCEL, main_menu
from services.membership import submit_request
from states.states import JoinFSM

router = Router(name="start")


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db: Database,
                    config: Config) -> None:
    await state.clear()
    user = await UserRepo.get_by_tg(db, message.from_user.id)

    if user and user["status"] == "active":
        await message.answer(
            f"С возвращением, {user['full_name']}!",
            reply_markup=main_menu(user["role"] == "admin"))
        return
    if user and user["status"] == "pending":
        await message.answer("Ваша заявка уже на рассмотрении у администратора. Ожидайте.")
        return

    # новый пользователь или removed — подаём (повторную) заявку
    if message.from_user.id == config.admin_tg_id and user is None:
        await message.answer("Привет, админ! Как вас записать в таблицах расчёта?")
    else:
        await message.answer(
            "Привет! Это бот учёта общих трат коллектива.\n"
            "Чтобы подать заявку на вступление, напишите своё имя "
            "(так вас будут видеть в таблицах расчёта):",
            reply_markup=ReplyKeyboardRemove())
    await state.set_state(JoinFSM.waiting_name)


@router.message(JoinFSM.waiting_name, F.text)
async def join_name(message: Message, state: FSMContext, db: Database,
                    config: Config, bot: Bot) -> None:
    name = message.text.strip()
    if not (1 < len(name) <= 64):
        await message.answer("Имя должно быть от 2 до 64 символов. Попробуйте ещё раз:")
        return
    await state.clear()

    if message.from_user.id == config.admin_tg_id:
        user = await UserRepo.get_by_tg(db, message.from_user.id)
        if user is None:
            await UserRepo.create(db, message.from_user.id, message.from_user.username,
                                  name, role="admin", status="active")
        await message.answer(f"Готово, {name}! Вы администратор коллектива.",
                             reply_markup=main_menu(is_admin=True))
        return

    await submit_request(bot, db, config.admin_tg_id,
                         message.from_user.id, message.from_user.username, name)
    await message.answer("📨 Заявка отправлена администратору. "
                         "Вы получите сообщение, когда её рассмотрят.")


# ----------------------- глобальная отмена ----------------------------------

@router.callback_query(F.data == "fsm:cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.answer()


@router.message(Command("cancel"))
@router.message(F.text == BTN_CANCEL)
async def msg_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Действие отменено.")
