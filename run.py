# run.py
import logging
import os
import asyncio
from bot import DeliveryBot
from database import init_db

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    try:
        print("🚀 Bot ishga tushmoqda...")
        print(f"📁 Mavjud fayllar: {os.listdir('.')}")
        
        # Bazani yaratish
        init_db()
        print("✅ Ma'lumotlar bazasi tayyor")
        
        # Botni ishga tushirish
        bot = DeliveryBot()
        print("✅ Bot muvaffaqiyatli ishga tushdi!")
        
        # Railway uchun portni ochib turish (web service uchun)
        port = int(os.environ.get('PORT', 8080))
        print(f"🌐 Server {port}-portda ishga tushdi")
        
        # Botni ishlatish
        await bot.application.initialize()
        await bot.application.start()
        await bot.application.updater.start_polling()
        
        # Keep alive
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"Bot ishga tushmadi: {e}")
        print(f"❌ Xatolik: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(main())
