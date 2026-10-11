# Ustoz Elite — Telegram bot

Abituriyentlar uchun AI ustoz va studentlar uchun slayd, referat, mustaqil ish, maqola, kurs ishi va test tayyorlash boti.

## Ishga tushirish

```bash
cd "~/projects/Elite Future/ustoz_elite"
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
cp .env.example .env      # keyin .env ni to'ldiring
./venv/bin/python app.py
```

`.env` da kamida `BOT_TOKEN`, `ADMINS`, `ANTHROPIC_API_KEY`, `CARD_NUMBER` bo'lishi kerak.
`DATABASE_URL` bo'sh qolsa, sinov uchun SQLite (`ustoz_elite.db`) ishlatiladi. Haqiqiy ishga tushirishda PostgreSQL:

```bash
sudo -u postgres createuser -P ustoz
sudo -u postgres createdb -O ustoz ustoz_elite
# .env: DATABASE_URL=postgresql+asyncpg://ustoz:PAROL@localhost:5432/ustoz_elite
```

Jadvallar bot birinchi ishga tushganda avtomatik yaratiladi.

## Tuzilma

| Papka | Vazifasi |
|---|---|
| `data/` | sozlamalar, narxlar, tariflar, tugma matnlari |
| `database/` | modellar va so'rovlar (SQLAlchemy async) |
| `handlers/users/` | ro'yxatdan o'tish, Abituriyent, Student, testlar, to'lov |
| `handlers/admin/` | `/admin`, `/tolovlar`, `/premium`, `/block` |
| `services/ai.py` | Claude API: reja, slayd, hujjat, testga javob, kitobchadan test, AI ustoz |
| `services/documents.py` | `.pptx` va `.docx` yasash |
| `services/extract.py` | PDF/Word dan matn olish, testlarni 30 tadan bo'lish |
| `services/worker.py` | fon navbati: og'ir ishlar ketma-ket bajariladi, bot qotmaydi |
| `services/payments.py` | chek orqali to'lov, admin tasdiqlashi |

## To'lov oqimi

1. Foydalanuvchi xizmatni tanlaydi → bot karta, summa va noyob kod (`UE-12345`) beradi.
2. «✅ To'lov qildim» → chek rasmi yoki PDF → adminlarga tasdiqlash tugmalari bilan boradi.
3. Admin tasdiqlasa ish navbatga tushadi (yoki Premium yoqiladi); rad etsa sabab va yangi kod yuboriladi.
4. Bir chekni ikki marta yuborib bo'lmaydi.

Payme/Click ulanganda faqat to'lovni tasdiqlash qismi o'zgaradi: `payments` jadvalida `method` va `provider_txn_id` maydonlari tayyor.

## Narx va limitlarni o'zgartirish

`data/config.py`: `PRICES`, `FREE_DOCS`, `PLANS` (AI ustoz kunlik limiti `ai_chat`).

## Serverda 24/7 ishlatish (systemd)

Bot kompyuter yoki server yoqilganda o'zi ishga tushadi va to'xtab qolsa 5 soniyada qayta yonadi.

```bash
# 1) Loyiha papkasida turib (cd ".../ustoz_elite") faylni o'rnating — foydalanuvchi va yo'l avtomatik qo'yiladi
sed -e "s|USERNAME|$USER|g" -e "s|PROJECT_DIR|$PWD|g" deploy/ustoz_elite.service | sudo tee /etc/systemd/system/ustoz_elite.service

# 2) Yoqish
sudo systemctl daemon-reload
sudo systemctl enable --now ustoz_elite

# Holatini ko'rish / jurnal / qayta ishga tushirish
systemctl status ustoz_elite
journalctl -u ustoz_elite -f
sudo systemctl restart ustoz_elite
```

Kodni yangilagandan keyin: `sudo systemctl restart ustoz_elite`.
Eslatma: qayta ishga tushirilganda o'sha paytda ishlanayotgan testlar (quiz) yo'qoladi — o'quvchi testni qaytadan boshlaydi.

## Admin buyruqlari

| Buyruq | Vazifasi |
|---|---|
| `/admin` | statistika, daromad, menyu |
| `/sinflar` | sinflar → fanlar → nomli testlar (AI / Avtomatik / Qo'lda) va mock imtihonlar |
| `/tolovlar` | tekshirilmagan cheklar |
| `/xabar` | barcha foydalanuvchilarga xabar |
| `/premium ID tarif kun` | qo'lda Premium berish (basic, pro, max) |
| `/block ID`, `/unblock ID` | foydalanuvchini bloklash |
