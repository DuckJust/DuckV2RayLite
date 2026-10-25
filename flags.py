# flags.py
from __future__ import annotations

import re
from pathlib import Path
from urllib.request import urlopen

# --- تنظیمات ---
FLAG_DIR = Path(__file__).parent / "flags"
FLAG_DIR.mkdir(exist_ok=True)

# اگه True باشه و فایل محلی نبود، از CDN دانلود می‌کنه.
# برای استفاده ۱۰۰٪ آفلاین این رو False بذار و پوشه flags رو دستی پر کن.
AUTO_DOWNLOAD = False

ISO2_CODES = set("""
ad ae af ag ai al am ao aq ar as at au aw ax az
ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz
ca cc cd cf cg ch ci ck cl cm cn co cr cu cv cw cx cy cz
de dj dk dm do dz
ec ee eg eh er es et
fi fj fk fm fo fr
ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy
hk hm hn hr ht hu
id ie il im in io iq ir is it
je jm jo jp
ke kg kh ki km kn kp kr kw ky kz
la lb lc li lk lr ls lt lu lv ly
ma mc md me mf mg mh mk ml mm mn mo mp mq mr ms mt mu mv mw mx my mz
na nc ne nf ng ni nl no np nr nu nz
om
pa pe pf pg ph pk pl pm pn pr ps pt pw py
qa
re ro rs ru rw
sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz
tc td tf tg th tj tk tl tm tn to tr tt tv tw tz
ua ug um us uy uz
va vc ve vg vi vn vu
wf ws
ye yt
za zm zw
""".split())

NAME_TO_CODE = {
    "germany": "de", "deutschland": "de", "آلمان": "de",
    "netherlands": "nl", "holland": "nl", "هلند": "nl",
    "france": "fr", "فرانسه": "fr",
    "united states": "us", "usa": "us", "america": "us",
    "آمریکا": "us", "امریکا": "us",
    "united kingdom": "gb", "england": "gb", "britain": "gb",
    "uk": "gb", "انگلستان": "gb", "بریتانیا": "gb",
    "turkey": "tr", "turkiye": "tr", "ترکیه": "tr",
    "russia": "ru", "روسیه": "ru",
    "iran": "ir", "ایران": "ir",
    "canada": "ca", "کانادا": "ca",
    "japan": "jp", "ژاپن": "jp",
    "china": "cn", "چین": "cn",
    "korea": "kr", "کره": "kr",
    "india": "in", "هند": "in",
    "finland": "fi", "فنلاند": "fi",
    "sweden": "se", "سوئد": "se",
    "norway": "no", "نروژ": "no",
    "denmark": "dk", "دانمارک": "dk",
    "switzerland": "ch", "سوئیس": "ch",
    "austria": "at", "اتریش": "at",
    "belgium": "be", "بلژیک": "be",
    "poland": "pl", "لهستان": "pl",
    "spain": "es", "اسپانیا": "es",
    "italy": "it", "ایتالیا": "it",
    "portugal": "pt", "پرتغال": "pt",
    "greece": "gr", "یونان": "gr",
    "romania": "ro", "رومانی": "ro",
    "bulgaria": "bg", "بلغارستان": "bg",
    "hungary": "hu", "مجارستان": "hu",
    "czech": "cz", "چک": "cz",
    "ireland": "ie", "ایرلند": "ie",
    "australia": "au", "استرالیا": "au",
    "brazil": "br", "برزیل": "br",
    "mexico": "mx", "مکزیک": "mx",
    "argentina": "ar", "آرژانتین": "ar",
    "south africa": "za", "آفریقای جنوبی": "za",
    "israel": "il", "اسرائیل": "il",
    "uae": "ae", "emirates": "ae", "امارات": "ae",
    "saudi arabia": "sa", "عربستان": "sa",
    "qatar": "qa", "قطر": "qa",
    "kuwait": "kw", "کویت": "kw",
    "singapore": "sg", "سنگاپور": "sg",
    "hong kong": "hk", "هنگ کنگ": "hk",
    "taiwan": "tw", "تایوان": "tw",
    "malaysia": "my", "مالزی": "my",
    "indonesia": "id", "اندونزی": "id",
    "thailand": "th", "تایلند": "th",
    "vietnam": "vn", "ویتنام": "vn",
    "philippines": "ph", "فیلیپین": "ph",
    "pakistan": "pk", "پاکستان": "pk",
    "afghanistan": "af", "افغانستان": "af",
    "iraq": "iq", "عراق": "iq",
    "armenia": "am", "ارمنستان": "am",
    "azerbaijan": "az", "آذربایجان": "az",
    "georgia": "ge", "گرجستان": "ge",
    "lithuania": "lt", "لیتوانی": "lt",
    "latvia": "lv", "لتونی": "lv",
    "estonia": "ee", "استونی": "ee",
    "ukraine": "ua", "اوکراین": "ua",
    "moldova": "md", "مولداوی": "md",
    "cyprus": "cy", "قبرس": "cy",
    "malta": "mt", "مالت": "mt",
    "iceland": "is", "ایسلند": "is",
    "luxembourg": "lu", "لوکزامبورگ": "lu",
    "slovakia": "sk", "اسلواکی": "sk",
    "slovenia": "si", "اسلوونی": "si",
    "croatia": "hr", "کرواسی": "hr",
    "serbia": "rs", "صربستان": "rs",
    "kazakhstan": "kz", "قزاقستان": "kz",
    "uzbekistan": "uz", "ازبکستان": "uz",
    "belarus": "by", "بلاروس": "by",
}

