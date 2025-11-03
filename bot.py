import os, json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, BotCommand, InputMediaPhoto, Update as TGUpdate
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters

# ====== CONFIG ======
BOT_TOKEN = "8250732880:AAFjc1mv1NT23e4Rk1uIxpBndJ358Gf1hqc"
DATA_FILE = "data.json"
LINKS_FILE = "links.json"  # chat_id:msg_id -> event_id

# ====== STATES ======
EAT_CHOICE, EAT_AMOUNT, EAT_FOOD = range(3)
SLEEP_CHOICE = 10
SLEEP_REC_START, SLEEP_REC_END = 11, 12
POOP_WAIT = 20
STATS_CAT, STATS_RANGE = 30, 31

MONTHS_UA = ["Січня","Лютого","Березня","Квітня","Травня","Червня",
             "Липня","Серпня","Вересня","Жовтня","Листопада","Грудня"]

def fmt_dt_uk(dt: datetime) -> str:
    return f"{dt.day} {MONTHS_UA[dt.month-1]} {dt.hour:02d}:{dt.minute:02d}"

def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")

def fmt_minutes(total_min: int) -> str:
    h = total_min // 60
    m = total_min % 60
    parts = []
    if h: parts.append(f"{h} год")
    parts.append(f"{m} хв")
    return " ".join(parts)

def parse_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")

def day_start(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def parse_user_time(txt: str) -> Optional[datetime]:
    txt = txt.strip()
    if len(txt) == 5 and txt[2] == ":" and txt[:2].isdigit() and txt[3:].isdigit():
        hh, mm = int(txt[:2]), int(txt[3:])
        today = datetime.now()
        return today.replace(hour=hh, minute=mm, second=0, microsecond=0)
    try:
        return datetime.strptime(txt, "%d-%m-%Y %H:%M")
    except:
        return None

MAIN_KB = ReplyKeyboardMarkup(
    [["/eat", "/sleep"],
     ["/poop", "/stats"]],
    resize_keyboard=True
)

def ensure_file(path: str, default):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)

def ensure_data_file():
    ensure_file(DATA_FILE, [])
    ensure_file(LINKS_FILE, {})

