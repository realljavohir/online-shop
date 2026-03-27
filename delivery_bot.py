# delivery_bot.py
import os
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode

# ==================== KONFIGURATSIYA ====================
TOKEN = os.environ.get("BOT_TOKEN", "8753597096:aafneqoidkyzatgrcuiqn22c0tnahc5jts0")
ADMIN_IDS = [int(id) for id in os.environ.get("ADMIN_IDS", "6713905538").split(",") if id]

if not TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")
if not ADMIN_IDS:
    logging.warning("ADMIN_IDS not set in environment variables!")

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
        
        # Admin balans
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_balance (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance INTEGER DEFAULT 0,
                updated_at TIMESTAMP
            )
        ''')
        
        # Sozlamalar
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            )
        ''')
        
        # Default sozlamalar
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES ('commission_amount', '500', ?)
        ''', (datetime.now(),))
        
        cursor.execute('''
            INSERT OR IGNORE INTO admin_balance (id, balance, updated_at)
            VALUES (1, 0, ?)
        ''', (datetime.now(),))
        
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
    
    def update_user_balance(self, user_id: int, amount: int):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE users SET balance = balance + ? WHERE user_id = ?
        ''', (amount, user_id))
        self.conn.commit()
    
    def get_user_balance(self, user_id: int) -> int:
        cursor = self.conn.cursor()
        cursor.execute('SELECT balance FROM users WHERE user_id = ?', (user_id,))
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def add_driver(self, user_id: int, car_model: str, plate_number: str):
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO drivers (user_id, car_model, plate_number)
            VALUES (?, ?, ?)
        ''', (user_id, car_model, plate_number))
        self.conn.commit()
    
    def get_driver(self, user_id: int) -> Optional[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM drivers WHERE user_id = ?', (user_id,))
        return cursor.fetchone()
    
    def update_driver_availability(self, user_id: int, is_available: bool):
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE drivers SET is_available = ? WHERE user_id = ?
        ''', (1 if is_available else 0, user_id))
        self.conn.commit()
    
    def add_order(self, customer_id: int, pickup: str, delivery: str, phone: str, amount: int) -> int:
        commission = self.get_commission()
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT INTO orders (customer_id, pickup_address, delivery_address, customer_phone, 
                               status, amount, commission, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (customer_id, pickup, delivery, phone, 'pending', amount, commission, datetime.now()))
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
            
            # Buyurtma ma'lumotlarini olish
            cursor.execute('SELECT amount, commission, driver_id FROM orders WHERE order_id = ?', (order_id,))
            amount, commission, driver_id = cursor.fetchone()
            
            # Haydovchiga to'lov (amount - commission)
            driver_payment = amount - commission
            cursor.execute('''
                UPDATE users SET balance = balance + ? WHERE user_id = ?
            ''', (driver_payment, driver_id))
            
            # Admin balansiga komissiya qo'shish
            cursor.execute('''
                UPDATE admin_balance 
                SET balance = balance + ?, updated_at = ?
                WHERE id = 1
            ''', (commission, datetime.now()))
            
            # Haydovchining total_orders ni oshirish
            cursor.execute('''
                UPDATE drivers 
                SET total_orders = total_orders + 1 
                WHERE user_id = ?
            ''', (driver_id,))
        
        self.conn.commit()
    
    def get_pending_orders(self) -> List[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT order_id, pickup_address, delivery_address, amount, customer_phone
            FROM orders WHERE status = 'pending'
        ''')
        return cursor.fetchall()
    
    def get_driver_orders(self, driver_id: int) -> List[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT order_id, pickup_address, delivery_address, status, amount, created_at
            FROM orders WHERE driver_id = ? ORDER BY created_at DESC
        ''', (driver_id,))
        return cursor.fetchall()
    
    def get_customer_orders(self, customer_id: int) -> List[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT order_id, pickup_address, delivery_address, status, amount, created_at
            FROM orders WHERE customer_id = ? ORDER BY created_at DESC
        ''', (customer_id,))
        return cursor.fetchall()
    
    def get_order(self, order_id: int) -> Optional[Tuple]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM orders WHERE order_id = ?', (order_id,))
        return cursor.fetchone()
    
    def get_commission(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'commission_amount'")
        result = cursor.fetchone()
        return int(result[0]) if result else 500
    
    def set_commission(self, amount: int) -> bool:
        if amount < 500 or amount > 1000:
            return False
        cursor = self.conn.cursor()
        cursor.execute('''
            UPDATE settings SET value = ?, updated_at = ? WHERE key = 'commission_amount'
        ''', (str(amount), datetime.now()))
        self.conn.commit()
        return True
    
    def get_admin_balance(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT balance FROM admin_balance WHERE id = 1")
        result = cursor.fetchone()
        return result[0] if result else 0
    
    def update_driver_rating(self, driver_id: int, rating: int):
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT rating, total_orders FROM drivers WHERE user_id = ?
        ''', (driver_id,))
        result = cursor.fetchone()
        
        if result:
            current_rating, total_orders = result
            new_rating = (current_rating * total_orders + rating) / (total_orders + 1)
            cursor.execute('''
                UPDATE drivers SET rating = ? WHERE user_id = ?
            ''', (new_rating, driver_id))
            self.conn.commit()
    
    def get_statistics(self) -> Dict:
        cursor = self.conn.cursor()
        
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
        
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'accepted'")
        accepted_orders = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM orders WHERE status = 'completed'")
        completed_orders = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(amount) FROM orders WHERE status = 'completed'")
        total_income = cursor.fetchone()[0] or 0
        
        return {
            'total_users': total_users,
            'total_drivers': total_drivers,
            'total_orders': total_orders,
            'pending_orders': pending_orders,
            'accepted_orders': accepted_orders,
            'completed_orders': completed_orders,
            'total_commission': total_commission,
            'total_income': total_income
        }

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
    WAITING_RATING = 7

