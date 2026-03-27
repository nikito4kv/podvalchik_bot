from aiogram import Router, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.keyboards.reply import main_menu
from app.keyboards.inline import (
    my_forecasts_menu_kb,
    active_tournaments_kb,
    view_forecast_kb,
    forecast_history_kb,
    confirmation_kb,
    help_menu_kb,
    help_back_kb,
)
from app.db.models import User, Tournament, Forecast, TournamentStatus, Player
from app.db.session import async_session
from app.utils.formatting import format_breadcrumbs
from app.config import config
from app.handlers.render_helpers import (
    build_forecast_card_text,
    build_history_details_text,
    get_forecast_view_flags,
)

router = Router()


from aiogram.utils.keyboard import InlineKeyboardBuilder


@router.message(CommandStart())
async def cmd_start(message: types.Message):
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            session.add(
                User(
                    id=message.from_user.id,
                    username=message.from_user.username or "unknown",
                    full_name=message.from_user.full_name,
                )
            )
            await session.commit()
            await message.answer(
                "Добро пожаловать! Я бот для прогнозов на настольный теннис. "
                "Я зарегистрировал вас в системе. Вот главное меню:",
                reply_markup=main_menu,
            )
            return

    await message.answer(
        f"С возвращением, {message.from_user.first_name}! Вот главное меню:",
        reply_markup=main_menu,
    )


@router.message(F.text == "ℹ️ Правила")
async def handle_rules(message: types.Message):  # ADDED async
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await message.answer(text, reply_markup=help_menu_kb())


@router.callback_query(F.data == "help:main")
async def cq_help_main(callback: types.CallbackQuery):
    text = "<b>📚 Справочный центр</b>\n\nВыберите интересующий вас раздел:"
    await callback.message.edit_text(text, reply_markup=help_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "help:scoring")
async def cq_help_scoring(callback: types.CallbackQuery):
    text = """
    <b>📈 Система начисления очков (РТТФ)</b>

    Мы используем справедливую систему оценки прогнозов:

    🔸 <b>+1 балл:</b> Вы угадали, что игрок займет призовое место, но ошиблись с точной позицией.
    <i>Пример: Поставили на 1-е, а он занял 3-е.</i>

    🎯 <b>+5 баллов:</b> Вы угадали игрока и его точное место.
    <i>Пример: Поставили на 1-е, и он занял 1-е.</i>

    💎 <b>БОНУС +15 баллов:</b> Вы угадали <b>всех</b> призеров и их места в точности.
    <i>Это высшее мастерство!</i>
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()


@router.callback_query(F.data == "help:ranks")
async def cq_help_ranks(callback: types.CallbackQuery):
    text = """
    <b>🏅 Ранги и Достижения</b>

    Ваш статус зависит от суммы очков:
    👶 <b>Новичок</b>: 0 - 50
    🧢 <b>Любитель</b>: 51 - 200
    🎱 <b>Профи</b>: 201 - 500
    🧠 <b>Эксперт</b>: 501 - 1000
    🔮 <b>Оракул</b>: 1000+

    <b>Специальные отметки:</b>
    💎 — Количество "Идеальных турниров" (с бонусом +15).
    🎯 — Количество точных попаданий в место (+5 баллов).
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()


@router.callback_query(F.data == "help:how_to")
async def cq_help_howto(callback: types.CallbackQuery):
    text = """
    <b>📝 Как сделать прогноз</b>

    1. Нажмите кнопку <b>"🏁 Актуальные турниры"</b>.
    2. Выберите турнир из списка (если есть открытые).
    3. Нажмите <b>"🔮 Сделать прогноз"</b>.
    4. Выберите игроков последовательно для каждого места (1-е, 2-е, и т.д.).
    5. Подтвердите выбор.

    Вы можете изменить прогноз в любой момент до начала турнира!
    """
    await callback.message.edit_text(text, reply_markup=help_back_kb())
    await callback.answer()


@router.message(F.text == "🗂 Архив прогнозов")
async def handle_my_forecasts(message: types.Message):  # ADDED async
    """
    Shows the menu for viewing active or past forecasts.
    """
    await message.answer(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )


@router.callback_query(F.data == "back_to_forecasts_menu")
async def back_to_forecasts_menu(callback_query: types.CallbackQuery):  # ADDED async
    """
    Returns the user to the main forecasts menu.
    """
    await callback_query.message.edit_text(
        "Выберите, какие прогнозы вы хотите посмотреть:",
        reply_markup=my_forecasts_menu_kb(),
    )
    await callback_query.answer()


