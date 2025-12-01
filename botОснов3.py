import sys
import os
import atexit
import logging
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.webhook.aiohttp_server import  SimpleRequestHandler, setup_application
import asyncio
import hashlib
import json
from datetime import datetime
import time
from aiogram import BaseMiddleware
from aiogram.types import Update
from aiogram.client.session.aiohttp import AiohttpSession

class TimingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        start = time.time()
        try:
            return await handler(event, data)
        finally:
            duration = time.time() - start
            if duration > 1.0:  # Логируем только медленные запросы
                logger.warning(f"Медленный обработчик: {duration:.2f}с для {event.type}")

support_tickets = {}
active_tickets = []
ticket_counter = 1

# Реферальная система
referral_data = {}  # user_id: {referral_code, referrals_count, referred_by}

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ЗАМЕНИТЕ НА ВАШИ ДАННЫЕ
BOT_TOKEN = "7247213543:AAEEG59-k0IV6ne370xzojr87XCXdZxDEF0"
CHANNEL_ID = "-1003455005128"
CHANNEL_URL = "https://t.me/easyobxod"
ADMIN_IDS = [5919648338]

# Хранилище данных
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)
router = Router()


# Глобальные переменные для хранения данных
user_data_storage = {}  # user_id: {service_id, service_link}
support_requests = {}  # user_id: [messages]

# Список услуг
services = {
    "service1": "Обход для всех операторов (на всегда:50+ серверов) - https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/refs/heads/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
}

class UserState(StatesGroup):
    waiting_for_service = State()
    waiting_for_subscription = State()
    waiting_for_support_message = State()

class AdminState(StatesGroup):
    waiting_for_reply = State()

# Функция проверки подписки
async def check_subscription(user_id: int):
    try:
        # Добавляем таймаут для запроса
        chat_member = await asyncio.wait_for(
            bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id),
            timeout=2.0  # Максимум 2 секунд ожидания
        )
        return chat_member.status in ['member', 'administrator', 'creator']
    except asyncio.TimeoutError:
        logger.error("Таймаут при проверке подписки")
        return False
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# Проверка является ли пользователь администратором
def is_admin(user_id: int):
    return user_id in ADMIN_IDS

def get_success_message(service_link):
    return (
        "✅ Спасибо за подписку!\n\n"
        "📋 Гайд по установке конфигов:\n"
        "1) Переходите по ссылке\n"
        "2) Копируйте все конфиги в ней\n"
        "3) Заходите в v2raytun/Happ\n"
        "4) Нажимаете на '+'\n"
        "5) Нажимаете импортировать из буфера обмена\n\n"
        "⁉️ Как понять какие конфиги работают:\n"
        "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
        "и те сервера которые имеют пинг могут работать.\n\n"
        "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n"
        f"{service_link}\n\n"
        "Для обновления ссылки используйте команду /sub"
    )

# Главное меню С кнопкой "Обновить" (после проверки подписки)
def main_menu_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔄 Обновить", callback_data="update"))
    keyboard.add(InlineKeyboardButton(text="👥 Рефералы", callback_data="referral"))
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_services_from_main"))
    keyboard.add(InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"))
    keyboard.adjust(2, 2)
    return keyboard.as_markup()

def sub_menu_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="👥 Рефералы", callback_data="referral"))
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_services_from_main"))
    keyboard.add(InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"))
    keyboard.adjust(2, 1)
    return keyboard.as_markup()

# Клавиатура для ответов от поддержки
def support_reply_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_from_support_reply"))
    keyboard.add(InlineKeyboardButton(text="🆘 Поддержка", callback_data="support"))
    keyboard.adjust(2)
    return keyboard.as_markup()


# Клавиатура выбора услуг
def services_keyboard():
    try:
        keyboard = InlineKeyboardBuilder()
        for service_id, service_desc in services.items():
            service_name = service_desc.split(' - ')[0]
            logger.info(f"Создаем кнопку для услуги: {service_id} - {service_name}")
            keyboard.add(InlineKeyboardButton(
                text=service_name,
                callback_data=f"service_{service_id}"
            ))
        keyboard.adjust(1)
        return keyboard.as_markup()
    except Exception as e:
        logger.error(f"Ошибка создания клавиатуры услуг: {e}")
        return None

# Клавиатура для проверки подписки (с кнопкой "Назад")
def subscription_check_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="check_subscription"))
    keyboard.add(InlineKeyboardButton(text="📢 Перейти в канал", url=CHANNEL_URL))
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_services"))
    keyboard.adjust(2, 1)
    return keyboard.as_markup()


# Клавиатура для поддержки
def support_keyboard():
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_from_support"))
    return keyboard.as_markup()