# ==================== KLAVIATURALAR ====================
def get_main_keyboard(user_type: str = 'customer'):
    if user_type == 'driver':
        keyboard = [
            [KeyboardButton("🚗 Mavjudlik holati"), KeyboardButton("📋 Mening buyurtmalarim")],
            [KeyboardButton("💰 Mening balansim"), KeyboardButton("⭐ Reytingim")],
            [KeyboardButton("📦 Mavjud buyurtmalar"), KeyboardButton("ℹ️ Yordam")]
        ]
    else:
        keyboard = [
            [KeyboardButton("🚕 Buyurtma berish")],
            [KeyboardButton("📋 Mening buyurtmalarim"), KeyboardButton("💰 Mening balansim")],
            [KeyboardButton("ℹ️ Yordam")]
        ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_button():
    keyboard = [[KeyboardButton("🔙 Orqaga")]]
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
        [InlineKeyboardButton("💰 Admin balans", callback_data="admin_balance")],
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
        stats = db.get_statistics()
        
        text = f"""
📊 **Statistika**

👥 Foydalanuvchilar: {stats['total_users']}
🚗 Haydovchilar: {stats['total_drivers']}
📦 Jami buyurtmalar: {stats['total_orders']}
⏳ Kutilayotgan: {stats['pending_orders']}
✅ Qabul qilingan: {stats['accepted_orders']}
✔️ Bajarilgan: {stats['completed_orders']}
💰 Umumiy daromad: {stats['total_income']:,} so'm
💰 Umumiy komissiya: {stats['total_commission']:,} so'm
        """
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_users":
        cursor = db.conn.cursor()
        cursor.execute("SELECT user_id, full_name, phone, user_type, balance, created_at FROM users ORDER BY created_at DESC LIMIT 20")
        users = cursor.fetchall()
        
        if not users:
            await query.edit_message_text("📭 Foydalanuvchilar topilmadi.")
            return
        
        text = "👥 **Foydalanuvchilar ro'yxati:**\n\n"
        for user in users:
            text += f"🆔 ID: `{user[0]}`\n👤 {user[1]}\n📞 {user[2] or '❌'}\n📌 {user[3]}\n💰 {user[4]:,} so'm\n📅 {user[5][:16]}\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_orders":
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT order_id, pickup_address, delivery_address, status, amount, created_at 
            FROM orders ORDER BY created_at DESC LIMIT 20
        """)
        orders = cursor.fetchall()
        
        if not orders:
            await query.edit_message_text("📭 Buyurtmalar topilmadi.")
            return
        
        status_emoji = {"pending": "⏳", "accepted": "✅", "completed": "✔️", "cancelled": "❌"}
        
        text = "📦 **Buyurtmalar:**\n\n"
        for order in orders:
            emoji = status_emoji.get(order[3], "❓")
            text += f"{emoji} #{order[0]} | {order[3]}\n📍 {order[1][:30]} → {order[2][:30]}\n💰 {order[4]:,} so'm\n📅 {order[5][:16]}\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_drivers":
        cursor = db.conn.cursor()
        cursor.execute("""
            SELECT d.user_id, u.full_name, u.phone, d.car_model, d.plate_number, 
                   d.is_available, d.rating, d.total_orders, u.balance
            FROM drivers d
            JOIN users u ON d.user_id = u.user_id
            ORDER BY d.rating DESC
            LIMIT 20
        """)
        drivers = cursor.fetchall()
        
        if not drivers:
            await query.edit_message_text("🚗 Haydovchilar topilmadi.")
            return
        
        text = "🚗 **Haydovchilar ro'yxati:**\n\n"
        for driver in drivers:
            status = "🟢 Faol" if driver[5] else "🔴 Faol emas"
            text += f"🆔 ID: `{driver[0]}`\n👤 {driver[1]}\n📞 {driver[2] or '❌'}\n🚘 {driver[3]} | {driver[4]}\n⭐ {driver[6]:.1f} | 📦 {driver[7]}\n💰 {driver[8]:,} so'm\n📌 {status}\n\n"
        
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif data == "admin_balance":
        balance = db.get_admin_balance()
        await query.edit_message_text(
            f"💰 **Admin balansi:**\n\n{balance:,} so'm",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "admin_commission":
        current_commission = db.get_commission()
        
        keyboard = [
            [InlineKeyboardButton("500 so'm", callback_data="set_comm_500")],
            [InlineKeyboardButton("600 so'm", callback_data="set_comm_600")],
            [InlineKeyboardButton("700 so'm", callback_data="set_comm_700")],
            [InlineKeyboardButton("800 so'm", callback_data="set_comm_800")],
            [InlineKeyboardButton("900 so'm", callback_data="set_comm_900")],
            [InlineKeyboardButton("1000 so'm", callback_data="set_comm_1000")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="admin_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            f"⚙️ **Komissiya sozlamalari**\n\nJoriy komissiya: {current_commission} so'm\n\nYangi komissiyani tanlang (500-1000 so'm oralig'ida):",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
    
    elif data.startswith("set_comm_"):
        amount = int(data.split("_")[2])
        if db.set_commission(amount):
            await query.edit_message_text(f"✅ Komissiya {amount} so'mga o'zgartirildi!")
        else:
            await query.edit_message_text("❌ Komissiya 500-1000 so'm oralig'ida bo'lishi kerak!")
    
    elif data == "admin_back":
        keyboard = [
            [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="admin_users")],
            [InlineKeyboardButton("🚗 Haydovchilar", callback_data="admin_drivers")],
            [InlineKeyboardButton("📦 Buyurtmalar", callback_data="admin_orders")],
            [InlineKeyboardButton("💰 Admin balans", callback_data="admin_balance")],
            [InlineKeyboardButton("⚙️ Komissiya sozlamalari", callback_data="admin_commission")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("👨‍💼 Admin panel", reply_markup=reply_markup)

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
                resize_keyboard=True,
                one_time_keyboard=True
            )
        )
        return States.WAITING_PHONE.value
    
    user_type = user[3]
    await update.message.reply_text(
        f"👋 Xush kelibsiz, {full_name}!\n\n"
        f"Sizning ro'lingiz: {'🚗 Haydovchi' if user_type == 'driver' else '👤 Mijoz'}",
        reply_markup=get_main_keyboard(user_type)
    )
    return States.MAIN.value

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
    return States.MAIN.value

async def register_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Foydalanuvchi mavjudligini tekshirish
    user = db.get_user(user_id)
    if not user:
        await update.message.reply_text(
            "❌ Avval /start buyrug'i bilan ro'yxatdan o'ting!"
        )
        return States.MAIN.value
    
    # Haydovchi allaqachon ro'yxatdan o'tganmi?
    driver = db.get_driver(user_id)
    if driver:
        await update.message.reply_text(
            "✅ Siz allaqachon haydovchi sifatida ro'yxatdan o'tgansiz!",
            reply_markup=get_main_keyboard('driver')
        )
        return States.MAIN.value
    
    await update.message.reply_text(
        "🚗 Haydovchi sifatida ro'yxatdan o'tish\n\n"
        "Avtomobilingiz modelini kiriting:\n"
        "Masalan: Chevrolet Lacetti, 2018",
        reply_markup=get_back_button()
    )
    return States.WAITING_CAR_MODEL.value

async def get_car_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Orqaga":
        await update.message.reply_text(
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_keyboard('customer')
        )
        return States.MAIN.value
    
    context.user_data['car_model'] = update.message.text
    
    await update.message.reply_text(
        "🚘 Davlat raqamini kiriting:\n"
        "Masalan: 01 A 123 AA",
        reply_markup=get_back_button()
    )
    return States.WAITING_PLATE_NUMBER.value

async def get_plate_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Orqaga":
        await update.message.reply_text(
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_keyboard('customer')
        )
        return States.MAIN.value
    
    user_id = update.effective_user.id
    car_model = context.user_data.get('car_model')
    plate_number = update.message.text
    
    # Foydalanuvchini yangilash
    db.add_user(user_id, update.effective_user.full_name, '', 'driver')
    db.add_driver(user_id, car_model, plate_number)
    
    await update.message.reply_text(
        "✅ Haydovchi sifatida ro'yxatdan o'tdingiz!\n\n"
        "Endi siz buyurtmalarni qabul qilishingiz mumkin.\n"
        "Mavjud buyurtmalarni ko'rish uchun /orders buyrug'ini yuboring.",
        reply_markup=get_main_keyboard('driver')
    )
    return States.MAIN.value

async def create_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    
    if not user:
        await update.message.reply_text("❌ Iltimos, avval /start buyrug'ini bosing!")
        return States.MAIN.value
    
    if user[3] == 'driver':
        await update.message.reply_text("❌ Haydovchilar buyurtma bera olmaydi!")
        return States.MAIN.value
    
    await update.message.reply_text(
        "📍 **Yangi buyurtma**\n\n"
        "Qayerdan olish joyini kiriting:\n"
        "Masalan: Toshkent, Chilonzor, 5-mavze",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_back_button()
    )
    return States.WAITING_PICKUP.value

async def get_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Orqaga":
        await update.message.reply_text(
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_keyboard('customer')
        )
        return States.MAIN.value
    
    context.user_data['pickup'] = update.message.text
    
    await update.message.reply_text(
        "📍 Qayerga yetkazib berish joyini kiriting:",
        reply_markup=get_back_button()
    )
    return States.WAITING_DELIVERY.value

async def get_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Orqaga":
        await update.message.reply_text(
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_keyboard('customer')
        )
        return States.MAIN.value
    
    context.user_data['delivery'] = update.message.text
    
    await update.message.reply_text(
        "📞 Mijozning telefon raqamini kiriting:\n"
        "Masalan: +998901234567",
        reply_markup=get_back_button()
    )
    return States.WAITING_ORDER_PHONE.value

async def get_order_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Orqaga":
        await update.message.reply_text(
            "Bosh menyuga qaytdingiz.",
            reply_markup=get_main_keyboard('customer')
        )
        return States.MAIN.value
    
    user_id = update.effective_user.id
    pickup = context.user_data.get('pickup')
    delivery = context.user_data.get('delivery')
    phone = update.message.text
    
    # Buyurtma narxini hisoblash (oddiy hisob - masofa bo'yicha)
    amount = 15000
    
    order_id = db.add_order(user_id, pickup, delivery, phone, amount)
    
    # Haydovchilarga xabar yuborish
    cursor = db.conn.cursor()
    cursor.execute("SELECT user_id FROM drivers WHERE is_available = 1")
    drivers = cursor.fetchall()
    
    sent_count = 0
    for driver in drivers:
        try:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept_{order_id}")]
            ])
            await context.bot.send_message(
                driver[0],
                f"🚗 **Yangi buyurtma!**\n\n"
                f"🆔 #{order_id}\n"
                f"📍 Olib ketish: {pickup}\n"
                f"📍 Yetkazish: {delivery}\n"
                f"💰 Narx: {amount:,} so'm\n"
                f"📞 Mijoz: {phone}\n\n"
                f"💰 Komissiya: {db.get_commission():,} so'm\n"
                f"💰 Haydovchiga: {amount - db.get_commission():,} so'm",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
            sent_count += 1
        except Exception as e:
            logging.error(f"Xabar yuborilmadi {driver[0]}: {e}")
    
    await update.message.reply_text(
        f"✅ Buyurtma yaratildi!\n\n"
        f"🆔 Buyurtma raqami: #{order_id}\n"
        f"📍 {pickup} → {delivery}\n"
        f"💰 Narx: {amount:,} so'm\n\n"
        f"⏳ {sent_count} ta haydovchiga xabar yuborildi.\n"
        f"Haydovchi qabul qilishini kuting...",
        reply_markup=get_main_keyboard('customer')
    )
    return States.MAIN.value

async def accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    driver_id = query.from_user.id
    
    # Haydovchi ro'yxatdan o'tganmi?
    driver = db.get_driver(driver_id)
    if not driver:
        await query.edit_message_text("❌ Siz haydovchi sifatida ro'yxatdan o'tmagansiz!")
        return
    
    order_id = int(query.data.split('_')[1])
    
    # Order ni tekshirish
    order = db.get_order(order_id)
    if not order:
        await query.edit_message_text("❌ Buyurtma topilmadi!")
        return
    
    if order[6] != 'pending':  # status index
        await query.edit_message_text("❌ Bu buyurtma allaqachon boshqa haydovchi tomonidan qabul qilingan!")
        return
    
    db.update_order_status(order_id, 'accepted', driver_id)
    
    # Buyurtma ma'lumotlarini olish
    cursor = db.conn.cursor()
    cursor.execute("SELECT customer_id, pickup_address, delivery_address, customer_phone FROM orders WHERE order_id = ?", (order_id,))
    order_data = cursor.fetchone()
    
    await query.edit_message_text(
        f"✅ Siz #{order_id} - buyurtmani qabul qildingiz!\n\n"
        f"📍 Olib ketish: {order_data[1]}\n"
        f"📍 Yetkazish: {order_data[2]}\n"
        f"📞 Mijoz: {order_data[3]}\n\n"
        f"Buyurtmani bajarganingizdan so'ng /complete_{order_id} buyrug'ini yuboring."
    )
    
    # Mijozga xabar
    try:
        await context.bot.send_message(
            order_data[0],
            f"✅ Haydovchi buyurtmangizni qabul qildi!\n\n"
            f"🆔 Buyurtma #{order_id}\n"
            f"🚗 Haydovchi siz bilan bog'lanadi.\n\n"
            f"Buyurtma bajarilgandan so'ng reyting qoldirishingiz mumkin: /rate_{order_id}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logging.error(f"Xabar yuborilmadi: {e}")

async def complete_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buyurtmani bajarilgan deb belgilash"""
    user_id = update.effective_user.id
    
    # Command ni tekshirish
    if not update.message.text.startswith('/complete_'):
        await update.message.reply_text("❌ Noto'g'ri format! /complete_{order_id} ko'rinishida yuboring.")
        return
    
    try:
        order_id = int(update.message.text.split('_')[1])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Noto'g'ri format! /complete_{order_id} ko'rinishida yuboring.")
        return
    
    # Tekshirish
    order = db.get_order(order_id)
    if not order:
        await update.message.reply_text("❌ Buyurtma topilmadi!")
        return
    
    # order: (order_id, customer_id, driver_id, pickup_address, delivery_address, 
    #         customer_phone, status, amount, commission, created_at, completed_at)
    if order[2] != user_id:  # driver_id index
        await update.message.reply_text("❌ Bu sizning buyurtmangiz emas!")
        return
    
    if order[6] != 'accepted':  # status index
        await update.message.reply_text("❌ Buyurtma qabul qilingan holatda emas!")
        return
    
    db.update_order_status(order_id, 'completed')
    
    # Haydovchiga to'lov miqdorini hisoblash
    driver_payment = order[7] - order[8]  # amount - commission
    
    await update.message.reply_text(
        f"✅ #{order_id} - buyurtma muvaffaqiyatli bajarildi!\n"
        f"💰 {driver_payment:,} so'm balansingizga o'tkazildi.\n\n"
        f"Buyurtmachiga reyting qoldirishni unutmang."
    )
    
    # Mijozga xabar
    try:
        await context.bot.send_message(
            order[1],  # customer_id
            f"✅ #{order_id} - buyurtmangiz yetkazib berildi!\n"
            f"Xizmatdan foydalanganingiz uchun rahmat!\n\n"
            f"Haydovchiga reyting bering: /rate_{order_id}",
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        logging.error(f"Xabar yuborilmadi: {e}")

async def rate_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Haydovchiga reyting berish"""
    user_id = update.effective_user.id
    
    # Command ni tekshirish
    if not update.message.text.startswith('/rate_'):
        await update.message.reply_text("❌ Noto'g'ri format! /rate_{order_id} ko'rinishida yuboring.")
        return
    
    try:
        order_id = int(update.message.text.split('_')[1])
    except (IndexError, ValueError):
        await update.message.reply_text("❌ Noto'g'ri format! /rate_{order_id} ko'rinishida yuboring.")
        return
    
    # Tekshirish
    order = db.get_order(order_id)
    if not order:
        await update.message.reply_text("❌ Buyurtma topilmadi!")
        return
    
    if order[1] != user_id:  # customer_id index
        await update.message.reply_text("❌ Bu sizning buyurtmangiz emas!")
        return
    
    if order[6] != 'completed':  # status index
        await update.message.reply_text("❌ Faqat bajarilgan buyurtmalarga reyting berish mumkin!")
        return
    
    context.user_data['rate_order_id'] = order_id
    
    keyboard = [
        [InlineKeyboardButton("⭐ 1", callback_data="rate_1"),
         InlineKeyboardButton("⭐⭐ 2", callback_data="rate_2"),
         InlineKeyboardButton("⭐⭐⭐ 3", callback_data="rate_3")],
        [InlineKeyboardButton("⭐⭐⭐⭐ 4", callback_data="rate_4"),
         InlineKeyboardButton("⭐⭐⭐⭐⭐ 5", callback_data="rate_5")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "⭐ Haydovchiga reyting bering (1-5):",
        reply_markup=reply_markup
    )
    return States.WAITING_RATING.value

async def save_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reytingni saqlash"""
    query = update.callback_query
    await query.answer()
    
    rating = int(query.data.split('_')[1])
    order_id = context.user_data.get('rate_order_id')
    
    if not order_id:
        await query.edit_message_text("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")
        return ConversationHandler.END
    
    order = db.get_order(order_id)
    if order and order[2]:  # driver_id mavjud
        # Haydovchi reytingini yangilash
        db.update_driver_rating(order[2], rating)
        
        await query.edit_message_text(
            f"✅ Reyting qabul qilindi!\n"
            f"Haydovchiga {rating}⭐ berdingiz.\n\n"
            f"Xizmatdan foydalanganingiz uchun rahmat!"
        )
        
        # context.user_data dan tozalash
        context.user_data.pop('rate_order_id', None)
        return ConversationHandler.END
    else:
        await query.edit_message_text("❌ Xatolik: Buyurtma yoki haydovchi topilmadi.")
        return ConversationHandler.END

# ==================== MENU HANDLERLAR ====================
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    
    user = db.get_user(user_id)
    if not user:
        await start(update, context)
        return
    
    user_type = user[3]
    
    if text == "🚕 Buyurtma berish":
        return await create_order(update, context)
    
    elif text == "📋 Mening buyurtmalarim":
        if user_type == 'driver':
            orders = db.get_driver_orders(user_id)
        else:
            orders = db.get_customer_orders(user_id)
        
        if not orders:
            await update.message.reply_text("📭 Sizda hech qanday buyurtma yo'q.")
            return
        
        status_emoji = {"pending": "⏳", "accepted": "✅", "completed": "✔️", "cancelled": "❌"}
        
        text = "📋 **Buyurtmalaringiz:**\n\n"
        for order in orders:
            emoji = status_emoji.get(order[3], "❓")
            text += f"{emoji} #{order[0]} | {order[3]}\n📍 {order[1][:30]} → {order[2][:30]}\n💰 {order[4]:,} so'm\n📅 {order[5][:16]}\n\n"
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
    
    elif text == "💰 Mening balansim":
        balance = db.get_user_balance(user_id)
        await update.message.reply_text(
            f"💰 **Balansingiz:**\n\n{balance:,} so'm",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif text == "🚗 Mavjudlik holati" and user_type == 'driver':
        driver = db.get_driver(user_id)
        if driver:
            is_available = driver[3]  # is_available index
            status = "🟢 Faol" if is_available else "🔴 Faol emas"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔴 Faol emas qilish" if is_available else "🟢 Faol qilish",
                    callback_data="toggle_availability"
                )]
            ])
            
            await update.message.reply_text(
                f"🚗 **Mavjudlik holati:**\n\n{status}\n\n"
                f"Faol bo'lganingizda yangi buyurtmalarni qabul qila olasiz.",
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text == "⭐ Reytingim" and user_type == 'driver':
        driver = db.get_driver(user_id)
        if driver:
            rating = driver[4]  # rating index
            total_orders = driver[5]  # total_orders index
            await update.message.reply_text(
                f"⭐ **Sizning reytingingiz:**\n\n"
                f"{rating:.1f} ⭐\n"
                f"📦 Bajarilgan buyurtmalar: {total_orders}",
                parse_mode=ParseMode.MARKDOWN
            )
    
    elif text == "📦 Mavjud buyurtmalar" and user_type == 'driver':
        orders = db.get_pending_orders()
        
        if not orders:
            await update.message.reply_text("📭 Hozircha mavjud buyurtmalar yo'q.")
            return
        
        text = "📦 **Mavjud buyurtmalar:**\n\n"
        for order in orders:
            text += f"🆔 #{order[0]}\n📍 {order[1]} → {order[2]}\n💰 {order[3]:,} so'm\n📞 {order[4]}\n\n"
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Yangilash", callback_data="refresh_orders")]
        ])
        
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
    
    elif text == "ℹ️ Yordam":
        help_text = """
ℹ️ **Yordam**

**Mijozlar uchun:**
🚕 /start - Boshlash
🚕 Buyurtma berish - Yangi buyurtma yaratish
📋 Mening buyurtmalarim - Buyurtmalar tarixi
💰 Mening balansim - Balansni ko'rish

**Haydovchilar uchun:**
🚗 /start - Boshlash
🚗 Mavjudlik holati - Faollikni o'zgartirish
📦 Mavjud buyurtmalar - Yangi buyurtmalarni ko'rish
📋 Mening buyurtmalarim - Qabul qilingan buyurtmalar
💰 Mening balansim - Balansni ko'rish
⭐ Reytingim - Reytingni ko'rish

**Buyruqlar:**
/driver - Haydovchi sifatida ro'yxatdan o'tish
/complete_{id} - Buyurtmani bajarish
/rate_{id} - Reyting berish
/admin - Admin panel (faqat adminlar uchun)

📞 **Aloqa:** @support
        """
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def toggle_availability(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    driver_id = query.from_user.id
    driver = db.get_driver(driver_id)
    
    if driver:
        new_status = not driver[3]  # is_available index
        db.update_driver_availability(driver_id, new_status)
        
        status_text = "🟢 Faol" if new_status else "🔴 Faol emas"
        await query.edit_message_text(
            f"✅ Mavjudlik holati o'zgartirildi!\n\n"
            f"Hozirgi holat: {status_text}"
        )
    else:
        await query.edit_message_text("❌ Xatolik yuz berdi!")

async def refresh_orders(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    orders = db.get_pending_orders()
    
    if not orders:
        await query.edit_message_text("📭 Hozircha mavjud buyurtmalar yo'q.")
        return
    
    text = "📦 **Mavjud buyurtmalar:**\n\n"
    for order in orders:
        text += f"🆔 #{order[0]}\n📍 {order[1]} → {order[2]}\n💰 {order[3]:,} so'm\n📞 {order[4]}\n\n"
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Yangilash", callback_data="refresh_orders")]
    ])
    
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=get_main_keyboard('customer')
    )
    return ConversationHandler.END

