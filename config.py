import os

# Bot tokenini @BotFather dan oling
BOT_TOKEN = os.getenv('BOT_TOKEN', '8753597096:AAFNeqOiDKYzatgrcuiQn22c0tNAhc5jTs0')

# Adminlar Telegram ID lari ro'yxati
ADMIN_IDS = [6713905538]  # O'zingizning ID laringizni qo'ying

# Ma'lumotlar bazasi (PostgreSQL yoki SQLite)
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./delivery_bot.db')

# Narxlar (1 kg uchun)
PRICE_PER_KG = 5000

# Bot sozlamalari
MAX_ORDER_WEIGHT = 100  # kg
MIN_ORDER_WEIGHT = 0.1  # kg