@router.callback_query(F.data == "forecasts:active")
async def show_active_forecasts(callback_query: types.CallbackQuery):  # ADDED async
    """
    Shows a list of tournaments for which the user has an active forecast.
    """
    await callback_query.answer()
    user_id = callback_query.from_user.id
    async with async_session() as session:
        active_forecasts_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status.in_([TournamentStatus.OPEN, TournamentStatus.LIVE]),
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(active_forecasts_stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            breadcrumbs = format_breadcrumbs(["Главная", "Мои прогнозы", "Активные"])
            builder = InlineKeyboardBuilder()
            builder.button(
                text="🏁 Посмотреть доступные турниры",
                callback_data="predict_back_to_list",
            )  # Callback to show active tournaments
            builder.row(
                InlineKeyboardButton(
                    text="◀️ Назад", callback_data="back_to_forecasts_menu"
                )
            )

            await callback_query.message.edit_text(
                f"{breadcrumbs}\n\nУ вас пока нет активных прогнозов. Сделайте первый!",
                reply_markup=builder.as_markup(),
            )
            return

        breadcrumbs = format_breadcrumbs(["Главная", "Мои прогнозы", "Активные"])
        await callback_query.message.edit_text(
            f"{breadcrumbs}\n\nВыберите турнир, чтобы посмотреть ваш прогноз:",
            reply_markup=active_tournaments_kb([f.tournament for f in forecasts]),
        )


@router.callback_query(F.data.startswith("view_forecast:"))
async def show_specific_forecast(callback_query: types.CallbackQuery):  # ADDED async
    """
    Shows the user's specific forecast for a selected tournament.
    """
    await callback_query.answer()
    tournament_id = int(callback_query.data.split(":")[1])
    user_id = callback_query.from_user.id

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(Forecast.user_id == user_id, Forecast.tournament_id == tournament_id)
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast:
            await callback_query.message.answer("Прогноз не найден.")
            return

        # Fetch player objects
        player_ids = forecast.prediction_data
        if not player_ids:
            await callback_query.message.answer(
                "В этом прогнозе нет данных об игроках."
            )
            return

        players_stmt = select(Player).where(Player.id.in_(player_ids))
        result = await session.execute(players_stmt)
        players_map = {p.id: p for p in result.scalars()}

        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        text = build_forecast_card_text(
            tournament_name=forecast.tournament.name,
            tournament_date_str=tournament_date,
            player_ids=player_ids,
            players_map=players_map,
            escape_html=True,
        )

        admin_ids = config.admin_ids if isinstance(config.admin_ids, list) else []
        allow_edit, is_admin, _show_others = get_forecast_view_flags(
            tournament_status=forecast.tournament.status,
            user_id=user_id,
            admin_ids=admin_ids,
        )

        kb = view_forecast_kb(
            back_callback="forecasts:active",
            forecast_id=forecast.id,
            tournament_id=tournament_id,
            allow_edit=allow_edit,
            show_others=_show_others,
            is_admin=is_admin,  # Pass for consistency check in KB
            tournament_status=forecast.tournament.status,  # Pass for consistency check in KB
        )

        await callback_query.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("edit_forecast_start:"))
async def cq_edit_forecast_start(callback_query: types.CallbackQuery):  # ADDED async
    """Asks for confirmation to edit a forecast."""
    await callback_query.answer()
    forecast_id = int(callback_query.data.split(":")[1])
    text = "Вы уверены, что хотите изменить прогноз? Ваш старый прогноз будет заменен только <b>после сохранения нового</b>."
    await callback_query.message.edit_text(
        text,
        reply_markup=confirmation_kb(action_prefix=f"edit_confirm:{forecast_id}"),
    )


@router.callback_query(F.data.startswith("forecasts:history:"))
async def show_forecast_history(callback_query: types.CallbackQuery):  # ADDED async
    """
    Shows a paginated list of the user's past forecasts.
    """
    await callback_query.answer()
    page = int(callback_query.data.split(":")[2])
    user_id = callback_query.from_user.id

    async with async_session() as session:
        history_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .join(Tournament, Forecast.tournament_id == Tournament.id)
            .where(
                Forecast.user_id == user_id,
                Tournament.status == TournamentStatus.FINISHED,
            )
            .order_by(Tournament.date.desc())
        )
        result = await session.execute(history_stmt)
        forecasts = result.scalars().all()

        if not forecasts:
            await callback_query.message.answer("У вас нет прошлых прогнозов.")
            return

        await callback_query.message.edit_text(
            "История ваших прогнозов:",
            reply_markup=forecast_history_kb(forecasts, page),
        )


@router.callback_query(F.data.startswith("view_history:"))
async def show_specific_history(callback_query: types.CallbackQuery):  # ADDED async
    """
    Shows a detailed comparison for a past forecast.
    """
    await callback_query.answer()
    parts = callback_query.data.split(":")
    forecast_id, page = int(parts[1]), int(parts[2])

    async with async_session() as session:
        # Fetch the forecast with tournament info
        forecast_stmt = (
            select(Forecast)
            .options(joinedload(Forecast.tournament))
            .where(Forecast.id == forecast_id)
        )
        result = await session.execute(forecast_stmt)
        forecast = result.scalar_one_or_none()

        if not forecast or not forecast.tournament.results:
            await callback_query.message.answer(
                "История для этого прогноза не найдена."
            )
            return

        # Get all player IDs from prediction and results to fetch names in one query
        pred_ids = forecast.prediction_data
        res_ids = [int(k) for k in forecast.tournament.results.keys()]
        all_player_ids = list(set(pred_ids) | set(res_ids))

        players_stmt = select(Player).where(Player.id.in_(all_player_ids))
        result = await session.execute(players_stmt)
        players_map = {p.id: p for p in result.scalars()}

        tournament_date = forecast.tournament.date.strftime("%d.%m.%Y")
        final_text = build_history_details_text(
            tournament_name=forecast.tournament.name,
            tournament_date_str=tournament_date,
            pred_ids=pred_ids,
            results=forecast.tournament.results,
            players_map=players_map,
            points_earned=forecast.points_earned,
        )

        # Pass tournament_id to enable 'Other Forecasts' button
        # History implies finished, so show_others=True
        await callback_query.message.edit_text(
            final_text,
            reply_markup=view_forecast_kb(
                back_callback=f"forecasts:history:{page}",
                forecast_id=forecast.id,
                tournament_id=forecast.tournament_id,
                allow_edit=False,
                show_others=True,
                is_admin=False,
                tournament_status=TournamentStatus.FINISHED,
            ),
        )
