# SplitBot — распределение трат коллектива

Telegram-бот: участники в течение месяца вносят траты и даты отсутствия, в начале
следующего месяца бот рассылает расчёт, после подтверждения всеми — итоговую
таблицу переводов «Кто → Кому → Сколько» с минимальным числом транзакций.

## Возможности

- **Два типа трат:** общая (платят все) и дневная (платят только присутствовавшие
  в дату траты; плательщик присутствует по определению).
- **Заявки на вступление:** новый пользователь при /start подаёт заявку, админ
  одобряет или отклоняет.
- **Месячный цикл:** в `SETTLE_DAY` числа бот переводит период в фазу
  подтверждения и рассылает превью расчёта; одновременно открывается новый месяц,
  ввод трат не останавливается. Период закрывается, когда подтвердят все.
- **Минимизация переводов:** жадный алгоритм, не более N−1 транзакций.
- **Админ-панель:** заявки, состав, редактирование/удаление любых трат
  (с аудитом «кто правил»), ручной запуск и принудительное закрытие расчёта.
  Правка траты в фазе подтверждения сбрасывает подтверждения и рассылает
  обновлённый расчёт.
- **Надёжность:** деньги хранятся в копейках (int), уведомления идемпотентны
  (`scheduler_log`), удаление трат и участников — мягкое.

## Запуск

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # вписать BOT_TOKEN и ADMIN_TG_ID
python main.py
```

`ADMIN_TG_ID` — ваш Telegram id (узнать: @userinfobot). Первый /start от этого
id регистрирует администратора без заявки.

Если Telegram заблокирован, задайте `PROXY_URL` в `.env` (http/https или socks5,
напр. `socks5://user:pass@host:1080`). Для socks5 нужен пакет `aiohttp-socks`
(уже в `requirements.txt`). Пустое значение — без прокси.

## Тесты

141 тест, покрытие 99% (все модули 100%, кроме runtime-части `main()` с polling):

```bash
pip install pytest pytest-asyncio pytest-cov
python -m pytest -q                       # весь набор
python -m pytest -q --cov=. --cov-report=term-missing   # с покрытием
```

Слои покрытия: чистое расчётное ядро; репозитории (in-memory SQLite); сервисы
периода/членства/рассылок (фейковый Bot фиксирует отправки и имитирует
заблокировавших бота); middleware доступа; клавиатуры и календарная сетка;
планировщик (включая идемпотентность и регресс на повторный старт после
заблокированного месяца); все FSM-потоки хэндлеров — прямым вызовом с моками
Message/CallbackQuery и реальным FSMContext, шаги aiogram_calendar — через патч
`process_selection`.

## Деплой на VPS (systemd)

`/etc/systemd/system/splitbot.service`:

```ini
[Unit]
Description=SplitBot
After=network-online.target

[Service]
User=splitbot
WorkingDirectory=/opt/splitbot
ExecStart=/opt/splitbot/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now splitbot
```

База — один файл SQLite (`DB_PATH`); бэкап = копия файла.

## Структура

```
main.py            сборка диспетчера, middleware, запуск polling и планировщика
config.py          конфигурация из .env
scheduler.py       месячный старт расчёта + ежедневные напоминания
db/database.py     подключение aiosqlite, схема (7 таблиц)
db/repositories.py весь SQL проекта
services/
  calculation.py   чистое расчётное ядро (балансы, минимизация) — покрыто тестами
  period_service.py жизненный цикл периода: open → confirming → closed
  membership.py    заявки, одобрение, исключение
  notifications.py безопасные рассылки
handlers/
  start.py         /start, JoinFSM, глобальная отмена
  member/          AddExpenseFSM, AbsenceFSM, подтверждение расчёта
  admin/           панель, участники, EditExpenseFSM, управление периодом
keyboards/         меню, подтверждения; календари (aiogram_calendar +
                   собственный мультивыбор для отсутствий)
middlewares/       контроль доступа: active-участник / админ
states/states.py   все FSM
```

## Отличия от проектного документа

- Выбор одиночной даты — `aiogram_calendar.SimpleCalendar` с `set_dates_range`
  (даты ограничены месяцем периода). Мультивыбор дат отсутствия библиотека не
  поддерживает, поэтому он реализован собственной inline-сеткой месяца.
- `RemoveMemberFSM` и `ForceCloseFSM` реализованы stateless-колбэками
  с подтверждением: весь контекст помещается в callback_data, состояние не нужно.
- При старте расчёта следующий период открывается сразу (а не при закрытии
  предыдущего), чтобы участники могли вносить траты нового месяца, пока идёт
  подтверждение старого.
