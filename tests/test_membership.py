"""Тесты membership: заявки, одобрение/отклонение, исключение."""
from db.repositories import UserRepo
from services import membership
from tests.conftest import ADMIN_TG, BOB_TG


async def test_submit_request_new_user(db, bot):
    await membership.submit_request(bot, db, ADMIN_TG, 555, "newbie", "Новичок")
    user = await UserRepo.get_by_tg(db, 555)
    assert user["status"] == "pending" and user["role"] == "member"
    card = bot.texts_for(ADMIN_TG)[0]
    assert "Новичок" in card and "@newbie" in card
    assert bot.markup_for(ADMIN_TG)[0] is not None  # кнопки принять/отклонить


async def test_submit_request_reapply_after_removal(db, seeded, bot):
    await UserRepo.set_status(db, seeded["bob"], "removed")
    await membership.submit_request(bot, db, ADMIN_TG, BOB_TG, "bob", "Боб Снова")
    user = await UserRepo.get_by_tg(db, BOB_TG)
    assert user["id"] == seeded["bob"]            # та же запись, не дубль
    assert user["status"] == "pending" and user["full_name"] == "Боб Снова"


async def test_approve(db, bot):
    await membership.submit_request(bot, db, ADMIN_TG, 555, None, "Новичок")
    user = await UserRepo.get_by_tg(db, 555)
    result = await membership.approve(bot, db, user["id"])
    assert "принят" in result
    assert (await UserRepo.get(db, user["id"]))["status"] == "active"
    assert any("одобрена" in t for t in bot.texts_for(555))


async def test_approve_twice(db, bot):
    await membership.submit_request(bot, db, ADMIN_TG, 555, None, "Новичок")
    user = await UserRepo.get_by_tg(db, 555)
    await membership.approve(bot, db, user["id"])
    assert await membership.approve(bot, db, user["id"]) == "Заявка уже обработана."


async def test_reject(db, bot):
    await membership.submit_request(bot, db, ADMIN_TG, 555, None, "Новичок")
    user = await UserRepo.get_by_tg(db, 555)
    result = await membership.reject(bot, db, user["id"])
    assert "отклонена" in result
    assert (await UserRepo.get(db, user["id"]))["status"] == "removed"
    assert any("отклонена" in t for t in bot.texts_for(555))


async def test_remove_member(db, seeded, bot):
    result = await membership.remove_member(bot, db, seeded["bob"])
    assert "исключён" in result
    assert (await UserRepo.get(db, seeded["bob"]))["status"] == "removed"
    assert any("исключены" in t for t in bot.texts_for(BOB_TG))


async def test_remove_admin_forbidden(db, seeded, bot):
    result = await membership.remove_member(bot, db, seeded["admin"])
    assert result == "Нельзя удалить администратора."
    assert (await UserRepo.get(db, seeded["admin"]))["status"] == "active"


async def test_remove_missing(db, seeded, bot):
    assert "не найден" in (await membership.remove_member(bot, db, 9999))
