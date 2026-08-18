# Zarafshon Taxi — ishchi guruh boti

Telegram guruhida ishlaydigan AI agentlar jamoasi. Har biri o'z sohasida,
hammasi Zarafshon loyihasi kontekstini biladi.

Bu **alohida bot** — taksi botiga tegmaydi. Sabab: `@ZarTaxiBot` mijozlar
ishlatadigan mahsulot, unga ichki asboblarni qo'shsak kod aralashib ketadi
va bitta xato ikkalasini ham yiqitadi.

---

## Agentlar

| Chaqirish | Kim | Model |
|---|---|---|
| `@marketolog` | Jalb qilish, e'lonlar, kanal kontenti | Sonnet |
| `@mahsulot` (`@goyachi`) | Nima qurish/qurmaslik, yangi texnologiyalar | Opus + qidiruv |
| `@kreativ` | Brend, logotip, slogan, vizual uslub | Sonnet |
| `@analitik` (`@moliya`) | Birlik iqtisodiyoti, prognoz, investor raqamlari | Opus + baza |
| `@texnik` (`@kod`) | Kod, xatolar, arxitektura | Sonnet |
| `@operatsion` (`@oper`) | Haydovchilar, sifat, obuna yig'ish | Sonnet + baza |

Misol:
```
@marketolog haydovchilar uchun e'lon matni yoz, uz va ru
```

---

## Qanday ishlaydi

**Umumiy xotira.** Guruhdagi barcha xabarlar bazaga yoziladi. Agent
chaqirilganda oxirgi 25 ta xabar unga kontekst sifatida beriladi — shuning
uchun u boshqa agentlar nima deganini ko'radi va ularga qo'shilishi yoki
e'tiroz bildirishi mumkin. Agent javoblari `[qavs]` bilan ajratilgan.

**Agent o'z-o'zidan gapirmaydi.** Faqat `@` bilan chaqirilganda javob
beradi. Bu ataylab: aks holda Marketolog G'oyachiga javob beradi, u
Marketologga javob beradi, va cheksiz halqa boshlanadi — pul yeb qo'yadi.

**Kunlik xarajat cheklovi.** Har chaqiruvdan oldin tekshiriladi. Limit
oshsa bot javob bermaydi. `DAILY_LIMIT_USD` bilan sozlanadi. Hisob
mahalliy yarim tunda yangilanadi (`TZ_OFFSET_HOURS`, boshida 5).

**Rasm.** Guruhga rasm tashlab izohida agentni chaqiring — u rasmni
ko'radi. Logotip eskizi `@kreativ` ga, xato skrinshoti `@texnik` ga.
Rasmli xabarga reply qilib chaqirsangiz ham ishlaydi.

**Reply.** Biror xabarga reply qilib agentni chaqirsangiz, o'sha
xabar alohida uzatiladi — u oxirgi 25 taga sig'masa ham. Reply
qilib faqat `@texnik` deb yozsangiz, agent o'sha xabarga sharh beradi.

**Javob yozilishi bilan ko'rinadi.** Opus 40-60 soniya o'ylaydi;
matn tayyor bo'lgan sari xabar yangilanib boradi. O'chirish: `STREAM=0`.

**Ovozli xabar.** Ixtiyoriy. Claude audio tushunmaydi, shuning uchun
ovoz avval matnga o'giriladi — buning uchun Whisper bilan mos
keladigan xizmat kerak (`VOICE_API_URL`). Sozlanmasa ovozli xabar
e'tiborsiz qoladi, xato bermaydi.

**Taksi bazasi — faqat o'qish.** `@analitik` va `@operatsion` real
statistikani ko'radi (buyurtmalar, haydovchilar, aylanma). Faqat `SELECT`
ishlatiladi: agent noto'g'ri narsa qilsa ham real ma'lumot o'chmasin.

---

## Buyruqlar

```
/kengash <savol>   — 3 ta agentga birdan berish (mustaqil fikrlar)
/raqamlar          — taksi botidan real statistika
/hisobot           — kunlik hisobotni hozir ko'rish
/xarajat           — API sarfi, agentlar bo'yicha
/agentlar          — ro'yxat
/id                — chat va foydalanuvchi ID si
/tozala            — guruh xotirasini tozalash
```

`/kengash` da agentlar bir-birini ko'rmaydi — mustaqil fikr olasiz.
Ular bahslashishini istasangiz, keyin `@` bilan chaqiring.

---

## Kunlik hisobot

`REPORT_HOUR=7` qo'ysangiz, har kuni ertalab soat 7 da guruhga
statistika tushadi: foydalanuvchi, haydovchi, buyurtma va aylanma —
har biri kechagiga nisbatan o'sish bilan.