# Функции для работы с рефералами
def generate_referral_code(user_id: int):
    """Генерация уникального реферального кода"""
    secret_key = "your_secret_key"
    data = f"{user_id}{secret_key}{datetime.now().timestamp()}"
    return hashlib.md5(data.encode()).hexdigest()[:8].upper()


def get_referral_link(user_id: int, bot_username: str):
    """Генерация реферальной ссылки"""
    if user_id not in referral_data:
        referral_data[user_id] = {
            'referral_code': generate_referral_code(user_id),
            'referrals_count': 0,
            'referred_by': None
        }

    return f"https://t.me/{bot_username}?start=ref_{referral_data[user_id]['referral_code']}"


# Клавиатура для реферального меню
def referral_keyboard(bot_username: str, user_id: int):
    keyboard = InlineKeyboardBuilder()
    referral_link = get_referral_link(user_id, bot_username)

    keyboard.add(InlineKeyboardButton(
        text="📤 Поделиться ссылкой",
        url=f"https://t.me/share/url?url={referral_link}&text=Присоединяйся%20к%20нашему%20VPN%20сервису!"
    ))
    keyboard.add(InlineKeyboardButton(text="📊 Статистика", callback_data="referral_stats"))
    keyboard.add(
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))  # Убедитесь, что здесь back_to_main
    keyboard.adjust(1)
    return keyboard.as_markup()


# Функция для сохранения данных рефералов
def save_referral_data():
    try:
        with open('.venv/referral_data.json', 'w', encoding='utf-8') as f:
            data_to_save = {str(k): v for k, v in referral_data.items()}
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения реферальных данных: {e}")


def load_referral_data():
    global referral_data
    try:
        with open('.venv/referral_data.json', 'r', encoding='utf-8') as f:
            data_loaded = json.load(f)
            referral_data = {int(k): v for k, v in data_loaded.items()}
    except FileNotFoundError:
        referral_data = {}
    except Exception as e:
        logger.error(f"Ошибка загрузки реферальных данных: {e}")
        referral_data = {}

# Реферальная система
referral_data = {}

@router.message(F.text == "/stats")
async def stats_handler(message: types.Message):
    user_id = str(message.from_user.id)
    if user_id in referral_data:
        user_data = referral_data[user_id]
        referrals_count = len(user_data.get("referrals", []))
        await message.answer(f"У вас {referrals_count} рефералов")
    else:
        await message.answer("Данные не найдены")


async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

    try:
        print("Бот запускается...")
        await dp.start_polling(bot)
    except Exception as e:
        print(f"Ошибка при запуске бота: {e}")
    finally:
        # Сохраняем данные при завершении работы
        save_referral_data(referral_data)  # Теперь правильно
        print("Бот остановлен")


@dp.message(Command("test"))
async def cmd_test(message: types.Message, state: FSMContext):
    """Тестовая команда для проверки работы бота"""
    await state.clear()

    # Проверяем создание клавиатуры
    test_keyboard = services_keyboard()
    if test_keyboard is None:
        await message.answer("❌ Ошибка создания клавиатуры услуг")
        return

    # Проверяем обработчик
    await message.answer(
        "🧪 Тестовый режим - выберите услугу:",
        reply_markup=test_keyboard
    )

    # Добавляем тестовую кнопку
    test_builder = InlineKeyboardBuilder()
    test_builder.add(InlineKeyboardButton(
        text="🧪 Тестовая услуга",
        callback_data="test_service"
    ))
    await message.answer(
        "Или нажмите тестовую кнопку:",
        reply_markup=test_builder.as_markup()
    )

@dp.errors()
async def errors_handler(update: types.Update, exception: Exception):
    logger.error(f"Ошибка в обработчике: {exception}")
    return True

