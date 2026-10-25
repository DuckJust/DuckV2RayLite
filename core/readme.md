<div align="center">

# 🦆 Duck V2Ray Lite

**کلاینت سبک، سریع و مدرن V2Ray برای ویندوز (نسخه پایتون)**

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-0078D6.svg)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

<img src="https://raw.githubusercontent.com/duckjust/DuckV2RayLite/main/logo.png" alt="Duck V2Ray Lite Logo" width="150" />

</div>

---

## 📖 درباره پروژه
**Duck V2Ray Lite** یک نرم‌افزار متن‌باز و فوق‌العاده سبک برای مدیریت، تست و اتصال به سرورهای V2Ray (Xray) است. این نسخه با زبان **Python** و فریم‌ورک **PyQt5** توسعه یافته و تجربه‌ای روان و بدون پیچیدگی را برای شما فراهم می‌کند.

## ✨ ویژگی‌های کلیدی
- 🚀 **تست دقیق و پایدار:** تست سرورها با استفاده از ۱۰ سایت معتبر (HTTP) و پینگ TCP.
- 🛡️ **پشتیبانی از پروتکل‌ها:** VMess, VLESS, Trojan, Shadowsocks.
- 🌍 **تشخیص خودکار کشور:** نمایش پرچم کشور سرورها بر اساس نام آن‌ها.
- 📊 **نمودار سرعت زنده:** مشاهده لحظه‌ای سرعت دانلود/آپلود و تاریخچه مصرف.
- 🖥️ **یکپارچگی با ویندوز:** تنظیم و بازگردانی خودکار پروکسی سیستم با یک کلیک.

---

## 🚀 راهنمای نصب و راه‌اندازی (برای کاربران)

برای اجرای برنامه، نیازی به نصب پایتون ندارید. مراحل زیر را به ترتیب انجام دهید:

### گام اول: دانلود برنامه
از بخش [**Releases**](https://github.com/duckjust/DuckV2RayLite/releases/latest) آخرین نسخه فایل `DuckV2RayLite.zip` را دانلود کرده و آن را در یک پوشه (مثلاً `C:\DuckV2RayLite`) استخراج کنید.

### گام دوم: دانلود هسته Xray (بسیار مهم)
به دلیل حجم بالای فایل‌های هسته، این فایل‌ها به صورت مستقیم در ریپازیتوری قرار داده نشده‌اند. شما باید هسته را بر اساس سیستم‌عامل خود دانلود کنید:

1. به صفحه رسمی [Xray-core Releases](https://github.com/XTLS/Xray-core/releases/latest) بروید.
2. فایل **`Xray-windows-64.zip`** را دانلود کنید.
3. فایل‌های `xray.exe`، `geoip.dat` و `geosite.dat` را از داخل فایل ZIP استخراج کرده و آن‌ها را داخل پوشه **`core`** (که در کنار فایل `DuckV2RayLite.exe` قرار دارد) کپی کنید.

> **ساختار پوشه شما باید به این شکل باشد:**
> ```text
> 📁 DuckV2RayLite
> ├── 📄 DuckV2RayLite.exe
> ├── 📁 core
> │   ├── 📄 xray.exe
> │   ├── 📄 geoip.dat
> │   └── 📄 geosite.dat
> └── 📁 flags
> ```

### گام سوم: اجرا
حالا کافیست فایل `DuckV2RayLite.exe` را اجرا کنید و لذت ببرید! 🎉

---

## 🛠️ راهنمای توسعه‌دهندگان (اجرا از سورس کد)

اگر قصد دارید کدها را تغییر دهید یا خودتان برنامه را بیلد کنید، مراحل زیر را دنبال کنید:

1. **کلون کردن مخزن:**
   ```bash
   git clone https://github.com/duckjust/DuckV2RayLite.git
   cd DuckV2RayLite