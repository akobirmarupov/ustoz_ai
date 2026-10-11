# Menyu tugmalari matnlari (handlerlar shu konstantalar bilan solishtiradi)

BTN_ABITURIYENT = "🎓 Abituriyent"
BTN_STUDENT = "👨‍🎓 Student"
BTN_PROFILE = "👤 Profil"
BTN_PAYMENTS = "💳 To'lovlarim"
BTN_HELP = "ℹ️ Yordam"
BTN_BACK = "⬅️ Bosh menyu"
BTN_CANCEL = "❌ Bekor qilish"

# Abituriyent
BTN_SOLVE = "📝 Test ishlash"
BTN_MOCK = "🧪 Mock imtihon"
BTN_MISTAKES = "❌ Xatolar daftari"
BTN_TUTOR = "🤖 AI ustozga savol"
BTN_RESULTS = "📈 Natijalarim"
BTN_RATING = "🏆 Reyting"
BTN_PREMIUM = "⭐️ Premium"
ABITURIYENT_SOON: tuple = ()

SUBJECTS = {"math": "Matematika", "english": "Ingliz tili"}

# Student
BTN_TEST = "✅ Test tayyorlash"
BTN_MY_WORKS = "🗂 Mening ishlarim"

DOC_KINDS = {
    "slide": {"button": "📊 Slayd", "title": "Slayd (taqdimot)",
              "sizes": [("10 ta slayd", 10), ("15 ta slayd", 15), ("20 ta slayd", 20)]},
    "referat": {"button": "📄 Referat", "title": "Referat",
                "sizes": [("8-10 bet", 9), ("12-15 bet", 13)]},
    "mustaqil": {"button": "📝 Mustaqil ish", "title": "Mustaqil ish",
                 "sizes": [("5-7 bet", 6), ("8-10 bet", 9), ("12-15 bet", 13)]},
    "maqola": {"button": "📰 Maqola", "title": "Maqola",
               "sizes": [("5-7 bet", 6), ("8-10 bet", 9)]},
    "kurs": {"button": "📚 Kurs ishi", "title": "Kurs ishi",
             "sizes": [("25-30 bet", 27)]},
}
DOC_BUTTONS = {v["button"]: k for k, v in DOC_KINDS.items()}

LANGS = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Ruscha", "en": "🇬🇧 Inglizcha"}

KIND_TITLES = {k: v["title"] for k, v in DOC_KINDS.items()} | {"test": "Test tayyorlash"}

ORDER_STATUS = {
    "outline": "📝 Reja",
    "awaiting_payment": "💳 To'lov kutilmoqda",
    "paid": "✅ To'langan — fayl kutilmoqda",
    "payment_review": "⏳ To'lov tekshirilmoqda",
    "queued": "⏳ Navbatda",
    "processing": "⚙️ Tayyorlanmoqda",
    "preparing": "⚙️ Fayl o'qilmoqda",
    "free_part": "🎁 test_1 bepul",
    "done": "✅ Tayyor",
    "failed": "⚠️ Xatolik",
    "rejected": "❌ Rad etildi",
}
