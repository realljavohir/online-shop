from bot import DeliveryBot
from database import init_db

if __name__ == '__main__':
    print("🚀 Bot ishga tushmoqda...")
    init_db()
    bot = DeliveryBot()
    print("✅ Bot muvaffaqiyatli ishga tushdi!")
    bot.run()
