import logging
import os
import asyncio
import sys

# Import qilish - avval delivery_bot, keyin bot
try:
    from delivery_bot import DeliveryBot
    print("✅ delivery_bot import qilindi")
except ImportError:
    try:
        from bot import DeliveryBot
        print("✅ bot import qilindi")
    except ImportError as e:
        print(f"❌ Xatolik: Hech qanday bot moduli topilmadi!")
        print(f"📁 Mavjud fayllar: {os.listdir('.')}")
        sys.exit(1)

from database import init_db
from config import BOT_TOKEN, ADMIN_IDS

# Logging sozlamalari
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    """Asosiy funksiya"""
    try:
        print("=" * 50)
        print("🚀 DELIVERY BOT ISHGA TUSHMOQDA")
        print("=" * 50)
        
        # Mavjud fayllarni ko'rsatish
        print(f"\n📁 Mavjud fayllar:")
        for file in os.listdir('.'):
            if file.endswith('.py'):
                print(f"   - {file}")
        
        print(f"\n📂 Joriy papka: {os.getcwd()}")
        
        # Bazani yaratish
        print("\n📊 Ma'lumotlar bazasi yaratilmoqda...")
        init_db()
        print("✅ Ma'lumotlar bazasi tayyor")
        
        # Bot tokenini tekshirish
        print("\n🔑 Bot token tekshirilmoqda...")
        if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ Xatolik: BOT_TOKEN sozlanmagan!")
            print("Railwayda environment variable 'BOT_TOKEN' ni sozlang")
            sys.exit(1)
        
        print(f"✅ Bot token: {BOT_TOKEN[:10]}... (uzunligi: {len(BOT_TOKEN)})")
        
        # Adminlarni tekshirish
        print(f"👥 Adminlar: {ADMIN_IDS}")
        
        # Botni ishga tushirish
        print("\n🤖 Bot ishga tushirilmoqda...")
        bot = DeliveryBot()
        
        # Botni ishga tushirish
        await bot.application.initialize()
        await bot.application.start()
        await bot.application.updater.start_polling()
        
        print("\n" + "=" * 50)
        print("✅ BOT MUVAFFAQIYATLI ISHGA TUSHDI!")
        print("=" * 50)
        print("\n🤖 Bot Telegramda ishlayapti...")
        print("📊 Loglar kuzatilmoqda...\n")
        
        # Botni ishlatish
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.error(f"Bot ishga tushmadi: {e}")
        print(f"\n❌ Xatolik: {e}")
        print("\n📋 Xatolik tafsilotlari:")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n👋 Bot to'xtatildi!")
        sys.exit(0)
