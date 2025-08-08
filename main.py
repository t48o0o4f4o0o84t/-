import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, Message
import os
import subprocess
import threading
import json
import datetime
import time
import psutil

# لا تضع التوكن هنا مباشرة
API_TOKEN = os.environ.get('TELEGRAM_API_TOKEN')
bot = telebot.TeleBot(API_TOKEN)

# Render توفر مساحة تخزين مؤقتة في هذا المسار
FILES_DIR = '/var/data/ai'
LOG_FILE = '/var/data/ai/activity_log.json'

if not os.path.exists(FILES_DIR):
    os.makedirs(FILES_DIR)

waiting_for_upload = set()
running_processes = {}
# يمكنك إضافة أرقام حسابات الأدمن هنا
ADMINS = {59348970}

def log_activity(chat_id, action, filename=None, extra=None):
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "user_id": chat_id,
        "action": action,
        "filename": filename,
        "extra": extra
    }
    logs = []
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            try:
                logs = json.load(f)
            except:
                logs = []
    logs.append(entry)
    with open(LOG_FILE, 'w', encoding='utf-8') as f:
        json.dump(logs, f, ensure_ascii=False, indent=2)

def check_admin(chat_id):
    return chat_id in ADMINS

def get_files_list():
    return [f for f in os.listdir(FILES_DIR) if f.endswith('.py')]

def build_files_keyboard(chat_id):
    files = get_files_list()
    keyboard = InlineKeyboardMarkup(row_width=2)
    for f in files:
        row = []
        if chat_id not in running_processes or running_processes[chat_id]['filename'] != f:
            row.append(InlineKeyboardButton(f"▶️ تشغيل {f}", callback_data=f"run::{f}"))
        else:
            row.append(InlineKeyboardButton(f"🛑 إيقاف {f}", callback_data=f"stop::{f}"))
        if check_admin(chat_id):
            row.append(InlineKeyboardButton(f"🗑️ حذف {f}", callback_data=f"del::{f}"))
        keyboard.add(*row)
    return keyboard

def main_menu_keyboard(chat_id):
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("⬆️ رفع ملف بايثون", callback_data="upload"),
        InlineKeyboardButton("📂 عرض الملفات", callback_data="list_files"),
    )
    if check_admin(chat_id):
        keyboard.add(InlineKeyboardButton("📋 سجل النشاط", callback_data="show_logs"))
    return keyboard

def syntax_check(file_path):
    result = subprocess.run(['python3', '-m', 'py_compile', file_path], capture_output=True, text=True)
    return result.returncode == 0, result.stderr