@dp.message(Command("debug_state"))
async def cmd_debug_state(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    user_data = await state.get_data()

    debug_info = (
        f"Текущее состояние: {current_state}\n"
        f"Данные пользователя: {user_data}\n"
        f"Выбранная услуга: {user_data.get('selected_service', 'Не выбрана')}\n"
        f"Список услуг: {list(services.keys())}"
    )

    await message.answer(f"<code>{debug_info}</code>", parse_mode="HTML")


@dp.callback_query(F.data == "check_subscription")
async def check_subscription_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        # Получаем данные из состояния
        user_data = await state.get_data()
        service_id = user_data.get('selected_service')

        logger.info(f"Данные пользователя: {user_data}")
        logger.info(f"Выбранная услуга: {service_id}")

        if not service_id:
            logger.error("Услуга не выбрана!")
            await callback.answer("❌ Ошибка: сначала выберите услугу", show_alert=True)
            return

        # Небольшая задержка для обновления статуса подписки
        logger.info("Ожидание обновления статуса подписки...")
        await asyncio.sleep(1)

        # Проверяем подписку
        logger.info(f"Проверяем подписку пользователя {callback.from_user.id} на канал {CHANNEL_ID}")
        is_subscribed = await check_subscription(callback.from_user.id)
        logger.info(f"Результат проверки подписки: {is_subscribed}")

        if is_subscribed:
            logger.info("Пользователь подписан, выдаем ссылку")
            service_link = services[service_id]

            # Сохраняем данные пользователя
            user_data_storage[callback.from_user.id] = {
                'service_id': service_id,
                'service_link': service_link
            }

            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )

            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()
            )
            await state.clear()
            logger.info("Пользователь успешно получил услугу")

        else:
            logger.warning(f"Пользователь {callback.from_user.id} не подписан на канал")
            error_message = (
                "❌ Вы не подписались на канал или подписка еще не обновилась!\n\n"
                "Пожалуйста:\n"
                "1. Убедитесь, что вы подписались на канал\n"
                "2. Нажмите кнопку 'Перейти в канал' для проверки\n"
                "3. Подождите несколько секунд после подписки\n"
                "4. Нажмите 'Проверить подписку' снова"
            )
            await callback.answer(error_message, show_alert=True)
    except Exception as e:  # Этот блок должен быть закрыт правильно
        logger.error(f"Критическая ошибка в обработчике проверки подписки: {e}")
        import traceback
        logger.error(f"Трассировка: {traceback.format_exc()}")
        await callback.answer("❌ Произошла критическая ошибка", show_alert=True)

# Команда /referral
@dp.message(Command("referral"))
async def cmd_referral(message: types.Message):
    bot_info = await bot.get_me()
    user_id = message.from_user.id

    if user_id not in referral_data:
        referral_data[user_id] = {
            'referral_code': generate_referral_code(user_id),
            'referrals_count': 0,
            'referred_by': None
        }

    referral_text = (
        "👥 Реферальная система\n\n"
        "Приглашайте друзей в нашего бота!\n\n"
        f"🔗 Ваша реферальная ссылка:\n"
        f"`{get_referral_link(user_id, bot_info.username)}`\n\n"
        "📈 Статистика:\n"
        f"• Приглашено друзей: {referral_data[user_id]['referrals_count']}\n\n"
        "Как пригласить друга:\n"
        "1. Поделитесь своей ссылкой с другом\n"
        "2. Друг переходит по ссылке и начинает использовать бота\n"
        "3. Статистика обновится автоматически"
    )

    await message.answer(
        referral_text,
        reply_markup=referral_keyboard(bot_info.username, user_id),
        parse_mode="Markdown"
    )

# Обработчик кнопки "Рефералы"
@dp.callback_query(F.data == "referral")
async def referral_handler(callback: types.CallbackQuery):
    await callback.answer()
    try:
        logger.info(f"Обработчик Рефералы вызван для пользователя {callback.from_user.id}")

        bot_info = await bot.get_me()
        user_id = callback.from_user.id

        if user_id not in referral_data:
            referral_data[user_id] = {
                'referral_code': generate_referral_code(user_id),
                'referrals_count': 0,
                'referred_by': None
            }

        referral_text = (
            "👥 Реферальная система\n\n"
            "Приглашайте друзей в нашего бота!\n\n"
            f"🔗 Ваша реферальная ссылка:\n"
            f"`{get_referral_link(user_id, bot_info.username)}`\n\n"
            "📈 Статистика:\n"
            f"• Приглашено друзей: {referral_data[user_id]['referrals_count']}"
        )

        await callback.message.edit_text(
            referral_text,
            reply_markup=referral_keyboard(bot_info.username, user_id),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка в обработчике Рефералы: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# Обработчик статистики рефералов
@dp.callback_query(F.data == "referral_stats")
async def referral_stats_handler(callback: types.CallbackQuery):
    await callback.answer()  # Убираем "часики" в Telegram

    user_id = callback.from_user.id

    if user_id not in referral_data:
        await callback.answer("❌ Данные не найдены", show_alert=True)
        return

    stats_text = (
        f"📊 Ваша реферальная статистика:\n\n"
        f"👥 Приглашено друзей: {referral_data[user_id]['referrals_count']}\n"
        f"🔗 Ваш реферальный код: {referral_data[user_id]['referral_code']}\n"
    )

    if referral_data[user_id]['referred_by']:
        stats_text += f"🤝 Вас пригласил: пользователь {referral_data[user_id]['referred_by']}\n"
    else:
        stats_text += "🤝 Вы пришли самостоятельно\n"

    # Создаем клавиатуру для возврата
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="🔙 Назад", callback_data="referral"))

    try:
        await callback.message.edit_text(
            stats_text,
            reply_markup=keyboard.as_markup()
        )
    except Exception as e:
        logger.error(f"Ошибка при редактировании сообщения со статистикой: {e}")
        await callback.answer("❌ Ошибка при отображении статистики", show_alert=True)


