# delivery_bot.py
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# ==================== KONFIGURATSIYA ====================
TOKEN = "8753597096:aafneqoidkyzatgrcuiqn22c0tnahc5jts0"  # Bot tokenini kiriting
ADMIN_IDS = [6713905538]  # Adminlar Telegram ID ro'yxati

# Komissiya sozlamalari
COMMISSION_AMOUNT = 500  # So'mda (500-1000 oralig'ida)

# ==================== MA'LUMOTLAR BAZASI ====================
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('delivery_bot.db', check_same_thread=False)
        self._create_tables()
    
    def _create_tables(self):
        cursor = self.conn.cursor()
        
        # Foydalanuvchilar
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                full_name TEXT,
                phone TEXT,
                user_type TEXT,
                balance INTEGER DEFAULT 0,
                created_at TIMESTAMP
            )
        ''')
        
        # Haydovchilar/Kuryerlar
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS drivers (
                user_id INTEGER PRIMARY KEY,
                car_model TEXT,
                plate_number TEXT,
                is_available INTEGER DEFAULT 1,
                rating REAL DEFAULT 5.0,
                total_orders INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        # Buyurtmalar
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER,
                driver_id INTEGER,
                pickup_address TEXT,
                delivery_address TEXT,
                customer_phone TEXT,
                status TEXT,
                amount INTEGER,
                commission INTEGER,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (customer_id) REFERENCES users (user_id),
                FOREIGN KEY (driver_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
    
    def add_user(self, user_id: int, full_name: str, phone: str, user_type: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, full_name, phone, user_type, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id, full_name, phone, user_type, datetime.now()))
        self.conn.commit()
    
    def get_user(self, user_id: int) -> Optional[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def add_driver(self, user_id: int, car_model: str, plate_number: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO drivers (user_id, car_model, plate_number)
            VALUES (?, ?, ?)
        ''', (user_id, car_model, plate_number))
        self.conn.commit()
    
    def add_order(self, customer_id: int, pickup: str, delivery: str, phone: str, amount: int) -> int:
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO orders (customer_id, pickup_address, delivery_address, customer_phone, 
                               status, amount, commission, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (customer_id, pickup, delivery, phone, 'pending', amount, COMMISSION_AMOUNT, datetime.now()))
        self.conn.commit()
        return cursor.lastrowid
    
    def update_order_status(self, order_id: int, status: str, driver_id: int = None):
        cursor = self.conn.cursor()
        if driver_id:
            cursor.execute('''
                UPDATE orders SET driver_id = ?, status = ? WHERE order_id = ?
            ''', (driver_id, status, order_id))
        else:
            cursor.execute('''
                UPDATE orders SET status = ? WHERE order_id = ?
            ''', (status, order_id))
        
        if status == 'completed':
            cursor.execute('''
                UPDATE orders SET completed_at = ? WHERE order_id = ?
            ''', (datetime.now(), order_id))
            
            # Komissiyani hisoblash
            cursor.execute('SELECT commission FROM orders WHERE order_id = ?', (order_id,))
            commission = cursor.fetchone()[0]
            
            # Admin balansiga qo'shish
            cursor.execute('''
                UPDATE users SET balance = balance + ? WHERE user_id = ?
            ''', (commission, 1))  # 1 - admin user_id
        
        self.conn.commit()
    
    def get_pending_orders(self) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT order_id, pickup_address, delivery_address, amount 
            FROM orders WHERE status = 'pending'
        ''')
        return cursor.fetchall()
    
    def get_driver_orders(self, driver_id: int) -> list:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT order_id, pickup_address, delivery_address, status, amount
            FROM orders WHERE driver_id = ? ORDER BY created_at DESC
        ''', (driver_id,))
        return cursor.fetchall()

db = Database()

# ==================== HOLATLAR ====================
class States(Enum):
    MAIN = 0
    WAITING_PHONE = 1
    WAITING_CAR_MODEL = 2
    WAITING_PLATE_NUMBER = 3
    WAITING_PICKUP = 4
    WAITING_DELIVERY = 5
    WAITING_ORDER_PHONE = 6

