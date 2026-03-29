import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from database import SessionLocal, Order, User, init_db
from config import BOT_TOKEN, ADMIN_IDS

# Logging sozlamalari
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

class DeliveryBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
        
    def setup_handlers(self):
        """Bot handlerlarini sozlash"""
        # Komandalar
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("admin", self.admin_panel))
        
        # Callback query handler
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        
        # Xabarlar
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message))
        
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start komandasi"""
        user = update.effective_user
        user_id = user.id
        username = user.username
        
        # Foydalanuvchini bazaga saqlash
        db = SessionLocal()
        existing_user = db.query(User).filter(User.telegram_id == user_id).first()
        
        if not existing_user:
            new_user = User(
                telegram_id=user_id,
                username=username,
                full_name=user.full_name,
                role='customer'  # standart mijoz
            )
            db.add(new_user)
            db.commit()
        
        db.close()
        
        # Tugmalar
        keyboard = [
            [InlineKeyboardButton("🚖 Buyurtma berish", callback_data="new_order")],
            [InlineKeyboardButton("📋 Mening buyurtmalarim", callback_data="my_orders")],
            [InlineKeyboardButton("ℹ️ Yordam", callback_data="help")]
        ]
        
        # Agar admin bo'lsa, admin tugmasi qo'shiladi
        if user_id in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("⚙️ Admin panel", callback_data="admin_panel")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 Assalomu alaykum, {user.full_name}!\n\n"
            f"🚖 Yuk tashish xizmatiga xush kelibsiz!\n\n"
            f"Quyidagi tugmalar orqali buyurtma berishingiz mumkin:",
            reply_markup=reply_markup
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Callback querylarni qayta ishlash"""
        query = update.callback_query
        await query.answer()
        
        data = query.data
        user_id = query.from_user.id
        
        if data == "new_order":
            await self.create_order(update, context)
        elif data == "my_orders":
            await self.show_my_orders(update, context)
        elif data == "help":
            await self.show_help(update, context)
        elif data == "admin_panel":
            await self.admin_panel(update, context)
        elif data.startswith("order_"):
            await self.show_order_details(update, context, data)
        elif data.startswith("accept_order_"):
            await self.accept_order(update, context, data)
        elif data.startswith("complete_order_"):
            await self.complete_order(update, context, data)
        elif data.startswith("cancel_order_"):
            await self.cancel_order(update, context, data)
    
    async def create_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yangi buyurtma yaratish"""
        context.user_data['creating_order'] = True
        await update.callback_query.message.reply_text(
            "📍 Iltimos, jo'natish manzilini kiriting:"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Foydalanuvchi xabarlarini qayta ishlash"""
        user_id = update.effective_user.id
        
        if context.user_data.get('creating_order'):
            # Buyurtma yaratish jarayoni
            if 'address_from' not in context.user_data:
                context.user_data['address_from'] = update.message.text
                await update.message.reply_text("📍 Qabul qilish manzilini kiriting:")
            elif 'address_to' not in context.user_data:
                context.user_data['address_to'] = update.message.text
                await update.message.reply_text("📦 Yukning og'irligini kiriting (kg):")
            elif 'weight' not in context.user_data:
                try:
                    weight = float(update.message.text)
                    context.user_data['weight'] = weight
                    
                    # Narxni hisoblash (misol uchun)
                    price = weight * 5000  # 1kg = 5000 so'm
                    context.user_data['price'] = price
                    
                    # Buyurtmani saqlash
                    db = SessionLocal()
                    order = Order(
                        user_id=user_id,
                        address_from=context.user_data['address_from'],
                        address_to=context.user_data['address_to'],
                        weight=weight,
                        price=price,
                        status='pending'
                    )
                    db.add(order)
                    db.commit()
                    db.refresh(order)
                    db.close()
                    
                    # Tasdiqlash xabari
                    await update.message.reply_text(
                        f"✅ Buyurtma qabul qilindi!\n\n"
                        f"📋 Buyurtma ID: {order.id}\n"
                        f"📍 Jo'natish: {order.address_from}\n"
                        f"📍 Qabul qilish: {order.address_to}\n"
                        f"⚖️ Og'irligi: {order.weight} kg\n"
                        f"💰 Narxi: {order.price} so'm\n\n"
                        f"Tez orada haydovchi buyurtmani qabul qiladi!"
                    )
                    
                    # Adminlarga xabar yuborish
                    await self.notify_admins(order)
                    
                    # Tozalash
                    context.user_data.clear()
                    
                except ValueError:
                    await update.message.reply_text("❌ Iltimos, to'g'ri og'irlik kiriting (masalan: 5.5):")
    
    async def show_my_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Foydalanuvchining buyurtmalarini ko'rsatish"""
        user_id = update.callback_query.from_user.id
        db = SessionLocal()
        orders = db.query(Order).filter(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(10).all()
        db.close()
        
        if not orders:
            await update.callback_query.message.reply_text("📭 Sizda hech qanday buyurtma yo'q.")
            return
        
        text = "📋 Sizning buyurtmalaringiz:\n\n"
        for order in orders:
            status_text = {
                'pending': '⏳ Kutilmoqda',
                'accepted': '✅ Qabul qilingan',
                'in_progress': '🚚 Yetkazilmoqda',
                'completed': '✅ Yakunlangan',
                'cancelled': '❌ Bekor qilingan'
            }.get(order.status, order.status)
            
            text += f"#{order.id} - {status_text}\n"
            text += f"📍 {order.address_from} → {order.address_to}\n"
            text += f"💰 {order.price} so'm\n\n"
        
        await update.callback_query.message.reply_text(text)
    
    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Yordam xabarini ko'rsatish"""
        await update.callback_query.message.reply_text(
            "📚 Yordam:\n\n"
            "🚖 Buyurtma berish - 'Buyurtma berish' tugmasini bosing\n"
            "📋 Mening buyurtmalarim - buyurtmalaringizni ko'rish\n"
            "💰 Narxlar - 1 kg uchun 5000 so'm\n\n"
            "📞 Savol va takliflar uchun: @reall_javohir"
        )
    
    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Admin panelini ko'rsatish"""
        user_id = update.effective_user.id
        
        if user_id not in ADMIN_IDS:
            if update.message:
                await update.message.reply_text("❌ Sizda admin huquqlari yo'q!")
            else:
                await update.callback_query.message.reply_text("❌ Sizda admin huquqlari yo'q!")
            return
        
        keyboard = [
            [InlineKeyboardButton("📋 Barcha buyurtmalar", callback_data="all_orders")],
            [InlineKeyboardButton("⏳ Kutilayotgan buyurtmalar", callback_data="pending_orders")],
            [InlineKeyboardButton("🚚 Haydovchilar", callback_data="drivers_list")],
            [InlineKeyboardButton("📊 Statistika", callback_data="statistics")],
            [InlineKeyboardButton("➕ Haydovchi qo'shish", callback_data="add_driver")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        if update.callback_query:
            await update.callback_query.message.reply_text(
                "⚙️ Admin panel\n\nQuyidagi tugmalardan birini tanlang:",
                reply_markup=reply_markup
            )
        else:
            await update.message.reply_text(
                "⚙️ Admin panel\n\nQuyidagi tugmalardan birini tanlang:",
                reply_markup=reply_markup
            )
    
    async def accept_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data):
        """Haydovchi buyurtmani qabul qilishi"""
        order_id = int(data.split('_')[2])
        driver_id = update.callback_query.from_user.id
        
        db = SessionLocal()
        order = db.query(Order).filter(Order.id == order_id).first()
        
        if order and order.status == 'pending':
            order.status = 'accepted'
            order.driver_id = driver_id
            db.commit()
            
            # Mijozga xabar
            await self.application.bot.send_message(
                chat_id=order.user_id,
                text=f"✅ Buyurtma #{order_id} haydovchi tomonidan qabul qilindi!\n\nTez orada siz bilan bog'lanadi."
            )
            
            await update.callback_query.message.reply_text(f"✅ Buyurtma #{order_id} qabul qilindi!")
        else:
            await update.callback_query.message.reply_text(f"❌ Buyurtma #{order_id} allaqachon qabul qilingan yoki bekor qilingan!")
        
        db.close()
    
    async def complete_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data):
        """Buyurtmani yakunlash"""
        order_id = int(data.split('_')[2])
        
        db = SessionLocal()
        order = db.query(Order).filter(Order.id == order_id).first()
        
        if order and order.status == 'accepted':
            order.status = 'completed'
            order.completed_at = datetime.now()
            db.commit()
            
            # Mijozga xabar
            await self.application.bot.send_message(
                chat_id=order.user_id,
                text=f"✅ Buyurtma #{order_id} muvaffaqiyatli yakunlandi!\n\nXizmatimizdan foydalanganingiz uchun rahmat!"
            )
            
            await update.callback_query.message.reply_text(f"✅ Buyurtma #{order_id} yakunlandi!")
        else:
            await update.callback_query.message.reply_text(f"❌ Buyurtma #{order_id} yakunlanmadi!")
        
        db.close()
    
    async def cancel_order(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data):
        """Buyurtmani bekor qilish"""
        order_id = int(data.split('_')[2])
        
        db = SessionLocal()
        order = db.query(Order).filter(Order.id == order_id).first()
        
        if order and order.status == 'pending':
            order.status = 'cancelled'
            db.commit()
            
            # Mijozga xabar
            await self.application.bot.send_message(
                chat_id=order.user_id,
                text=f"❌ Buyurtma #{order_id} bekor qilindi!"
            )
            
            await update.callback_query.message.reply_text(f"❌ Buyurtma #{order_id} bekor qilindi!")
        else:
            await update.callback_query.message.reply_text(f"❌ Buyurtma #{order_id} bekor qilinmadi!")
        
        db.close()
    
    async def show_order_details(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data):
        """Buyurtma detallarini ko'rsatish"""
        order_id = int(data.split('_')[1])
        
        db = SessionLocal()
        order = db.query(Order).filter(Order.id == order_id).first()
        db.close()
        
        if order:
            status_text = {
                'pending': '⏳ Kutilmoqda',
                'accepted': '✅ Qabul qilingan',
                'in_progress': '🚚 Yetkazilmoqda',
                'completed': '✅ Yakunlangan',
                'cancelled': '❌ Bekor qilingan'
            }.get(order.status, order.status)
            
            # Username ni xavfsiz olish
            user_name = "Noma'lum"
            if order.user:
                if order.user.username:
                    user_name = order.user.username
                elif order.user.full_name:
                    user_name = order.user.full_name
            
            text = (
                f"📋 Buyurtma #{order.id}\n\n"
                f"👤 Mijoz: {user_name}\n"
                f"📍 Jo'natish: {order.address_from}\n"
                f"📍 Qabul: {order.address_to}\n"
                f"⚖️ Og'irligi: {order.weight} kg\n"
                f"💰 Narxi: {order.price} so'm\n"
                f"📊 Holati: {status_text}\n"
                f"📅 Yaratilgan: {order.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            )
            
            if order.completed_at:
                text += f"✅ Yakunlangan: {order.completed_at.strftime('%d.%m.%Y %H:%M')}\n"
            
            keyboard = []
            if order.status == 'pending':
                keyboard.append([InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept_order_{order.id}")])
                keyboard.append([InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_order_{order.id}")])
            elif order.status == 'accepted':
                keyboard.append([InlineKeyboardButton("✅ Yakunlash", callback_data=f"complete_order_{order.id}")])
            
            if keyboard:
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.callback_query.message.reply_text(text, reply_markup=reply_markup)
            else:
                await update.callback_query.message.reply_text(text)
        else:
            await update.callback_query.message.reply_text("❌ Buyurtma topilmadi!")
    
    async def notify_admins(self, order):
        """Adminlarga yangi buyurtma haqida xabar berish"""
        # Username ni xavfsiz olish
        user_name = "Noma'lum"
        if order.user:
            if order.user.username:
                user_name = order.user.username
            elif order.user.full_name:
                user_name = order.user.full_name
        
        for admin_id in ADMIN_IDS:
            keyboard = [[InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept_order_{order.id}")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await self.application.bot.send_message(
                chat_id=admin_id,
                text=(
                    f"🆕 Yangi buyurtma!\n\n"
                    f"📋 ID: {order.id}\n"
                    f"📍 Jo'natish: {order.address_from}\n"
                    f"📍 Qabul: {order.address_to}\n"
                    f"⚖️ Og'irligi: {order.weight} kg\n"
                    f"💰 Narxi: {order.price} so'm\n"
                    f"👤 Mijoz: {user_name}"
                ),
                reply_markup=reply_markup
            )
    
    def run(self):
        """Botni ishga tushirish"""
        self.application.run_polling()
