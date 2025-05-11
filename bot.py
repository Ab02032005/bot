import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from dotenv import load_dotenv

# === Настройки логирования ===
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# === Загрузка переменных окружения ===
load_dotenv()
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_ID = os.getenv("ADMIN_USER_ID")

if not TOKEN or len(TOKEN) < 36:
    raise ValueError("Неверный или отсутствующий токен бота!")

# === Файл для сохранения заказов ===
ORDERS_FILE = 'orders.json'

# === Состояния пользователя ===
AWAITING_PAYMENT_CONFIRMATION = 'awaiting_payment_confirmation'

# === Товары ===
products = {
    "apple": {"id": "apple", "name": "🍎 Яблоко", "price": 50},
    "banana": {"id": "banana", "name": "🍌 Банан", "price": 70},
    "orange": {"id": "orange", "name": "🍊 Апельсин", "price": 80},
    "bread": {"id": "bread", "name": "🍞 Хлеб", "price": 40},
}

# === Загрузка/сохранение заказов из файла ===
def load_orders():
    if os.path.exists(ORDERS_FILE):
        with open(ORDERS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_order(order):
    orders = load_orders()
    orders.append(order)
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

# === Проверка прав администратора ===
def is_admin(user_id):
    return str(user_id) == ADMIN_ID

def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if not is_admin(user.id):
            await update.message.reply_text("❌ У вас нет прав администратора.")
            return
        return await handler(update, context)
    return wrapper

# === Команда /start ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart_count = len(context.user_data.get('cart', []))
    keyboard = [
        [InlineKeyboardButton("🍴 Меню", callback_data='menu')],
        [InlineKeyboardButton(f"🛒 Корзина ({cart_count})", callback_data='cart')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.message:
        await update.message.reply_text(
            "*Добро пожаловать в наш магазин!*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )
    else:
        await update.callback_query.message.edit_text(
            "*Добро пожаловать в наш магазин!*",
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

# === Команда /help ===
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📚 Доступные команды:\n"
        "/start - начать работу с ботом\n"
        "/help - показать это сообщение\n"
        "/checkout - оформить заказ"
    )

# === Обработчик текстовых сообщений (адрес доставки) ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data.get('state') == AWAITING_PAYMENT_CONFIRMATION:
        address = update.message.text.strip()
        if address:
            context.user_data['delivery_address'] = address
            context.user_data['state'] = None
            keyboard = [[InlineKeyboardButton("💳 Перейти к оплате", callback_data='pay_tinkoff')]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("Адрес сохранён. Теперь можно оплатить.", reply_markup=reply_markup)
        else:
            await update.message.reply_text("❌ Адрес не может быть пустым. Попробуйте ещё раз.")

# === Команда /checkout ===
async def checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cart = context.user_data.get('cart', [])
    if not cart:
        await update.message.reply_text("🛒 Ваша корзина пуста.")
        return

    total = sum(item['price'] for item in cart)
    cart_text = "\n".join([f"{item['name']} - {item['price']} руб." for item in cart])

    # Сохраняем заказ
    order = {
        'user_id': update.effective_user.id,
        'user_name': update.effective_user.full_name,
        'cart': cart,
        'total': total,
        'status': 'pending'
    }

    context.user_data['current_order'] = order

    keyboard = [[InlineKeyboardButton("💳 Оплатить через Тинькофф", callback_data='pay_tinkoff')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"*Ваш заказ:*\n{cart_text}\n\n*Итого: {total} руб.*\n"
        "Нажмите «Оплатить через Тинькофф», чтобы получить реквизиты.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# === Обработчик кнопок ===
async def main_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Ошибка при ответе на callback: {e}")
        return

    data = query.data

    if data == 'menu':
        await show_menu(update, context)
    elif data == 'cart':
        await show_cart(update, context)
    elif data == 'back':
        await start(update, context)
    elif data == 'clear_cart':
        await clear_cart(update, context)
    elif data.startswith('add_'):
        await add_to_cart(update, context)
    elif data.startswith('remove_'):
        await remove_from_cart(update, context)
    elif data == 'checkout_order':
        await checkout_order(update, context)
    elif data == 'pay_tinkoff':
        await pay_tinkoff(update, context)
    elif data == 'confirm_payment':
        await confirm_payment(update, context)
    elif data.startswith('approve_'):
        await approve_payment(update, context)

# === Клавиатурное меню ===
async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    keyboard = []
    for product_id, product in products.items():
        keyboard.append([InlineKeyboardButton(
            f"{product['name']} - {product['price']} руб.",
            callback_data=f"add_{product_id}"
        )])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data='back')])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text("*Выберите продукт:*", parse_mode='Markdown', reply_markup=reply_markup)

async def add_to_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    product_id = query.data.split('_')[1]
    if 'cart' not in context.user_data:
        context.user_data['cart'] = []
    context.user_data['cart'].append(products[product_id])
    await query.answer(f"✅ Добавлено: {products[product_id]['name']}")

async def remove_from_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    index = int(query.data.split('_')[1])
    cart = context.user_data.get('cart', [])
    if 0 <= index < len(cart):
        removed = cart.pop(index)
        context.user_data['cart'] = cart
        await query.answer(f"❌ Удалено: {removed['name']}")
    await show_cart(update, context)

async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = context.user_data.get('cart', [])
    if not cart:
        await query.edit_message_text("🛒 Ваша корзина пуста!")
        return

    total = sum(item['price'] for item in cart)
    cart_text = "\n".join([f"{i+1}. {item['name']} - {item['price']} руб." for i, item in enumerate(cart)])
    
    keyboard = [
        [InlineKeyboardButton("🍴 В меню", callback_data='menu')],
        [InlineKeyboardButton("🗑 Очистить корзину", callback_data='clear_cart')],
        [InlineKeyboardButton("📦 Оформить заказ", callback_data='checkout_order')]
    ]

    for i in range(len(cart)):
        keyboard.append([InlineKeyboardButton(f"❌ Удалить товар #{i+1}", callback_data=f"remove_{i}")])

    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(
        f"*Ваш заказ:*\n{cart_text}\n\n*Итого: {total} руб.*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    context.user_data['cart'] = []
    await query.answer("🗑 Корзина очищена!")
    await show_cart(update, context)

# === Кнопка "Оформить заказ" ===
async def checkout_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    cart = context.user_data.get('cart', [])
    if not cart:
        await query.edit_message_text("🛒 Ваша корзина пуста!")
        return

    total = sum(item['price'] for item in cart)
    cart_text = "\n".join([f"{item['name']} - {item['price']} руб." for item in cart])

    context.user_data['current_order'] = {
        'cart': cart,
        'total': total,
        'user_id': update.effective_user.id,
        'user_name': update.effective_user.full_name,
        'status': 'pending'
    }

    keyboard = [[InlineKeyboardButton("💳 Оплатить через Тинькофф", callback_data='pay_tinkoff')]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        f"*Ваш заказ:*\n{cart_text}\n\n*Итого: {total} руб.*\n"
        "Нажмите «Оплатить через Тинькофф», чтобы продолжить.",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

# === Оплата через Тинькофф ===
async def pay_tinkoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    order = context.user_data.get('current_order')
    if not order:
        await query.edit_message_text("❌ Не найдено данных о заказе.")
        return

    tinkoff_details = (
        "💳 *Реквизиты для оплаты (Тинькофф)*\n"
        "Номер карты: `2200 7019 3724 2698`\n"
        "Тел: 89225075311\n"
        "ФИО: Белоусов Андрей Николаевич\n"
        f"💰 Сумма: {order['total']} руб."
    )

    await query.message.reply_text(tinkoff_details, parse_mode='Markdown')
    context.user_data['state'] = AWAITING_PAYMENT_CONFIRMATION

    keyboard = [[InlineKeyboardButton("✅ Я оплатил", callback_data='confirm_payment')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_reply_markup(reply_markup=reply_markup)

# === Подтверждение оплаты пользователем ===
async def confirm_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Ожидание подтверждения администратором...")

    order = context.user_data.get('current_order')
    if not order:
        await query.edit_message_text("❌ Заказ не найден.")
        return

    user = update.effective_user
    message = (
        f"🔔 *Новый заказ №{hash(user.id)}*\n"
        f"Клиент: {user.full_name} (ID: {user.id})\n"
        f"Товары:\n" + "\n".join([f"- {item['name']} - {item['price']} руб." for item in order['cart']]) +
        f"\n💰 Сумма: {order['total']} руб.\n"
        "Нажмите кнопку ниже, чтобы подтвердить оплату:"
    )

    keyboard = [[InlineKeyboardButton("✅ Подтвердить оплату", callback_data=f"approve_{user.id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if ADMIN_ID:
        await context.bot.send_message(chat_id=ADMIN_ID, text=message, parse_mode='Markdown', reply_markup=reply_markup)
    else:
        logger.warning("Не указан ADMIN_ID — невозможно отправить сообщение админу.")

    await query.edit_message_text("📸 Отправьте чек или нажмите «Я оплатил», чтобы мы могли проверить платёж.")

# === Подтверждение админом ===
async def approve_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = int(query.data.split('_')[1])
    user = await context.bot.get_chat(user_id)

    # Подтверждаем оплату
    await query.answer("✅ Оплата подтверждена!")
    await context.bot.send_message(chat_id=user_id, text="✅ Ваш платёж подтверждён! Спасибо за покупку!")

    # Обновляем статус заказа и сохраняем его
    order = context.user_data.get('current_order')
    if order:
        order['status'] = 'paid'
        save_order(order)

    # Очищаем данные
    context.user_data['cart'] = []
    context.user_data['current_order'] = None
    context.user_data['state'] = None

    # Чек клиенту
    receipt = (
        "🧾 *Чек*\n"
        f"Покупатель: {user.full_name} (ID: {user.id})\n"
        "Заказанные товары:\n" + "\n".join([f"- {item['name']} - {item['price']} руб." for item in order['cart']]) +
        f"\n💰 Итого: {order['total']} руб.\n"
        "Спасибо за покупку!"
    )
    await context.bot.send_message(chat_id=user_id, text=receipt, parse_mode='Markdown')

# === Админ-панель ===
@admin_only
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔐 *Админ-панель*\n"
        "/orders — посмотреть последние заказы\n"
        "/list_products — список товаров\n"
        "/add_product <название> <цена> — добавить товар\n"
        "/remove_product <id> — удалить товар",
        parse_mode='Markdown'
    )

@admin_only
async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders_list = load_orders()
    if not orders_list:
        await update.message.reply_text("Нет оформленных заказов.")
        return

    for order in orders_list[-5:]:
        msg = (
            f"📦 Заказ от {order['user_name']} (ID: {order['user_id']})\n"
            f"Статус: {order['status']}\n"
            "Товары:\n" + "\n".join([f"- {item['name']} - {item['price']} руб." for item in order['cart']]) +
            f"\n💰 Сумма: {order['total']} руб."
        )
        await update.message.reply_text(msg)

@admin_only
async def list_products_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "*Список товаров:*\n"
    for pid, product in products.items():
        msg += f"\n{product['name']} — {product['price']} руб."
    await update.message.reply_text(msg, parse_mode='Markdown')

@admin_only
async def add_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        name = context.args[0]
        price = int(context.args[1])
        product_id = name.lower()
        products[product_id] = {"id": product_id, "name": name, "price": price}
        await update.message.reply_text(f"✅ Товар '{name}' добавлен.")
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Используйте: /add_product <название> <цена>")

@admin_only
async def remove_product_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        product_id = context.args[0].lower()
        if product_id in products:
            del products[product_id]
            await update.message.reply_text(f"✅ Товар '{product_id}' удалён.")
        else:
            await update.message.reply_text(f"❌ Товар '{product_id}' не найден.")
    except IndexError:
        await update.message.reply_text("❌ Используйте: /remove_product <id>")

# === Обработчик всех кнопок ===
async def main_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"Ошибка при ответе на callback: {e}")
        return

    data = query.data

    if data == 'menu':
        await show_menu(update, context)
    elif data == 'cart':
        await show_cart(update, context)
    elif data == 'back':
        await start(update, context)
    elif data == 'clear_cart':
        await clear_cart(update, context)
    elif data.startswith('add_'):
        await add_to_cart(update, context)
    elif data.startswith('remove_'):
        await remove_from_cart(update, context)
    elif data == 'checkout_order':
        await checkout_order(update, context)
    elif data == 'pay_tinkoff':
        await pay_tinkoff(update, context)
    elif data == 'confirm_payment':
        await confirm_payment(update, context)
    elif data.startswith('approve_'):
        await approve_payment(update, context)

# === Команда /orders (админ) ===
@admin_only
async def list_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    orders_list = load_orders()
    if not orders_list:
        await update.message.reply_text("Нет оформленных заказов.")
        return
    for order in orders_list[-5:]:
        msg = (
            f"📦 Заказ от {order['user_name']} (ID: {order['user_id']})\n"
            f"Статус: {order['status']}\n"
            "Товары:\n" + "\n".join([f"- {item['name']} - {item['price']} руб." for item in order['cart']]) +
            f"\n💰 Сумма: {order['total']} руб."
        )
        await update.message.reply_text(msg)

# === Обработчик всех кнопок ===
async def main_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        logger.warning(f"[Callback] Ошибка: {e}")
        return

    data = query.data

    if data == 'menu':
        await show_menu(update, context)
    elif data == 'cart':
        await show_cart(update, context)
    elif data == 'back':
        await start(update, context)
    elif data == 'clear_cart':
        await clear_cart(update, context)
    elif data.startswith('add_'):
        await add_to_cart(update, context)
    elif data.startswith('remove_'):
        await remove_from_cart(update, context)
    elif data == 'checkout_order':
        await checkout_order(update, context)
    elif data == 'pay_tinkoff':
        await pay_tinkoff(update, context)
    elif data == 'confirm_payment':
        await confirm_payment(update, context)
    elif data.startswith('approve_'):
        await approve_payment(update, context)

# === Сохранение заказа в файл ===
def save_order(order):
    orders = load_orders()
    orders.append(order)
    with open(ORDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(orders, f, ensure_ascii=False, indent=2)

# === Обработка ошибок ===
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Логирование ошибок"""
    logger.error(f"Ошибка при обработке обновления: {context.update}, ошибка: {context.error}")
    if update and hasattr(update, 'callback_query') and update.callback_query:
        try:
            await update.callback_query.answer("❌ Произошла внутренняя ошибка.")
        except Exception as e:
            print(f"[ERROR] Не удалось отправить ответ на callback: {e}")
    elif update and hasattr(update, 'message'):
        try:
            await update.message.reply_text("⚠️ Произошла внутренняя ошибка. Попробуйте снова.")
        except Exception as e:
            print(f"[ERROR] Не удалось отправить сообщение пользователю: {e}")
# === Запуск бота ===
def main():
    app = Application.builder().token(TOKEN).build()

    # === Команды ===
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('admin', admin))
    app.add_handler(CommandHandler('orders', list_orders))
    app.add_handler(CommandHandler('list_products', list_products_cmd))
    app.add_handler(CommandHandler('add_product', add_product_cmd))
    app.add_handler(CommandHandler('remove_product', remove_product_cmd))

    # === Кнопки ===
    app.add_handler(CallbackQueryHandler(main_button_handler))

    # === Сообщения ===
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_message))

    # === Обработка ошибок ===
    app.add_error_handler(error_handler)

    print("✅ Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()