# ==================== KLAVIATURALAR ====================
def get_main_keyboard(user_type: str = 'customer'):
    if user_type == 'driver':
        keyboard = [
            [KeyboardButton("🚗 Mavjudlik holati"), KeyboardButton("📋 Mening buyurtmalarim")],
            [KeyboardButton("💰 Mening balansim"), KeyboardButton("⭐ Reytingim")],
            [KeyboardButton("ℹ️ Yordam")]
        ]
    else:
        keyboard = [
            [KeyboardButton("🚕 Buyurtma berish")],
            [KeyboardButton("📋 Mening buyurtmalarim"), KeyboardButton("💰 Mening balansim")],
            [KeyboardButton("ℹ️ Yordam")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==================== ADMIN FUNKSIYALAR ====================
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Siz admin emassiz!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
        [InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users")],
        [InlineKeyboardButton("🚗 Haydovchilar", callback_data="admin_drivers")],
        [InlineKeyboardButton("📦 Buyurtmalar", callback_data="admin_orders")],
        [InlineKeyboardButton("⚙️ Komissiya sozlamalari", callback_data="admin_commission")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👨‍💼 Admin panel", reply_markup=reply_markup)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔ Ruxsat yo'q!")
        return
    
    data = query.data
    
    if data == "admin_stats":
        cursor = db.conn.cursor()
        
        # Statistika
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM users WHERE user_type = 'driver'")
        total_drivers = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM orders")
        total_orders = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(commission) FROM orders WHERE status = 'completed'")
        total_commission = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'pending'")
        pending_orders = cursor.fetchone()[0]
        
        text = f"""
📊 **Statistika**

👥 Foydalanuvchilar: {total_users}
🚗 Haydovchilar: {total_drivers}
📦 Jami buyurtmalar: {total_orders}
⏳ Kutilayotgan: {pending_orders}
💰 Umumiy komissiya: {total_commission:,} so'm
        """
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_users":
        cursor = db.conn.cursor()
        cursor.execute("SELECT user_id, full_name, user_type, created_at FROM users LIMIT 20")
        users = cursor.fetchall()
        
        text = "👥 **Foydalanuvchilar ro'yxati:**\n\n"
        for user in users:
            text += f"ID: `{user[0]}`\n👤 {user[1]}\n📌 {user[2]}\n📅 {user[3]}\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_orders":
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT order_id, pickup_address, delivery_address, status, amount 
            FROM orders ORDER BY created_at DESC LIMIT 20
        """)
        orders = cursor.fetchall()
        
        text = "📦 **Buyurtmalar:**\n\n"
        for order in orders:
            text += f"#{order[0]} | {order[3]}\n📍 {order[1][:30]} → {order[2][:30]}\n💰 {order[4]} so'm\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

# ==================== BOT ASOSIY FUNKSIYALAR ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    
    # Foydalanuvchini tekshirish
    user = db.get_user(user_id)
    if not user:
        await update.message.reply_text(
            f"👋 Assalomu alaykum, {full_name}!\n\n"
            "Botimizga xush kelibsiz! Iltimos, telefon raqamingizni yuboring.\n\n"
            "📱 Telefon raqamni yuborish uchun pastdagi tugmani bosing.",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton("📱 Telefon raqamni yuborish", request_contact=True)]],
                resize_keyboard=True
            )
        )
        return States.WAITING_PHONE
    
    user_type = user[3]
    await update.message.reply_text(
        f"👋 Xush kelibsiz, {full_name}!\n\n"
        f"Sizning ro'lingiz: {'🚗 Haydovchi' if user_type == 'driver' else '👤 Mijoz'}",
        reply_markup=get_main_keyboard(user_type)
    )
    return States.MAIN

async def handle_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    user_id = update.effective_user.id
    full_name = update.effective_user.full_name
    phone = contact.phone_number
    
    db.add_user(user_id, full_name, phone, 'customer')
    
    await update.message.reply_text(
        "✅ Telefon raqam qabul qilindi!\n\n"
        "Endi siz quyidagi xizmatlardan foydalanishingiz mumkin:\n"
        "🚕 Buyurtma berish\n"
        "📋 Mening buyurtmalarim\n"
        "💰 Mening balansim\n\n"
        "Agar haydovchi sifatida ro'yxatdan o'tmoqchi bo'lsangiz, /driver buyrug'ini yuboring.",
        reply_markup=get_main_keyboard('customer')
    )
    return States.MAIN

async def register_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    await update.message.reply_text(
        "🚗 Haydovchi sifatida ro'yxatdan o'tish\n\n"
        "Avtomobilingiz modelini kiriting:\n"
        "Masalan: Chevrolet Lacetti, 2018"
    )
    return States.WAITING_CAR_MODEL

async def get_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['car_model'] = update.message.text
    
    await update.message.reply_text(
        "🚘 Davlat raqamini kiriting:\n"
        "Masalan: 01 A 123 AA"
    )
    return States.WAITING_PLATE_NUMBER

async def get_plate_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    car_model = context.user_data.get('car_model')
    plate_number = update.message.text
    
    db.add_driver(user_id, car_model, plate_number)
    db.add_user(user_id, update.effective_user.full_name, '', 'driver')
    
    await update.message.reply_text(
        "✅ Haydovchi sifatida ro'yxatdan o'tdingiz!\n\n"
        "Endi siz buyurtmalarni qabul qilishingiz mumkin.\n"
        "Mavjud buyurtmalarni ko'rish uchun /orders buyrug'ini yuboring.",
        reply_markup=get_main_keyboard('driver')
    )
    return States.MAIN

async def create_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📍 **Yangi buyurtma**\n\n"
        "Qayerdan olish joyini kiriting:\n"
        "Masalan: Toshkent, Chilonzor, 5-mavze",
        parse_mode=ParseMode.MARKDOWN
    )
    return States.WAITING_PICKUP

async def get_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['pickup'] = update.message.text
    
    await update.message.reply_text(
        "📍 Qayerga yetkazib berish joyini kiriting:"
    )
    return States.WAITING_DELIVERY

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['delivery'] = update.message.text
    
    await update.message.reply_text(
        "📞 Mijozning telefon raqamini kiriting:"
    )
    return States.WAITING_ORDER_PHONE

async def get_order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    pickup = context.user_data.get('pickup')
    delivery = context.user_data.get('delivery')
    phone = update.message.text
    
    # Buyurtma narxini hisoblash (masofa bo'yicha)
    amount = 15000  # Asosiy narx
    
    order_id = db.add_order(user_id, pickup, delivery, phone, amount)
    
    # Haydovchilarga xabar yuborish
    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id FROM drivers WHERE is_available = 1")
    drivers = cursor.fetchall()
    
    for driver in drivers:
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept_{order_id}")]
            ])
            await context.bot.send_message(
                driver[0],
                f"🚗 **Yangi buyurtma!**\n\n"
                f"#{order_id}\n"
                f"📍 Olib ketish: {pickup}\n"
                f"📍 Yetkazish: {delivery}\n"
                f"💰 Narx: {amount:,} so'm\n"
                f"📞 Mijoz: {phone}\n\n"
                f"Komissiya: {COMMISSION_AMOUNT:,} so'm",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        except:
            pass
    
    await update.message.reply_text(
        f"✅ Buyurtma yaratildi!\n\n"
        f"Buyurtma raqami: #{order_id}\n"
        f"📍 {pickup} → {delivery}\n"
        f"💰 Narx: {amount:,} so'm\n\n"
        f"⏳ Haydovchi qabul qilishini kuting...",
        reply_markup=get_main_keyboard('customer')
    )
    return States.MAIN

async def accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    driver_id = query.from_user.id
    order_id = int(query.data.split('_')[1])
    
    db.update_order_status(order_id, 'accepted', driver_id)
    
    # Buyurtma ma'lumotlarini olish
    cursor = db.conn.cursor()
    cursor.execute("SELECT customer_id, pickup_address, delivery_address, customer_phone FROM orders WHERE order_id = ?", (order_id,))
    order = cursor.fetchone()
    
    await query.edit_message_text(
        f"✅ Siz #{order_id} - buyurtmani qabul qildingiz!\n\n"
        f"📍 Olib ketish: {order[1]}\n"
        f"📍 Yetkazish: {order[2]}\n"
        f"📞 Mijoz: {order[3]}\n\n"
        f"Buyurtmani bajarib, /complete_{order_id} buyrug'ini yuboring."
    )
    
    # Mijozga xabar
    await context.bot.send_message(
        order[0],
        f"✅ Haydovchi buyurtmangizni qabul qildi!\n\n"
        f"Buyurtma #{order_id}\n"
        f"🚗 Haydovchi siz bilan bog'lanadi.\n"
        f"📞 Haydovchi raqami: {query.from_user.username or 'admin'}"
    )

async def my_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if user[3] == 'driver':
        orders = db.get_driver_orders(user_id)
        text = "🚗 **Sizning buyurtmalaringiz:**\n\n"
        for order in orders:
            status_emoji = {"pending": "⏳", "accepted": "✅", "completed": "✔️", "cancelled": "❌"}
            emoji = status_emoji.get(order[3], "❓")
            text += f"{emoji} #{order[0]} | {order[3]}\n📍 {order[1][:30]} → {order[2][:30]}\n💰 {order[4]} so'm\n\n"
    else:
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT order_id, pickup_address, delivery_address, status, amount 
            FROM orders WHERE customer_id = ? ORDER BY created_at DESC
        """, (user_id,))
        orders = cursor.fetchall()
        
        text = "📋 **Sizning buyurtmalaringiz:**\n\n"
        for order in orders:
            status_emoji = {"pending": "⏳", "accepted": "✅", "completed": "✔️", "cancelled": "❌"}
            emoji = status_emoji.get(order[3], "❓")
            text += f"{emoji} #{order[0]} | {order[3]}\n📍 {order[1][:30]} → {order[2][:30]}\n💰 {order[4]} so'm\n\n"
    
    if not orders:
        text = "📭 Sizda hali buyurtma yo'q."
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def my_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    balance = user[4] if user else 0
    
    await update.message.reply_text(
        f"💰 **Sizning balansingiz:**\n\n"
        f"{balance:,} so'm\n\n"
        f"💡 Balansingizni to'ldirish uchun administrator bilan bog'laning.",
        parse_mode=ParseMode.MARKDOWN
    )

async def driver_availability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    cursor = db.conn.cursor()
    cursor.execute("SELECT is_available FROM drivers WHERE user_id = ?", (user_id,))
    result = cursor.fetchone()
    
    if result:
        current_status = result[0]
        new_status = 0 if current_status else 1
        
        cursor.execute("UPDATE drivers SET is_available = ? WHERE user_id = ?", (new_status, user_id))
        db.conn.commit()
        
        status_text = "🟢 faol" if new_status else "🔴 faol emas"
        await update.message.reply_text(f"✅ Holatingiz {status_text} ga o'zgartirildi.")
    else:
        await update.message.reply_text("❌ Siz haydovchi sifatida ro'yxatdan o'tmagansiz!")

async def pending_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = db.get_user(update.effective_user.id)
    if not user or user[3] != 'driver':
        await update.message.reply_text("❌ Bu funksiya faqat haydovchilar uchun!")
        return
    
    orders = db.get_pending_orders()
    
    if not orders:
        await update.message.reply_text("📭 Hozircha mavjud buyurtmalar yo'q.")
        return
    
    text = "🚗 **Mavjud buyurtmalar:**\n\n"
    for order in orders:
        text += f"#{order[0]}\n📍 {order[1]} → {order[2]}\n💰 {order[3]} so'm\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
ℹ️ **Yordam**

**Mijozlar uchun:**
🚕 /order - Buyurtma berish
📋 /myorders - Buyurtmalar tarixi
💰 /balance - Balansni ko'rish

**Haydovchilar uchun:**
🚗 /available - Mavjudlik holati
📋 /myorders - Mening buyurtmalarim
📦 /orders - Mavjud buyurtmalar

**Umumiy:**
👤 /driver - Haydovchi sifatida ro'yxatdan o'tish
ℹ️ /help - Yordam

📞 **Aloqa:** @support
    """
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

# ==================== ASOSIY FUNKSIYA ====================
def main():
    # Logging sozlamalari
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # Botni ishga tushirish
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            States.WAITING_PHONE: [MessageHandler(filters.CONTACT, handle_contact)],
            States.WAITING_CAR_MODEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_car_model)],
            States.WAITING_PLATE_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_plate_number)],
            States.WAITING_PICKUP: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pickup)],
            States.WAITING_DELIVERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery)],
            States.WAITING_ORDER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_order_phone)],
            States.MAIN: [
                CommandHandler('driver', register_driver),
                CommandHandler('order', create_order),
                CommandHandler('myorders', my_orders),
                CommandHandler('balance', my_balance),
                CommandHandler('orders', pending_orders),
                CommandHandler('available', driver_availability),
                CommandHandler('help', help_command),
                CommandHandler('admin', admin_panel),
                MessageHandler(filters.Regex('^🚕 Buyurtma berish$'), create_order),
                MessageHandler(filters.Regex('^📋 Mening buyurtmalarim$'), my_orders),
                MessageHandler(filters.Regex('^💰 Mening balansim$'), my_balance),
                MessageHandler(filters.Regex('^🚗 Mavjudlik holati$'), driver_availability),
                MessageHandler(filters.Regex('^📦 Mavjud buyurtmalar$'), pending_orders),
                MessageHandler(filters.Regex('^⭐ Reytingim$'), lambda u, c: u.message.reply_text("⭐ Reytingingiz: 5.0")),
                MessageHandler(filters.Regex('^ℹ️ Yordam$'), help_command),
            ]
        },
        fallbacks=[CommandHandler('start', start)]
    )
    
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(accept_order, pattern='^accept_'))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))
    
    # Webhook (Railway uchun)
    import os
    PORT = int(os.environ.get('PORT', 8443))
    
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=TOKEN,
        webhook_url=f"https://{os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost')}/{TOKEN}"
    )

if __name__ == '__main__':
    main()