```
🌅 Kunlik hisobot — 18.08.2026

Taksi (kechagiga nisbatan)
Foydalanuvchilar: 138 (+38)
Haydovchilar: 12 (+2) (onlayn: 4)
Buyurtmalar: 240 (+40)
Yakunlanish darajasi: 79%

⚠️ 3 ta ariza javob kutmoqda.
```

Eng muhimi oxirgi qator. Haydovchi ariza qoldirib javob kutadi —
bir kun javobsiz qolsa boshqa joyga ketadi. Hisobot buni har kuni
ko'z oldingizga qo'yadi.

Taksi bazasi o'sish tarixini saqlamaydi, faqat joriy holatni. Shuning
uchun kunlik kesim ishchi botning o'z bazasiga yozib boriladi
(`snapshots` jadvali). Birinchi kuni o'sish ko'rsatilmaydi —
solishtiradigan narsa yo'q.

Hisobot AI ishlatmaydi, faqat bazadan o'qiydi — kunlik limitni
yemaydi. Kutmasdan ko'rish uchun `/hisobot`.

---

## Ishga tushirish

### 1. Sozlash

```bash
cp .env.example .env
```

To'ldiring:

| O'zgaruvchi | Nima |
|---|---|
| `STAFF_BOT_TOKEN` | Yangi bot tokeni (@BotFather) |
| `ANTHROPIC_API_KEY` | console.anthropic.com dan |
| `ALLOWED_USERS` | Sizning Telegram ID ingiz |
| `ALLOWED_CHATS` | Guruh ID si (manfiy son) |
| `TAXI_DATABASE_URL` | Taksi botining Postgres manzili |
| `DAILY_LIMIT_USD` | Kunlik chegara, boshida 3-5 qo'ying |
| `REPORT_HOUR` | Kunlik hisobot soati (0-23). Bo'sh — o'chiq |
| `VOICE_API_URL` | Ovoz transkripsiyasi. Bo'sh — o'chiq |

ID larni bilish: botni guruhga qo'shing va `/id` yozing.

⚠️ `ALLOWED_USERS` bo'sh bo'lsa bot ishga tushmaydi. Bu ataylab —
himoyasiz bot pulingizni yeydi.

### 2. Lokal

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

### 3. Railway

Yangi servis → GitHub repo → Variables ni to'ldiring →
`DATABASE_URL` uchun Postgres qo'shing.

---

## Xarajat

O'rtacha so'rov (~8000 kirish + 900 chiqish token), 2026-avgust narxlari:

| Model | Bitta so'rov | Kuniga 30 ta | Oyiga |
|---|---|---|---|
| Sonnet 5 | $0.025 | $0.75 | ~$22 |
| Opus 5 | $0.063 | $1.88 | ~$56 |

Aralash rejimda (kuniga 20 Sonnet + 10 Opus) oyiga **~$34**.

To'rt narsa xarajatni oshiradi: uzun guruh xotirasi, web qidiruv,
`/kengash` (bitta savol = 3 ta so'rov) va rasm (bitta rasm ~1500
token, ya'ni Sonnet'da ~$0.003). Xarajat ko'p ko'rinsa
`MEMORY_MESSAGES` ni kamaytiring.

Oqim rejimi (`STREAM`) narxga ta'sir qilmaydi — o'sha so'rov, faqat
javob bo'lak-bo'lak keladi. Kunlik hisobot ham bepul, u AI emas
baza o'qiydi.

Narxlar o'zgarishi mumkin — `bot/llm.py` dagi `PRICING` ni
vaqti-vaqti bilan tekshiring.

---

## Kontekstni yangilab turing

`bot/agents/context.py` — agentlarning Zarafshon haqidagi bilimi.
Loyihada nimadir o'zgarsa (narx aniqlandi, haydovchi qo'shildi,
yangi funksiya) shu faylni yangilang.

Hozir u yerda `⚠️` bilan belgilangan tekshirilmagan raqamlar bor —
asosiysi narx. Yandexning Zarafshondagi real narxi aniqlangach,
o'sha joyni to'g'rilang va ogohlantirishni olib tashlang.

Agentlar qanchalik aniq ma'lumot olsa, javoblari shunchalik foydali.
Taxminiy kontekst taxminiy javob beradi.

---

## Chegaralar

Bu agentlar strategiya, matn, tahlil beradi. Lekin:

- Bozor ma'lumotini **bilmaydi** — Zarafshonliklar 6000 so'mni qimmat
  deb hisoblaydimi degan savolga taxmin qiladi, u yerdagi odam biladi
- Haydovchi bilan **gaplasha olmaydi** — ishonch faqat shaxsan quriladi
- Qaror **qabul qilmaydi** — nazoratchi sizsiz

Ular vaqtingizni tejaydi, o'rningizni bosmaydi.