def run_file_with_profiling(chat_id, file_path, filename):
    try:
        start_time = time.time()
        proc = subprocess.Popen(
            ['python3', file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding='utf-8'
        )
        pid = proc.pid
        p = psutil.Process(pid)
        stdout, stderr = proc.communicate()
        end_time = time.time()
        elapsed_time = end_time - start_time
        try:
            memory_info = p.memory_info()
            memory_used_mb = memory_info.rss / (1024 * 1024)
        except:
            memory_used_mb = 0
        reply = f"🖥️ ناتج تشغيل {filename}:\n\n{stdout.strip() or '(لا يوجد إخراج)'}"
        if stderr.strip():
            reply += f"\n\n⚠️ أخطاء:\n{stderr.strip()}"
        reply += f"\n\n⏱️ وقت التشغيل: {elapsed_time:.2f} ثانية"
        reply += f"\n🧠 استهلاك الذاكرة: {memory_used_mb:.2f} ميجابايت"
        bot.send_message(chat_id, reply)
        log_activity(chat_id, "run", filename)
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ أثناء التشغيل: {str(e)}")

def stop_running_process(chat_id):
    if chat_id in running_processes:
        proc = running_processes[chat_id]['proc']
        proc.kill()
        running_processes.pop(chat_id, None)
        return True
    return False

@bot.message_handler(commands=['start'])
def cmd_start(message: Message):
    chat_id = message.chat.id
    bot.send_message(
        chat_id,
        "👋 مرحباً في بوت استضافة بايثون الخارق!\nاختر من القائمة:",
        reply_markup=main_menu_keyboard(chat_id)
    )
    log_activity(chat_id, "start")

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call: CallbackQuery):
    chat_id = call.message.chat.id
    data = call.data
    if data == "upload":
        waiting_for_upload.add(chat_id)
        bot.answer_callback_query(call.id, "أرسل ملف بايثون (*.py) لرفعه.")
        bot.send_message(chat_id, "يرجى إرسال ملف بايثون (*.py) الآن.")
        return
    if data == "list_files":
        files = get_files_list()
        if not files:
            bot.answer_callback_query(call.id, "🚫 لا توجد ملفات بايثون.")
            bot.send_message(chat_id, "🚫 لا توجد ملفات حالياً.")
            return
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, "📂 ملفات بايثون:", reply_markup=build_files_keyboard(chat_id))
        return
    if data.startswith("run::"):
        filename = data.split("::")[1]
        file_path = os.path.join(FILES_DIR, filename)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ الملف غير موجود!")
            return
        if chat_id in running_processes:
            bot.answer_callback_query(call.id, "⚠️ هناك ملف يعمل حالياً، أوقفه أولاً.")
            return
        ok, err = syntax_check(file_path)
        if not ok:
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, f"❌ أخطاء في بناء الجملة:\n{err}")
            return
        bot.answer_callback_query(call.id, f"جارِ تشغيل {filename}...")
        thread = threading.Thread(target=run_file_with_profiling, args=(chat_id, file_path, filename), daemon=True)
        thread.start()
        log_activity(chat_id, "run_start", filename)
        return
    if data.startswith("stop::"):
        filename = data.split("::")[1]
        if stop_running_process(chat_id):
            bot.answer_callback_query(call.id, f"🛑 تم إيقاف تشغيل {filename}.")
            bot.send_message(chat_id, f"🛑 تم إيقاف تشغيل الملف: {filename}")
            log_activity(chat_id, "stop", filename)
        else:
            bot.answer_callback_query(call.id, "⚠️ لا يوجد ملف يعمل حالياً.")
        return
    if data.startswith("del::"):
        filename = data.split("::")[1]
        file_path = os.path.join(FILES_DIR, filename)
        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "❌ الملف غير موجود!")
            return
        if not check_admin(chat_id):
            bot.answer_callback_query(call.id, "❌ صلاحية الحذف متاحة فقط للأدمن!")
            return
        try:
            os.remove(file_path)
            bot.answer_callback_query(call.id, f"🗑️ تم حذف {filename}")
            bot.send_message(chat_id, f"🗑️ تم حذف الملف: {filename}")
            log_activity(chat_id, "delete", filename)
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ خطأ أثناء الحذف!")
            bot.send_message(chat_id, f"❌ خطأ أثناء حذف الملف: {str(e)}")
        return
    if data == "show_logs":
        if not check_admin(chat_id):
            bot.answer_callback_query(call.id, "❌ صلاحية الوصول مرفوضة!")
            return
        if not os.path.exists(LOG_FILE):
            bot.answer_callback_query(call.id)
            bot.send_message(chat_id, "لا يوجد سجل نشاط حتى الآن.")
            return
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            logs = json.load(f)
        text = "\n".join([f"{log['timestamp']} - {log['user_id']} - {log['action']} - {log.get('filename','')}" for log in logs[-10:]])
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, f"📋 آخر 10 نشاطات:\n{text}")
        return

@bot.message_handler(content_types=['document'])
def handle_document(message: Message):
    chat_id = message.chat.id
    if chat_id not in waiting_for_upload:
        bot.send_message(chat_id, "لرفع ملف، اضغط زر '⬆️ رفع ملف بايثون' أولاً.")
        return
    doc = message.document
    if not doc.file_name.endswith('.py'):
        bot.send_message(chat_id, "❌ فقط ملفات بايثون (*.py) مسموح برفعها.")
        return
    try:
        file_info = bot.get_file(doc.file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        file_path = os.path.join(FILES_DIR, doc.file_name)
        with open(file_path, 'wb') as f:
            f.write(downloaded_file)
        ok, err = syntax_check(file_path)
        if not ok:
            os.remove(file_path)
            bot.send_message(chat_id, f"❌ أخطاء في بناء الجملة:\n{err}")
            return
        bot.send_message(chat_id, f"✅ تم رفع الملف بنجاح: {doc.file_name}")
        waiting_for_upload.remove(chat_id)
        log_activity(chat_id, "upload", doc.file_name)
    except Exception as e:
        bot.send_message(chat_id, f"❌ خطأ أثناء رفع الملف: {str(e)}")

print("بوت تيليجرام استضافة بايثون الخارق شغال...")
bot.infinity_polling()