EMOJI_FLAG_TO_CODE = {}
for _code in ISO2_CODES:
    _flag_emoji = ''.join(chr(0x1F1E6 + ord(c) - ord('a')) for c in _code)
    EMOJI_FLAG_TO_CODE[_flag_emoji] = _code.upper()


def detect_country_code(name: str) -> str | None:
    """از اسم سرور، کد کشور ISO2 برمی‌گردونه یا None."""
    if not name:
        return None

    # 1. flag emoji مستقیم (بالاترین اولویت)
    for emoji, code in EMOJI_FLAG_TO_CODE.items():
        if emoji in name:
            return code

    name_lower = name.lower().strip()

    # 2. نام کامل کشور (طولانی‌ترها اول تا «united states» قبل از «us» بیاد)
    for phrase in sorted(NAME_TO_CODE.keys(), key=len, reverse=True):
        if phrase in name_lower:
            return NAME_TO_CODE[phrase].upper()

    # 3. کد 2 حرفی جدا مثل "DE-01" یا "[US]" یا "NL Server"
    for match in re.finditer(r'(?<![A-Za-z])([A-Za-z]{2})(?![A-Za-z])', name):
        token = match.group(1)
        if token.lower() in ISO2_CODES:
            if token.isupper() or token.islower():
                return token.upper()

    return None


def flag_path(code: str) -> Path:
    """مسیر فایل PNG محلی پرچم."""
    return FLAG_DIR / f"{code.lower()}.png"


def ensure_flag(code: str, timeout: float = 6.0) -> bool:
    """
    بررسی می‌کنه پرچم به‌صورت آفلاین موجوده.
    اگه نبود و AUTO_DOWNLOAD=True باشه، از CDN دانلود می‌کنه.
    """
    if not code or len(code) != 2:
        return False
    path = flag_path(code)
    if path.exists() and path.stat().st_size > 200:
        return True

    if not AUTO_DOWNLOAD:
        return False

    try:
        url = f"https://flagcdn.com/w40/{code.lower()}.png"
        with urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        if len(data) > 200:
            path.write_bytes(data)
            return True
    except Exception as e:
        print(f"[flags] download failed for {code}: {e}")
    return False