# Обработчик кнопки "Назад" из реферального меню
@dp.callback_query(F.data == "back_to_main")
async def back_to_main_handler(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_id = callback.from_user.id

        # Проверяем, есть ли у пользователя сохраненные данные об услуге
        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']

            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )

            # Проверяем, отличается ли новое сообщение от текущего
            current_text = callback.message.text
            if current_text != success_text:
                await callback.message.edit_text(
                    success_text,
                    reply_markup=main_menu_keyboard()
                )
            else:
                await callback.answer("Вы уже в главном меню")

        else:
            # Если данных нет, возвращаем к выбору услуги
            welcome_text = (
                "Добро пожаловать в наш VPN! 🌐\n"
                "Выберите услугу из списка ниже:"
            )

            current_text = callback.message.text
            if current_text != welcome_text:
                await callback.message.edit_text(
                    welcome_text,
                    reply_markup=services_keyboard()
                )
                await state.set_state(UserState.waiting_for_service)
            else:
                await callback.answer("Вы уже в меню выбора услуг")

        await callback.answer()
    except Exception as e:
        if "message is not modified" in str(e):
            await callback.answer("Вы уже в этом меню")
        else:
            logger.error(f"Ошибка в back_to_main_handler: {e}")
            await callback.answer("Произошла ошибка", show_alert=True)

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()
    referred_by = None

    # Проверяем реферальную ссылку
    if len(args) > 1 and args[1].startswith('ref_'):
        referral_code = args[1][4:]

        # Ищем пользователя с таким реферальным кодом
        for user_id, data in referral_data.items():
            if data['referral_code'] == referral_code and user_id != message.from_user.id:
                referred_by = user_id
                break

        # Если нашли реферера, сохраняем информацию
        if referred_by:
            if message.from_user.id not in referral_data:
                referral_data[message.from_user.id] = {
                    'referral_code': generate_referral_code(message.from_user.id),
                    'referrals_count': 0,
                    'referred_by': referred_by
                }
            else:
                referral_data[message.from_user.id]['referred_by'] = referred_by

            # Увеличиваем счетчик рефералов у пригласившего
            referral_data[referred_by]['referrals_count'] += 1

            # Уведомляем пригласившего
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 По вашей ссылке зарегистрировался новый пользователь!\n"
                    f"Теперь у вас {referral_data[referred_by]['referrals_count']} рефералов."
                )
            except:
                pass

    await state.clear()
    welcome_text = "Добро пожаловать в наш VPN! 🌐\nВыберите услугу из списка ниже:"

    if referred_by:
        welcome_text = "Добро пожаловать в наш VPN! 🌐\nВы зарегистрировались по реферальной ссылке!\nВыберите услугу из списка ниже:"

    await message.answer(
        welcome_text,
        reply_markup=services_keyboard()
    )
    await state.set_state(UserState.waiting_for_service)


@dp.callback_query(F.data.startswith("service_"))
async def select_service(callback: types.CallbackQuery, state: FSMContext):
    logger.info(f"Выбрана услуга: {callback.data}")
    await callback.answer()
    try:
        service_id = callback.data.split("_")[1]
        logger.info(f"ID услуги: {service_id}")

        if service_id not in services:
            logger.warning(f"Услуга {service_id} не найдена")
            await callback.answer("Услуга не найдена", show_alert=True)
            return

        logger.info(f"Услуга {service_id} найдена, обновляем состояние")
        await state.update_data(selected_service=service_id)
        subscription_text = (
            "📢 Для получения доступа к услуге необходимо подписаться на наш канал!\n"
            "После подписки нажмите кнопку 'Проверить подписку'"
        )

        await callback.message.edit_text(
            subscription_text,
            reply_markup=subscription_check_keyboard()
        )
        await state.set_state(UserState.waiting_for_subscription)

    except Exception as e:
        logger.error(f"Ошибка в select_service: {e}")
        await callback.answer("Произошла ошибка при выборе услуги", show_alert=True)


@dp.callback_query(F.data == "check_subscription", UserState.waiting_for_subscription)
async def your_handler(callback: types.CallbackQuery):
    await callback.answer()