def load_data(): return json.load(open(DATA_FILE, encoding="utf-8"))
def save_data(d): json.dump(d, open(DATA_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
def load_links(): return json.load(open(LINKS_FILE, encoding="utf-8"))
def save_links(l): json.dump(l, open(LINKS_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def next_id(d: List[Dict[str, Any]]) -> int:
    return (max((x.get("id", 0) for x in d), default=0) + 1)

def append_item(x: Dict[str, Any]) -> int:
    ensure_data_file()
    d = load_data()
    x["id"] = next_id(d)
    d.append(x)
    save_data(d)
    return x["id"]

def link_message_to_event(chat_id: int, msg_id: int, event_id: int):
    links = load_links()
    links[f"{chat_id}:{msg_id}"] = event_id
    save_links(links)

def link_both(update, bot_msg_id: Optional[int], event_id: int):
    chat_id = update.effective_chat.id
    if bot_msg_id:
        link_message_to_event(chat_id, bot_msg_id, event_id)
    if update.message:
        link_message_to_event(chat_id, update.message.message_id, event_id)

def resolve_event_id_from_reply(update) -> Optional[int]:
    if not update.message or not update.message.reply_to_message:
        return None
    chat_id = update.effective_chat.id
    msg_id = update.message.reply_to_message.message_id
    links = load_links()
    return links.get(f"{chat_id}:{msg_id}")

def get_event_by_id(event_id: int) -> Optional[Dict[str, Any]]:
    d = load_data()
    for x in d:
        if x.get("id") == event_id:
            return x
    return None

def delete_event_by_id(event_id: int) -> bool:
    d = load_data()
    newd = [x for x in d if x.get("id") != event_id]
    if len(newd) == len(d):
        return False
    save_data(newd)
    links = load_links()
    to_del = [k for k, v in links.items() if v == event_id]
    for k in to_del: del links[k]
    save_links(links)
    return True

def update_event_time(event_id: int, new_dt: datetime) -> bool:
    d = load_data()
    ok = False
    for x in d:
        if x.get("id") == event_id:
            x["time"] = new_dt.strftime("%Y-%m-%d %H:%M")
            ok = True
            break
    if ok: save_data(d)
    return ok

# ---------- COMMANDS ----------
async def start(update, ctx):
    await update.message.reply_text(
        "Привіт! Це трекер для Ріка 👶\n\n"
        "🍽️ /eat — їжа\n"
        "😴 /sleep — сон (є 📝 Запис заднім числом)\n"
        "💩 /poop — какашки\n"
        "📊 /stats — статистика\n"
        "🗑️ /del — видалити (відповіддю на повідомлення)\n",
        reply_markup=MAIN_KB
    )

async def menu_cmd(update, ctx): await update.message.reply_text("Меню:", reply_markup=MAIN_KB)
async def cancel_cmd(update, ctx): ctx.user_data.clear(); await update.message.reply_text("Скасовано.", reply_markup=MAIN_KB); return ConversationHandler.END

# /eat
EAT_TYPE_KB = ReplyKeyboardMarkup([["Суміш", "Прикорм"]], resize_keyboard=True, one_time_keyboard=True)
async def eat_start(update, ctx): await update.message.reply_text("Що записуємо?", reply_markup=EAT_TYPE_KB); return EAT_CHOICE
async def eat_choice(update, ctx):
    t = (update.message.text or "").lower()
    if "сум" in t: ctx.user_data["eat"]="formula"; await update.message.reply_text("Скільки мл? (тільки число)", reply_markup=ReplyKeyboardRemove()); return EAT_AMOUNT
    if "при" in t: ctx.user_data["eat"]="solids"; await update.message.reply_text("Що саме їв?", reply_markup=ReplyKeyboardRemove()); return EAT_FOOD
    await update.message.reply_text("Обери: Суміш або Прикорм.", reply_markup=EAT_TYPE_KB); return EAT_CHOICE
async def eat_amount(update, ctx):
    raw = (update.message.text or "").strip()
    if not raw.isdigit(): await update.message.reply_text("Введи число, напр. 180"); return EAT_AMOUNT
    ml = int(raw)
    eid = append_item({"type":"eat","food":"-","amount":str(ml),"time":now_str()})
    sent = await update.message.reply_text(f"✅ Суміш, {ml} мл — {fmt_dt_uk(datetime.now())}", reply_markup=MAIN_KB)
    link_both(update, sent.message_id, eid); ctx.user_data.clear(); return ConversationHandler.END
async def eat_food(update, ctx):
    food = (update.message.text or "").strip()
    if not food or food.startswith("/"): await update.message.reply_text("Скасовано.", reply_markup=MAIN_KB); return ConversationHandler.END
    eid = append_item({"type":"eat","food":food,"amount":"-","time":now_str()})
    sent = await update.message.reply_text(f"✅ Прикорм — {food} — {fmt_dt_uk(datetime.now())}", reply_markup=MAIN_KB)
    link_both(update, sent.message_id, eid); ctx.user_data.clear(); return ConversationHandler.END

# /sleep
SLEEP_KB = ReplyKeyboardMarkup([["😴 Заснув","🌞 Прокинувся","📝 Запис"]], resize_keyboard=True, one_time_keyboard=True)
async def sleep_start(update, ctx): await update.message.reply_text("Обери:", reply_markup=SLEEP_KB); return SLEEP_CHOICE
def last_sleep_start(d):
    for x in reversed(d):
        if x.get("type")=="sleep" and x.get("action")=="sleep_start": return x
    return None
async def sleep_choice(update, ctx):
    t = (update.message.text or "").lower(); now_iso = now_str()
    if "зас" in t:
        eid = append_item({"type":"sleep","action":"sleep_start","time":now_iso})
        sent = await update.message.reply_text(f"😴 Заснув — {fmt_dt_uk(datetime.now())}", reply_markup=MAIN_KB)
        link_both(update, sent.message_id, eid); return ConversationHandler.END
    if "про" in t:
        d = load_data(); s = last_sleep_start(d)
        eid = append_item({"type":"sleep","action":"sleep_end","time":now_iso})
        if not s:
            sent = await update.message.reply_text("⚠️ Не знайдено сну", reply_markup=MAIN_KB)
            link_both(update, sent.message_id, eid); return ConversationHandler.END
        st = parse_dt(s["time"]); en = parse_dt(now_iso)
        mins = max(0, int((en-st).total_seconds()/60))
        sent = await update.message.reply_text(f"🌞 Прокинувся — {fmt_dt_uk(datetime.now())}\n🕒 {fmt_minutes(mins)}", reply_markup=MAIN_KB)
        link_both(update, sent.message_id, eid); return ConversationHandler.END
    if "запис" in t:
        await update.message.reply_text("О котрій заснув?", reply_markup=ReplyKeyboardRemove()); return SLEEP_REC_START
    await update.message.reply_text("Обери кнопку", reply_markup=SLEEP_KB); return SLEEP_CHOICE
async def sleep_rec_start(update, ctx):
    dt = parse_user_time(update.message.text or "")
    if not dt: await update.message.reply_text("Формат: HH:MM або DD-MM-YYYY HH:MM"); return SLEEP_REC_START
    ctx.user_data["rec_start"] = dt; await update.message.reply_text("О котрій прокинувся?"); return SLEEP_REC_END
async def sleep_rec_end(update, ctx):
    dt_end = parse_user_time(update.message.text or "")
    if not dt_end: await update.message.reply_text("Формат: HH:MM або DD-MM-YYYY HH:MM"); return SLEEP_REC_END
    dt_start = ctx.user_data.get("rec_start")
    if not dt_start or dt_end <= dt_start: await update.message.reply_text("Кінець має бути пізніше за початок."); return SLEEP_REC_END
    eid1 = append_item({"type":"sleep","action":"sleep_start","time":dt_start.strftime("%Y-%m-%d %H:%M")})
    eid2 = append_item({"type":"sleep","action":"sleep_end","time":dt_end.strftime("%Y-%m-%d %H:%M")})
    mins = int((dt_end - dt_start).total_seconds()//60)
    sent = await update.message.reply_text(f"📝 Записано: сон {fmt_minutes(mins)}\nз {fmt_dt_uk(dt_start)} до {fmt_dt_uk(dt_end)}", reply_markup=MAIN_KB)
    link_both(update, sent.message_id, eid2); ctx.user_data.clear(); return ConversationHandler.END

# /poop
async def poop_start(update, ctx):
    when = now_str()
    eid = append_item({"type":"poop","action":"pooped","time":when,"photo_file_id":None})
    ctx.user_data["poop"]=when
    sent = await update.message.reply_text("💩 Записано. Надішли фото або '-'", reply_markup=ReplyKeyboardRemove())
    link_both(update, sent.message_id, eid); return POOP_WAIT
async def poop_wait(update, ctx):
    if update.message.text == "-":
        await update.message.reply_text("✅ 💩 без фото", reply_markup=MAIN_KB); return ConversationHandler.END
    if update.message.photo:
        d = load_data(); fid = update.message.photo[-1].file_id; target_id=None
        for x in reversed(d):
            if x.get("type")=="poop" and x.get("photo_file_id") is None:
                x["photo_file_id"]=fid; target_id=x["id"]; break
        save_data(d)
        sent = await update.message.reply_text("✅ 💩 + фото", reply_markup=MAIN_KB)
        if target_id: link_both(update, sent.message_id, target_id)
        return ConversationHandler.END
    await update.message.reply_text("Фото або '-'"); return POOP_WAIT

# /stats
STATS_CAT_KB = ReplyKeyboardMarkup([["📊 Усе"],["🥗 Їжа"],["😴 Сон"],["💩 Какашки"]], resize_keyboard=True, one_time_keyboard=True)
STATS_RANGE_KB = ReplyKeyboardMarkup([["Сьогодні"],["7 днів"],["30 днів"]], resize_keyboard=True, one_time_keyboard=True)

def period_label(days:int)->str:
    return "Сьогодні" if days==1 else ("останні 7 днів" if days==7 else "останні 30 днів")

def filter_since(days: int):
    now = datetime.now()
    return day_start(now) if days==1 else day_start(now) - timedelta(days=days-1)

def build_eat_stats(days: int) -> str:
    d = load_data(); since = filter_since(days)
    eats = [x for x in d if x.get("type")=="eat" and parse_dt(x["time"]) >= since]
    cnt=len(eats); total_ml=0; solids=[]; last=None
    for x in eats:
        a=x.get("amount","-"); 
        if isinstance(a,str) and a.isdigit(): total_ml+=int(a)
        food=(x.get("food") or "").strip(); 
        if food and food!="-": solids.append(food)
        if (last is None) or (parse_dt(x["time"])>parse_dt(last["time"])): last=x
    uniq=", ".join(sorted(set(solids), key=str.lower)) if solids else "—"
    last_line="—"
    if last:
        dt=fmt_dt_uk(parse_dt(last["time"]))
        last_line=f"{dt} ({last['food']})" if (last.get("food") or "-")!="-" else f"{dt} (суміш {last.get('amount','?')} мл)"
    lines=[f"📊 Статистика — Їжа — {period_label(days)}",
           f"🍽️ Прийомів: {cnt}",
           f"🍼 Сумарно суміші: {total_ml} мл",
           f"🥗 Продукти (унікальні): {uniq}",
           f"⏱️ Останній прийом: {last_line}"]
    if days==1:
        solids_today=[x for x in eats if (x.get('food') or '-')!='-']
        if solids_today:
            solids_today.sort(key=lambda x: parse_dt(x["time"]))
            lines.append("🍽️ Список за сьогодні:")
            for x in solids_today:
                t=parse_dt(x["time"]); lines.append(f"• {t.hour:02d}:{t.minute:02d} — {x['food']}")
    return "\n".join(lines)

def build_sleep_stats(days:int)->str:
    d=load_data(); since=filter_since(days)
    total=0; by_day:Dict[str,int]={}; cur=None
    for x in d:
        if x.get("type")!="sleep": continue
        t=parse_dt(x["time"])
        if x.get("action")=="sleep_start": cur=t
        elif x.get("action")=="sleep_end" and cur:
            if t>=since:
                s=max(cur,since)
                if t>s:
                    dur=int((t-s).total_seconds()//60); total+=max(0,dur)
                    day_key=day_start(t).strftime("%Y-%m-%d")
                    by_day[day_key]=by_day.get(day_key,0)+max(0,dur)
            cur=None
    lines=[f"📊 Статистика — Сон — {period_label(days)}"]
    if days==1: lines.append(f"😴 Сон сьогодні: {fmt_minutes(total)}")
    else:
        avg=total//days; lines.append(f"😴 Сон за період: {fmt_minutes(total)}"); lines.append(f"📈 Середнє за день: {fmt_minutes(avg)}")
        if by_day:
            lines.append("🗓️ По днях:")
            for day in sorted(by_day.keys()):
                dlabel=parse_dt(day+" 00:00"); lines.append(f"• {dlabel.day} {MONTHS_UA[dlabel.month-1]} — {fmt_minutes(by_day[day])}")
    last_start,last_end=None,None
    for x in d:
        if x.get("type")!="sleep": continue
        if x.get("action")=="sleep_start": last_start=parse_dt(x["time"])
        if x.get("action")=="sleep_end":   last_end=parse_dt(x["time"])
    if last_end and (not last_start or last_end>last_start):
        mins=int((datetime.now()-last_end).total_seconds()//60); lines.append(f"⏱️ Востаннє спав: {fmt_minutes(mins)} тому")
    elif last_start and (not last_end or last_start>last_end):
        mins=int((datetime.now()-last_start).total_seconds()//60); lines.append(f"⏱️ Зараз спить: {fmt_minutes(mins)}")
    return "\n".join(lines)

async def send_poop_photos_for_period(update, ctx, days:int):
    d=load_data(); since=filter_since(days)
    photos=[x for x in d if x.get("type")=="poop" and x.get("photo_file_id") and parse_dt(x["time"])>=since]
    if not photos: return
    batch=[]
    for x in photos:
        cap=f"💩 {fmt_dt_uk(parse_dt(x['time']))}"
        batch.append(InputMediaPhoto(x["photo_file_id"], caption=cap))
        if len(batch)==10:
            await ctx.bot.send_media_group(chat_id=update.effective_chat.id, media=batch); batch=[]
    if batch: await ctx.bot.send_media_group(chat_id=update.effective_chat.id, media=batch)

def build_poop_stats(days:int)->str:
    d=load_data(); since=filter_since(days)
    pp=[x for x in d if x.get("type")=="poop" and parse_dt(x["time"])>=since]
    last=max(pp, key=lambda x:x["time"]) if pp else None
    last_line=fmt_dt_uk(parse_dt(last["time"])) if last else "—"
    return "\n".join([f"📊 Статистика — Какашки — {period_label(days)}",
                      f"💩 Какашки: {len(pp)}", f"⏱️ Останній раз: {last_line}"])

def build_all_stats(days:int)->str:
    d=load_data(); since=filter_since(days)
    eats=[x for x in d if x.get("type")=="eat" and parse_dt(x["time"])>=since]
    total_ml=sum(int(x["amount"]) for x in eats if str(x.get("amount","-")).isdigit())
    total_min=0; cur=None
    for x in d:
        if x.get("type")!="sleep": continue
        t=parse_dt(x["time"])
        if x.get("action")=="sleep_start": cur=t
        elif x.get("action")=="sleep_end" and cur:
            if t>=since:
                s=max(cur,since)
                if t>s: total_min+=int((t-s).total_seconds()//60)
            cur=None
    pp=[x for x in d if x.get("type")=="poop" and parse_dt(x["time"])>=since]
    return "\n".join([f"📊 Статистика — Усе — {period_label(days)}",
                      f"🍽️ Прийомів їжі: {len(eats)} | 🍼 суміш: {total_ml} мл",
                      f"😴 Сон: {fmt_minutes(total_min)}",
                      f"💩 Какашки: {len(pp)}"])

async def stats_start(update, ctx):
    await update.message.reply_text("Що показати?", reply_markup=STATS_CAT_KB); return STATS_CAT
async def stats_cat(update, ctx):
    t=(update.message.text or "").lower()
    if "ї" in t: ctx.user_data["stat_cat"]="eat"
    elif "сон" in t: ctx.user_data["stat_cat"]="sleep"
    elif "кака" in t: ctx.user_data["stat_cat"]="poop"
    else: ctx.user_data["stat_cat"]="all"
    await update.message.reply_text("За який період?", reply_markup=STATS_RANGE_KB); return STATS_RANGE
async def stats_range(update, ctx):
    t=(update.message.text or "").lower()
    days=1 if "сьо" in t else 7 if "7" in t else 30
    cat=ctx.user_data.get("stat_cat","all")
    if cat=="eat": msg=build_eat_stats(days); await update.message.reply_text(msg, reply_markup=MAIN_KB)
    elif cat=="sleep": msg=build_sleep_stats(days); await update.message.reply_text(msg, reply_markup=MAIN_KB)
    elif cat=="poop": msg=build_poop_stats(days); await update.message.reply_text(msg, reply_markup=MAIN_KB); await send_poop_photos_for_period(update, ctx, days)
    else: msg=build_all_stats(days); await update.message.reply_text(msg, reply_markup=MAIN_KB)
    ctx.user_data.clear(); return ConversationHandler.END

# /del + час у відповіді
async def del_cmd(update, ctx):
    eid = resolve_event_id_from_reply(update)
    if not eid:
        await update.message.reply_text("Зроби /del як відповідь на повідомлення (бота або своє) пов'язане з записом.")
        return
    ok = delete_event_by_id(eid)
    await update.message.reply_text("🗑️ Видалено." if ok else "Не знайшов запис для видалення.")
async def reply_time_fix(update, ctx):
    eid = resolve_event_id_from_reply(update)
    if not eid: return
    new_dt = parse_user_time(update.message.text or "")
    if not new_dt: return
    ev = get_event_by_id(eid)
    if not ev or ev.get("type") != "eat": return
    if update_event_time(eid, new_dt):
        await update.message.reply_text(f"⏱️ Оновив час: {fmt_dt_uk(new_dt)}")

async def post_init(app):
    cmds=[BotCommand("start","🏁 Почати"), BotCommand("eat","🍽️ Їжа"), BotCommand("sleep","😴 Сон"),
          BotCommand("poop","💩 Какашки"), BotCommand("stats","📊 Статистика"),
          BotCommand("del","🗑️ Видалити (відповідь)"), BotCommand("menu","🔘 Меню"), BotCommand("cancel","✖️ Скасувати")]
    await app.bot.set_my_commands(cmds)

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_cmd))
    app.add_handler(CommandHandler("cancel", cancel_cmd))
    app.add_handler(CommandHandler("del", del_cmd))
    # /eat
    eat_conv = ConversationHandler(
        entry_points=[CommandHandler("eat", eat_start)],
        states={EAT_CHOICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, eat_choice)],
                EAT_AMOUNT:[MessageHandler(filters.TEXT & ~filters.COMMAND, eat_amount)],
                EAT_FOOD:[MessageHandler(filters.TEXT & ~filters.COMMAND, eat_food)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    ); app.add_handler(eat_conv)
    # /sleep
    sleep_conv = ConversationHandler(
        entry_points=[CommandHandler("sleep", sleep_start)],
        states={SLEEP_CHOICE:[MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_choice)],
                SLEEP_REC_START:[MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_rec_start)],
                SLEEP_REC_END:[MessageHandler(filters.TEXT & ~filters.COMMAND, sleep_rec_end)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    ); app.add_handler(sleep_conv)
    # /poop
    poop_conv = ConversationHandler(
        entry_points=[CommandHandler("poop", poop_start)],
        states={POOP_WAIT:[MessageHandler(filters.PHOTO, poop_wait),
                           MessageHandler(filters.TEXT & ~filters.COMMAND, poop_wait)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    ); app.add_handler(poop_conv)
    # /stats
    stats_conv = ConversationHandler(
        entry_points=[CommandHandler("stats", stats_start)],
        states={STATS_CAT:[MessageHandler(filters.TEXT & ~filters.COMMAND, stats_cat)],
                STATS_RANGE:[MessageHandler(filters.TEXT & ~filters.COMMAND, stats_range)]},
        fallbacks=[CommandHandler("cancel", cancel_cmd)],
    ); app.add_handler(stats_conv)
    # перехоплювач для виправлення часу
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_time_fix))

# ---------- LOCAL POLLING ----------
def run_polling():
    ensure_data_file()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    register_handlers(app)
    print("Bot running (polling)…")
    app.run_polling()

# ---------- FASTAPI WEBHOOK (Render) ----------
from fastapi import FastAPI, Request, HTTPException

app = FastAPI()
_ptb_app: Optional[Application] = None

@app.on_event("startup")
async def _startup():
    global _ptb_app
    ensure_data_file()
    _ptb_app = Application.builder().token(BOT_TOKEN).build()
    register_handlers(_ptb_app)
    await post_init(_ptb_app)
    await _ptb_app.initialize()
    await _ptb_app.start()

    base_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("WEBHOOK_BASE_URL")
    secret = os.getenv("WEBHOOK_SECRET", "secret")
    if base_url:
        await _ptb_app.bot.set_webhook(f"{base_url}/webhook/{secret}")

@app.on_event("shutdown")
async def _shutdown():
    if _ptb_app:
        await _ptb_app.stop()
        await _ptb_app.shutdown()

@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    expected = os.getenv("WEBHOOK_SECRET", "secret")
    if secret != expected:
        raise HTTPException(status_code=403, detail="bad secret")
    data = await request.json()
    update = TGUpdate.de_json(data, _ptb_app.bot)
    await _ptb_app.process_update(update)
    return {"ok": True}

if __name__ == "__main__":
    # локальний запуск
    run_polling()
