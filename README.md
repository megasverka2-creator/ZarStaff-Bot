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
oshsa bot javob bermaydi. `DAILY_LIMIT_USD` bilan sozlanadi.

**Taksi bazasi — faqat o'qish.** `@analitik` va `@operatsion` real
statistikani ko'radi (buyurtmalar, haydovchilar, aylanma). Faqat `SELECT`
ishlatiladi: agent noto'g'ri narsa qilsa ham real ma'lumot o'chmasin.

---

## Buyruqlar

```
/kengash <savol>   — 3 ta agentga birdan berish (mustaqil fikrlar)
/raqamlar          — taksi botidan real statistika
/xarajat           — API sarfi, agentlar bo'yicha
/agentlar          — ro'yxat
/id                — chat va foydalanuvchi ID si
/tozala            — guruh xotirasini tozalash
```

`/kengash` da agentlar bir-birini ko'rmaydi — mustaqil fikr olasiz.
Ular bahslashishini istasangiz, keyin `@` bilan chaqiring.

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

Uchta narsa xarajatni oshiradi: uzun guruh xotirasi, web qidiruv,
`/kengash` (bitta savol = 3 ta so'rov). Xarajat ko'p ko'rinsa
`MEMORY_MESSAGES` ni kamaytiring.

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