async def check_subscription_handler(callback: types.CallbackQuery, state: FSMContext):
    try:
        user_data = await state.get_data()
        service_id = user_data.get('selected_service')

        if not service_id:
            await callback.answer("Ошибка: услуга не выбрана", show_alert=True)
            return

        # Добавляем небольшую задержку для обновления статуса подписки
        await asyncio.sleep()

        is_subscribed = await check_subscription(callback.from_user.id)

        if is_subscribed:
            service_link = services[service_id]

            # Сохраняем данные пользователя
            user_data_storage[callback.from_user.id] = {
                'service_id': service_id,
                'service_link': service_link
            }

            await callback.message.edit_text(
                get_success_message(service_link),
                reply_markup=main_menu_keyboard()
            )
            await state.clear()
        else:
            error_message = (
                "❌ Вы не подписались на канал или подписка еще не обновилась!\n\n"
                "Пожалуйста:\n"
                "1. Убедитесь, что вы подписались на канал\n"
                "2. Нажмите кнопку 'Перейти в канал' для проверки\n"
                "3. Подождите несколько секунд после подписки\n"
                "4. Нажмите 'Проверить подписку' снова"
            )
            await callback.answer(error_message, show_alert=True)

    except Exception as e:
        logger.error(f"Ошибка в обработчике проверки подписки: {e}")
        await callback.answer("Произошла ошибка при проверке подписки", show_alert=True)

# Команда /help для пользователей
@dp.message(Command("help"))
async def cmd_help(message: types.Message, state: FSMContext):
    # Проверяем, получал ли пользователь услугу
    if message.from_user.id not in user_data_storage:
        await message.answer("Сначала выберите услугу и подпишитесь на канал, используя /start")
        return

    await message.answer(
        "🆘 Поддержка\n"
        "Опишите вашу проблему, и мы постараемся помочь вам как можно скорее:",
        reply_markup=support_keyboard()
    )
    await state.set_state(UserState.waiting_for_support_message)