# ==================== MAIN ====================
def main():
    # Logging sozlamalari
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handler - ro'yxatdan o'tish
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            States.WAITING_PHONE.value: [MessageHandler(filters.CONTACT, handle_contact)],
            States.WAITING_CAR_MODEL.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_car_model)],
            States.WAITING_PLATE_NUMBER.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_plate_number)],
            States.WAITING_PICKUP.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_pickup)],
            States.WAITING_DELIVERY.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_delivery)],
            States.WAITING_ORDER_PHONE.value: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_order_phone)],
            States.WAITING_RATING.value: [CallbackQueryHandler(save_rating, pattern='^rate_')],
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex('^🔙 Orqaga$'), cancel)],
    )
    
    # Handlers
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('driver', register_driver))
    app.add_handler(CommandHandler('admin', admin_panel))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern='^admin_'))
    app.add_handler(CallbackQueryHandler(accept_order, pattern='^accept_'))
    app.add_handler(CallbackQueryHandler(toggle_availability, pattern='^toggle_availability$'))
    app.add_handler(CallbackQueryHandler(refresh_orders, pattern='^refresh_orders$'))
    app.add_handler(MessageHandler(filters.Regex('^(🚕 Buyurtma berish|📋 Mening buyurtmalarim|💰 Mening balansim|🚗 Mavjudlik holati|⭐ Reytingim|📦 Mavjud buyurtmalar|ℹ️ Yordam)$'), handle_menu))
    app.add_handler(MessageHandler(filters.Regex('^/complete_'), complete_order))
    app.add_handler(MessageHandler(filters.Regex('^/rate_'), rate_driver))
    
    # Botni ishga tushirish
    print("Bot ishga tushdi...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
