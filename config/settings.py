# config/settings.py
import os

# -------- المسارات العامة --------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.normpath(os.path.join(BASE_DIR, ".."))

# فولدر التحميل المؤقت قبل الرفع
TEMP_DOWNLOAD_DIR = os.path.join(APP_ROOT, "temp_files")
os.makedirs(TEMP_DOWNLOAD_DIR, exist_ok=True)

# -------- Google Drive --------
# سيبها فاضية لو هتدخل الـ Folder ID من الواجهة
DRIVE_FOLDER_ID = ""

# اسم فولدر الأرشيف اللي هننقل له الملفات على Drive بعد الرفع
ARCHIVE_FOLDER_NAME = "Sigma_Archive"

# -------- SFTP (قيم افتراضية) --------
SFTP_HOST = ""          # بيتكتب من الواجهة أو من بروفايل محفوظ
SFTP_PORT = 22
SFTP_USERNAME = ""
SFTP_PASSWORD = ""      # إحنا بنحفظه مشفّر داخل profiles_store، القيمة هنا للإفتراضي بس
SFTP_KEY_FILE = ""      # اختياري: مسار مفتاح خاص لو هتستخدم key بدل الباسورد
SFTP_REMOTE_DIR = "/upload"  # المسار الافتراضي على السيرفر

# -------- عام --------
POLL_INTERVAL = 30      # عدد الثواني بين كل دورة مراقبة
# فلترة اختيارية: [] يعني مسموح كل الامتدادات
ALLOWED_EXTENSIONS = []   # مثال: ["csv", "txt", "pdf"]
# تجاهل ملفات أكبر من الحجم ده (ميجابايت) — 0 أو None لتعطيل الشرط
MAX_FILE_SIZE_MB = 0