# Обработчик текстовых сообщений в режиме поддержки
@dp.message(UserState.waiting_for_support_message)
async def process_support_message(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id
        user_message = message.text

        # Сохраняем запрос в поддержку
        if user_id not in support_requests:
            support_requests[user_id] = []

        support_requests[user_id].append(user_message)

        # Уведомляем администраторов
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(
                    admin_id,
                    f"🆘 Новый запрос в поддержку от пользователя {user_id} (@{message.from_user.username or 'N/A'}):\n\n{user_message}"
                )
            except Exception as e:
                logger.error(f"Не удалось отправить уведомление администратору {admin_id}: {e}")

        await message.answer(
            "✅ Ваше сообщение отправлено в поддержку. Мы ответим вам в ближайшее время.",
            reply_markup=main_menu_keyboard()  # Теперь эта функция должна быть определена
        )
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка в process_support_message: {e}")
        # Альтернативная клавиатура на случай ошибки
        try:
            from aiogram.utils.keyboard import ReplyKeyboardBuilder
            builder = ReplyKeyboardBuilder()
            builder.add(types.KeyboardButton(text="/start"))
            await message.answer(
                "✅ Ваше сообщение отправлено в поддержку.",
                reply_markup=builder.as_markup(resize_keyboard=True)
            )
        except:
            await message.answer("✅ Ваше сообщение отправлено в поддержку.")
        await state.clear()


# Команда /support для администраторов
@dp.message(Command("support"))
async def cmd_support_admin(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return

    if not active_tickets:
        await message.answer("✅ На данный момент активных тикетов нет.")
        return

    tickets_text = "📋 АКТИВНЫЕ ТИКЕТЫ ПОДДЕРЖКИ:\n\n"

    keyboard = InlineKeyboardBuilder()

    for ticket_id in active_tickets:
        if ticket_id in support_tickets:
            ticket = support_tickets[ticket_id]
            tickets_text += (
                f"🔸 Тикет #{ticket_id}\n"
                f"👤 {ticket['user_id']} {ticket['username']}\n"
                f"📅 {ticket['created_at']}\n"
                f"💬 {ticket['messages'][0][:50]}...\n\n"
            )

            keyboard.add(InlineKeyboardButton(
                text=f"Тикет #{ticket_id} - {ticket['username']}",
                callback_data=f"admin_view_{ticket_id}"
            ))
    keyboard.adjust(1)
    await message.answer(tickets_text, reply_markup=keyboard.as_markup())


@dp.callback_query(F.data.startswith("admin_view_"))
async def admin_view_ticket(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return

    ticket_id = int(callback.data.split("_")[2])

    if ticket_id not in support_tickets:
        await callback.answer("❌ Тикет не найден")
        return

    ticket = support_tickets[ticket_id]

    ticket_text = (
        f"📋 ТИКЕТ #{ticket_id}\n\n"
        f"👤 Пользователь: {ticket['user_id']} {ticket['username']}\n"
        f"📅 Создан: {ticket['created_at']}\n"
        f"📊 Статус: {ticket['status']}\n\n"
        f"💬 Сообщения:\n"
    )

    for i, msg in enumerate(ticket['messages'], 1):
        ticket_text += f"{i}. {msg}\n"

    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📨 Ответить", callback_data=f"admin_reply_{ticket_id}"))
    keyboard.add(InlineKeyboardButton(text="🔒 Закрыть тикет", callback_data=f"admin_close_{ticket_id}"))
    keyboard.add(InlineKeyboardButton(text="🔙 Назад к списку", callback_data="admin_support_back"))

    await callback.message.edit_text(ticket_text, reply_markup=keyboard.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_reply_"))
async def admin_reply_ticket(callback: types.CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return

    ticket_id = int(callback.data.split("_")[2])

    if ticket_id not in support_tickets:
        await callback.answer("❌ Тикет не найден")
        return

    await state.update_data(admin_ticket_id=ticket_id)
    await state.set_state(AdminState.waiting_for_reply)

    await callback.message.answer(
        f"💬 Введите ответ для тикета #{ticket_id}:\n\n"
        f"Пользователь: {support_tickets[ticket_id]['user_id']} {support_tickets[ticket_id]['username']}"
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("admin_close_"))
async def admin_close_ticket(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return

    ticket_id = int(callback.data.split("_")[2])

    if ticket_id not in support_tickets:
        await callback.answer("❌ Тикет не найден")
        return

    support_tickets[ticket_id]['status'] = 'closed'
    if ticket_id in active_tickets:
        active_tickets.remove(ticket_id)

    await callback.answer("✅ Тикет закрыт")
    await callback.message.edit_text(
        f"✅ Тикет #{ticket_id} закрыт",
        reply_markup=InlineKeyboardBuilder()
        .add(InlineKeyboardButton(text="🔙 Назад к списку", callback_data="admin_support_back"))
        .as_markup()
    )


@dp.callback_query(F.data == "admin_support_back")
async def admin_support_back(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещен")
        return

    await cmd_support_admin(callback.message)
    await callback.answer()

# Обработчик выбора пользователя для ответа
@dp.callback_query(F.data.startswith("admin_support_"))
async def your_handler(callback: types.CallbackQuery):
    await callback.answer()
async def admin_select_user(callback: types.CallbackQuery, state: FSMContext):
    user_id = int(callback.data.split("_")[2])

    if user_id not in support_requests:
        await callback.answer("Запросы от этого пользователя не найдены", show_alert=True)
        return

    user_messages = "\n".join([f"• {msg}" for msg in support_requests[user_id]])

    await callback.message.edit_text(
        f"📨 Запросы от пользователя {user_id}:\n\n{user_messages}\n\n"
        f"Введите ответ для этого пользователя:",
    )

    await state.update_data(admin_reply_user_id=user_id)
    await state.set_state(AdminState.waiting_for_reply)
    await callback.answer()


# Обработчик ответа администратора
@dp.message(AdminState.waiting_for_reply)
async def admin_send_reply(message: types.Message, state: FSMContext):
    data = await state.get_data()
    ticket_id = data.get('admin_ticket_id')

    if not ticket_id or ticket_id not in support_tickets:
        await message.answer("❌ Ошибка: тикет не найден")
        await state.clear()
        return

    try:
        ticket = support_tickets[ticket_id]
        user_id = ticket['user_id']

        # Добавляем ответ в историю тикета
        ticket['messages'].append(f"👨‍💼 Поддержка: {message.text}")

        # Отправляем ответ пользователю
        await bot.send_message(
            user_id,
            f"📩 Ответ от поддержки (Тикет #{ticket_id}):\n\n"
            f"{message.text}\n\n"
            "Если у вас остались вопросы, напишите нам снова!",
            reply_markup=main_menu_keyboard()
        )

        await message.answer(f"✅ Ответ отправлен пользователю {user_id}")

        # Уведомляем других администраторов
        for admin_id in ADMIN_IDS:
            if admin_id != message.from_user.id:
                try:
                    await bot.send_message(
                        admin_id,
                        f"📨 Администратор ответил на тикет #{ticket_id}\n"
                        f"Пользователь: {user_id} {ticket['username']}"
                    )
                except:
                    pass

    except Exception as e:
        logger.error(f"Ошибка отправки ответа: {e}")
        await message.answer("❌ Не удалось отправить ответ")

    await state.clear()


# Команда /reply для администраторов (альтернативный способ)
@dp.message(Command("reply"))
async def cmd_reply_admin(message: types.Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("❌ У вас нет прав для использования этой команды.")
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❌ Использование: /reply <номер_тикета> <текст ответа>")
        return

    try:
        ticket_id = int(args[1])
        reply_text = args[2]

        if ticket_id not in support_tickets:
            await message.answer("❌ Тикет не найден")
            return

        ticket = support_tickets[ticket_id]
        user_id = ticket['user_id']

        # Добавляем ответ в историю тикета
        ticket['messages'].append(f"👨‍💼 Поддержка: {reply_text}")

        # Отправляем ответ пользователю
        await bot.send_message(
            user_id,
            f"📩 Ответ от поддержки (Тикет #{ticket_id}):\n\n"
            f"{reply_text}\n\n"
            "Если у вас остались вопросы, напишите нам снова!",
            reply_markup=main_menu_keyboard()
        )

        await message.answer(f"✅ Ответ отправлен пользователю {user_id}")

    except ValueError:
        await message.answer("❌ Неверный формат номера тикета")
    except Exception as e:
        logger.error(f"Ошибка отправки ответа через /reply: {e}")
        await message.answer("❌ Не удалось отправить ответ")


# Обработчик кнопки "Назад" из меню после /sub
@dp.callback_query(F.data == "back_from_sub_menu")
async def back_from_sub_menu_handler(callback: types.CallbackQuery):
    await callback.answer()
    try:
        user_id = callback.from_user.id
        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']

            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка в back_from_sub_menu_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@dp.message(Command("sub"))
async def cmd_sub(message: types.Message, state: FSMContext):
    try:
        user_id = message.from_user.id

        # Проверяем подписку
        if await check_subscription(user_id):
            # Проверяем, есть ли у пользователя сохраненная услуга
            if user_id in user_data_storage:
                service_link = user_data_storage[user_id]['service_link']

                update_text = (
                    f"Успешно обновлено✅\n"
                    f"Ваша ссылка на VPN конфиги:\n"
                    f"{service_link}"
                )

                await message.answer(
                    update_text,
                    reply_markup=sub_menu_keyboard()  # Используем специальную клавиатуру без "Обновить"
                )
            else:
                await message.answer(
                    "🔄 Обновление услуг\nВыберите услугу:",
                    reply_markup=services_keyboard()
                )
                await state.set_state(UserState.waiting_for_service)
        else:
            error_text = (
                "❌ Для доступа к услугам необходимо подписаться на наш канал!\n"
                "Пожалуйста, подпишитесь и попробуйте снова."
            )
            await message.answer(
                error_text,
                reply_markup=subscription_check_keyboard()
            )
            await state.set_state(UserState.waiting_for_subscription)

    except Exception as e:
        logger.error(f"Ошибка в команде /sub: {e}")
        await message.answer("Произошла ошибка при обновлении")


@dp.callback_query(F.data == "back_to_services_from_main")
async def back_to_services_from_main_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        user_id = callback.from_user.id

        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']

            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()  # Меню С кнопкой "Обновить"
            )
        else:
            welcome_text = (
                "Добро пожаловать в наш VPN! 🌐\n"
                "Выберите услугу из списка ниже:"
            )
            await callback.message.edit_text(
                welcome_text,
                reply_markup=services_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка в back_to_main_handlers: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

@dp.callback_query(F.data == "back_from_support_reply")
async def back_to_main_handlers(callback: types.CallbackQuery):
    await callback.answer()
    try:
        user_id = callback.from_user.id
        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']
            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()  # Меню С кнопкой "Обновить"
            )
        else:
            welcome_text = (
                "Добро пожаловать в наш VPN! 🌐\n"
                "Выберите услугу из списка ниже:"
            )
            await callback.message.edit_text(
                welcome_text,
                reply_markup=services_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка в back_to_main_handlers: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

# Обработчик кнопки "Назад" из поддержки
@dp.callback_query(F.data == "back_from_support")
async def back_from_support_handler(callback: types.CallbackQuery):
    await callback.answer()
    try:
        user_id = callback.from_user.id
        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']
            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()  # Теперь с кнопкой "Обновить"
            )
        else:
            welcome_text = (
                "Добро пожаловать в наш VPN! 🌐\n"
                "Выберите услугу из списка ниже:"
            )
            await callback.message.edit_text(
                welcome_text,
                reply_markup=services_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка в back_from_support_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# Обработчик кнопки "Назад" из ответа поддержки
@dp.callback_query(F.data == "back_from_support_reply")
async def back_from_support_reply_handler(callback: types.CallbackQuery):
    await callback.answer()
    try:
        user_id = callback.from_user.id
        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']

            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1) Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n"
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()  # Теперь с кнопкой "Обновить"
            )
        else:
            welcome_text = (
                "Добро пожаловать в наш VPN! 🌐\n"
                "Выберите услугу из списка ниже:"
            )
            await callback.message.edit_text(
                welcome_text,
                reply_markup=services_keyboard()
            )

    except Exception as e:
        logger.error(f"Ошибка в back_from_support_reply_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


# ПЕРЕПИСАННЫЙ обработчик кнопки "Обновить" и команды /sub
@dp.callback_query(F.data == "update")
async def update_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        user_id = callback.from_user.id
        if await check_subscription(user_id):
            if user_id in user_data_storage:
                service_link = user_data_storage[user_id]['service_link']

                update_text = (
                    f"Успешно обновлено✅\n"
                    f"Ваша ссылка на VPN конфиги:\n"
                    f"{service_link}"
                )

                await callback.message.edit_text(
                    update_text,
                    reply_markup=main_menu_keyboard()  # БЕЗ кнопки "Обновить"
                )
            else:
                await callback.message.edit_text(
                    "🔄 Обновление услуг\nВыберите услугу:",
                    reply_markup=services_keyboard()
                )
                await state.set_state(UserState.waiting_for_service)
        else:
            error_text = (
                "❌ Для доступа к услугам необходимо подписаться на наш канал!\n"
                "Пожалуйста, подпишитесь и попробуйте снова."
            )
            await callback.message.edit_text(
                error_text,
                reply_markup=subscription_check_keyboard()
            )
            await state.set_state(UserState.waiting_for_subscription)
    except Exception as e:
        logger.error(f"Ошибка в обработчике Обновить: {e}")
        await callback.answer("Произошла ошибка при обновлении", show_alert=True)


@dp.callback_query(F.data == "support")
async def support_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_text(
            "🆘 Поддержка\n\n"
            "Опишите вашу проблему или вопрос, и мы ответим вам в ближайшее время.\n\n"
            "Просто напишите ваше сообщение ниже:",
            reply_markup=InlineKeyboardBuilder()
                .add(InlineKeyboardButton(text="🔙 Отмена", callback_data="cancel_support"))
                .as_markup()
        )
        await state.set_state(UserState.waiting_for_support_message)
    except Exception as e:
        logger.error(f"Ошибка в support_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)


@dp.callback_query(F.data == "cancel_support", UserState.waiting_for_support_message)
async def cancel_support_handler(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        user_id = callback.from_user.id

        if user_id in user_data_storage:
            service_link = user_data_storage[user_id]['service_link']
            success_text = (
                "✅ Спасибо за подписку!\n\n"
                "📋 Гайд по установке конфигов:\n"
                "1) Переходите по ссылке\n"
                "2) Копируйте все конфиги в ней\n"
                "3) Заходите в v2raytun/Happ\n"
                "4) Нажимаете на '+'\n"
                "5) Нажимаете импортировать из буфера обмена\n"
                "⁉️ Как понять какие конфиги работают:\n"
                "1)Заходите в ваше приложение (v2raytun/Happ) и пингуете сервера,"
                "и те сервера которые имеют пинг могут работать.\n\n" 
                "🎉 И все ваши конфиги подключены, в случае чего пишите в поддержку /help!\n\n"
                f"{service_link}\n\n"
                "Для получения дополнительных ссылок используйте команду /sub"
            )
            await callback.message.edit_text(
                success_text,
                reply_markup=main_menu_keyboard()
            )
        else:
            await callback.message.edit_text(
                "Добро пожаловать в наш VPN! 🌐\nВыберите услугу:",
                reply_markup=services_keyboard()
            )
            await state.set_state(UserState.waiting_for_service)

        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка в cancel_support_handler: {e}")
        await callback.answer("Произошла ошибка", show_alert=True)

def check_bot_running():
    try:
        lock_file = ".venv/bot_running.lock"
        if os.path.exists(lock_file):
            # Пытаемся прочитать PID из файла
            try:
                with open(lock_file, 'r') as f:
                    old_pid = int(f.read().strip())

                # Проверяем, существует ли процесс с этим PID
                try:
                    os.kill(old_pid, 0)  # Проверка существования процесса
                    print("❌ Бот уже запущен! Завершите предыдущий процесс.")
                    sys.exit(1)
                except OSError:
                    # Процесс не существует, удаляем старый lock-файл
                    print("⚠️ Удален lock-файл от несуществующего процесса")
                    os.remove(lock_file)
            except (ValueError, IOError):
                # Файл поврежден, удаляем его
                os.remove(lock_file)

        # Создаем новый lock-файл
        with open(lock_file, 'w') as f:
            f.write(str(os.getpid()))

        return lock_file
    except Exception as e:
        print(f"Ошибка проверки запуска: {e}")
        return None

def cleanup(lock_file):
    if lock_file and os.path.exists(lock_file):
        os.remove(lock_file)


if __name__ == "__main__":
    load_referral_data()

    # Проверка на множественный запуск
    lock_file = check_bot_running()
    if lock_file:
        atexit.register(cleanup, lock_file)
        atexit.register(save_referral_data)

    logger.info("Бот запущен")
    logger.info(f"ID канала для проверки: {CHANNEL_ID}")
    try:
        dp.run_polling(bot)
    except KeyboardInterrupt:
        print("\nБот остановлен пользователем")
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
    finally:
        save_referral_data()