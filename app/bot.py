import time
from datetime import datetime, timedelta
from telebot import TeleBot
from telebot.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    Message,
)
from bson import ObjectId

from .config import get_config
from .db import init_db, get_db
from .repositories.settings import SettingsRepository
from .repositories.users import UsersRepository
from .repositories.channels import ChannelsRepository
from .repositories.payments import PaymentsRepository
from .repositories.schedules import SchedulesRepository
from .services.gemini import generate_questions
from .services.quota import (
    has_quota,
    can_submit_note_now,
    update_last_note_time,
    reset_notes_if_new_day,
    increment_quota,
    increase_total_notes,
)
from .services.scheduler import QuizScheduler
from .utils import is_subscribed, home_keyboard


cfg = get_config()
init_db()
db = get_db()
settings_repo = SettingsRepository(db)
users_repo = UsersRepository(db)
channels_repo = ChannelsRepository(db)
payments_repo = PaymentsRepository(db)
schedules_repo = SchedulesRepository(db)

bot = TeleBot(cfg.bot_token)
scheduler = QuizScheduler(db, bot)
scheduler.start()

pending_notes: dict[int, dict] = {}
pending_subscriptions: dict[int, dict] = {}


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("📝 Generate", callback_data="generate"),
        InlineKeyboardButton("👤 Profile", callback_data="profile"),
    )
    kb.row(
        InlineKeyboardButton("📢 My Channels", callback_data="channels"),
        InlineKeyboardButton("⏰ Schedule", callback_data="schedule_menu"),
    )
    kb.row(
        InlineKeyboardButton("ℹ️ About", callback_data="about"),
        InlineKeyboardButton("🆘 FAQs", callback_data="faq"),
    )
    kb.row(
        InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
        InlineKeyboardButton("👨‍💻 Developer", url="https://t.me/Bek_i"),
    )
    return kb


@bot.message_handler(commands=["start"]) 
def handle_start(message: Message):
    user_id = message.chat.id
    username = message.from_user.username or "No"

    users_repo.upsert_user(user_id, username)

    if cfg.maintenance_mode:
        bot.send_message(user_id, "The bot is currently under maintenance. Please try again later.")
        return

    if not is_subscribed(bot, user_id):
        channels_txt = "\n".join(cfg.force_channels) if cfg.force_channels else ""
        bot.send_message(user_id, f"Please join required channels to use the bot:\n{channels_txt}")
        return

    text = (
        "<b>Welcome to SmartQuiz Bot!</b>\n\n"
        "Turn your notes into interactive questions effortlessly.\n\n"
        "✨ Features:\n"
        "- Convert study notes into quizzes\n"
        "- Choose between text or quiz mode\n"
        "- Deliver to PM or your channel\n"
        "- Configure delay and schedule delivery\n\n"
        "Your support makes this bot better!"
    )
    bot.send_message(user_id, text, parse_mode="HTML", reply_markup=main_menu())


@bot.callback_query_handler(func=lambda call: call.data == "profile")
def handle_profile(call: CallbackQuery):
    user_id = call.from_user.id
    user = users_repo.get(user_id)
    if not user:
        bot.answer_callback_query(call.id, "User not found. Press /start")
        return

    premium_status = "Premium" if user.get("type") == "premium" else "Free"
    premium_since = user.get("premium_since")
    premium_since_str = premium_since.strftime("%Y-%m-%d") if premium_since else "N/A"

    text = (
        f"<b>User Profile</b>\n"
        f"<b>Name:</b> {call.from_user.full_name} <b>ID:</b> <code>{user_id}</code>\n"
        f"<b>Registered At:</b> {user.get('registered_at','')}\n"
        f"<b>Status:</b> {premium_status}\n"
        f"<b>Premium Since:</b> {premium_since_str}\n"
        f"<b>Last Used:</b> {user.get('last_note_time','Never')}\n"
        f"<b>Notes Today:</b> {user.get('notes_today',0)}\n"
        f"<b>Total Notes:</b> {user.get('total_notes',0)}\n"
        f"<b>Question Type:</b> {user.get('default_question_type','text').capitalize()}\n"
        f"<b>Questions Per Note:</b> {user.get('questions_per_note',5)}\n"
    )
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, text, parse_mode="HTML", reply_markup=home_keyboard())


# Channels Management
@bot.callback_query_handler(func=lambda call: call.data == "channels")
def handle_channels(call: CallbackQuery):
    user_id = call.from_user.id
    user_channels = channels_repo.list_channels(user_id)
    kb = InlineKeyboardMarkup(row_width=1)
    for ch in user_channels:
        label = f"{ch.get('title','Channel')} ({ch.get('username') or ch.get('chat_id')})"
        kb.add(InlineKeyboardButton(f"❌ Remove {label}", callback_data=f"removech_{ch['chat_id']}"))
    kb.add(InlineKeyboardButton("➕ Add a Channel", callback_data="add_channel_info"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))

    text = (
        "Manage your channels.\n\n"
        "- Add channels where you are admin/owner and where the bot is also admin.\n"
        "- You can later select any of them as quiz targets."
    )
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(user_id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "add_channel_info")
def handle_add_channel_info(call: CallbackQuery):
    user_id = call.from_user.id
    text = (
        "To add a channel:\n"
        "1) Add this bot as an admin in your channel.\n"
        "2) Forward a message from that channel here OR send the channel @username."
    )
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, text, reply_markup=home_keyboard())


@bot.message_handler(func=lambda m: m.forward_from_chat is not None and m.forward_from_chat.type == "channel")
def handle_channel_forward(message: Message):
    chat = message.forward_from_chat
    chat_id = chat.id
    title = chat.title or "Channel"
    username = chat.username
    user_id = message.from_user.id
    try:
        member = bot.get_chat_member(chat_id, user_id)
        if member.status not in ["administrator", "creator"]:
            bot.reply_to(message, "You must be admin of that channel.")
            return
        bot_member = bot.get_chat_member(chat_id, bot.get_me().id)
        can_post = bot_member.status in ["administrator", "creator"]
        channels_repo.add_channel(user_id, chat_id, title, username, can_post)
        bot.reply_to(message, f"Channel saved: {title}")
    except Exception as e:
        bot.reply_to(message, f"Failed to verify channel: {e}")


@bot.message_handler(func=lambda m: bool(m.text) and m.text.startswith("@"))
def handle_channel_username(message: Message):
    # Attempt to resolve channel by username
    user_id = message.from_user.id
    try:
        chat = bot.get_chat(message.text)
        if not chat or chat.type != "channel":
            bot.reply_to(message, "Not a valid channel username.")
            return
        member = bot.get_chat_member(chat.id, user_id)
        if member.status not in ["administrator", "creator"]:
            bot.reply_to(message, "You must be admin of that channel.")
            return
        bot_member = bot.get_chat_member(chat.id, bot.get_me().id)
        can_post = bot_member.status in ["administrator", "creator"]
        channels_repo.add_channel(user_id, chat.id, chat.title or "Channel", chat.username, can_post)
        bot.reply_to(message, f"Channel saved: {chat.title}")
    except Exception as e:
        bot.reply_to(message, f"Failed to add channel: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("removech_"))
def handle_remove_channel(call: CallbackQuery):
    user_id = call.from_user.id
    chat_id = int(call.data.split("_")[1])
    channels_repo.remove_channel(user_id, chat_id)
    bot.answer_callback_query(call.id, "Removed")
    handle_channels(call)


# Generate flow
@bot.callback_query_handler(func=lambda call: call.data == "generate")
def handle_generate(call: CallbackQuery):
    user_id = call.from_user.id
    users_repo.reset_notes_if_new_day(user_id)

    if not is_subscribed(bot, user_id):
        bot.answer_callback_query(call.id, "Please join required channels first.")
        bot.send_message(user_id, "Please Join All Our Channels!\n/start - To start again")
        return

    if not has_quota(db, user_id):
        bot.answer_callback_query(call.id, "You have reached your note limit for today.")
        return

    if not can_submit_note_now(db, user_id, cooldown_seconds=10):
        bot.answer_callback_query(call.id, "Please wait a few seconds before sending another note.")
        return

    pending_notes[user_id] = {"stage": "await_note"}
    bot.answer_callback_query(call.id)
    bot.send_message(
        user_id,
        "Send your note now as a single text message.\nThen you'll choose: destination (PM or channel), delay between questions (5s-60s), and optional scheduling.",
        reply_markup=home_keyboard(),
    )


@bot.message_handler(func=lambda m: m.from_user and m.from_user.id in pending_notes and pending_notes[m.from_user.id].get("stage") == "await_note")
def handle_note_submission(message: Message):
    user_id = message.from_user.id
    note = message.text or ""
    pending_notes[user_id]["note"] = note

    # Destination choices: PM or one of user's channels
    user_channels = channels_repo.list_channels(user_id)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📥 Send to PM", callback_data="dst_pm"))
    for ch in user_channels:
        label = f"{ch.get('title','Channel')} ({ch.get('username') or ch.get('chat_id')})"
        kb.add(InlineKeyboardButton(f"📣 {label}", callback_data=f"dst_ch_{ch['chat_id']}"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))

    pending_notes[user_id]["stage"] = "choose_destination"
    bot.send_message(user_id, "Choose where to send the quiz:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dst_"))
def handle_destination_selection(call: CallbackQuery):
    user_id = call.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        bot.answer_callback_query(call.id, "Start again with Generate")
        return

    if call.data == "dst_pm":
        state["target_chat_id"] = user_id
        state["target_label"] = "PM"
    elif call.data.startswith("dst_ch_"):
        chat_id = int(call.data.split("_")[2])
        ch = channels_repo.get_channel(user_id, chat_id)
        if not ch:
            bot.answer_callback_query(call.id, "Channel not found")
            return
        state["target_chat_id"] = chat_id
        state["target_label"] = ch.get("title") or str(chat_id)
    else:
        bot.answer_callback_query(call.id)
        return

    # Ask delay (5-60 seconds)
    kb = InlineKeyboardMarkup(row_width=5)
    for s in [5, 10, 15, 20, 30, 45, 60]:
        kb.add(InlineKeyboardButton(f"{s}s", callback_data=f"delay_{s}"))
    kb.add(InlineKeyboardButton("Custom", callback_data="delay_custom"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))

    state["stage"] = "choose_delay"
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, "Choose delay between questions:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delay_"))
def handle_delay(call: CallbackQuery):
    user_id = call.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        bot.answer_callback_query(call.id)
        return

    if call.data == "delay_custom":
        state["stage"] = "await_custom_delay"
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "Send a delay in seconds (5-60):")
        return

    delay = int(call.data.split("_")[1])
    delay = max(5, min(60, delay))
    state["delay_seconds"] = delay

    # Ask schedule or send now
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("Send Now", callback_data="sendnow"))
    kb.add(InlineKeyboardButton("Schedule", callback_data="doschedule"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))

    state["stage"] = "confirm_send_or_schedule"
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, f"Delay set to {delay}s. Send now or schedule?", reply_markup=kb)


@bot.message_handler(func=lambda m: m.from_user and m.from_user.id in pending_notes and pending_notes[m.from_user.id].get("stage") == "await_custom_delay")
def handle_custom_delay(message: Message):
    user_id = message.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        return
    try:
        delay = int(message.text.strip())
        if delay < 5 or delay > 60:
            raise ValueError
        state["delay_seconds"] = delay
    except Exception:
        bot.reply_to(message, "Invalid delay. Send a number 5-60.")
        return

    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("Send Now", callback_data="sendnow"))
    kb.add(InlineKeyboardButton("Schedule", callback_data="doschedule"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))

    state["stage"] = "confirm_send_or_schedule"
    bot.send_message(user_id, f"Delay set to {state['delay_seconds']}s. Send now or schedule?", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "sendnow")
def send_now(call: CallbackQuery):
    user_id = call.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        bot.answer_callback_query(call.id)
        return

    note = state.get("note", "")
    target = state.get("target_chat_id", user_id)
    delay = int(state.get("delay_seconds", 5))

    user = users_repo.get(user_id) or {}
    num_questions = int(user.get("questions_per_note", 5))
    q_format = (user.get("default_question_type") or cfg.question_type_default).lower()

    if not has_quota(db, user_id):
        bot.answer_callback_query(call.id, "Daily quota reached")
        return

    if not can_submit_note_now(db, user_id, cooldown_seconds=10):
        bot.answer_callback_query(call.id, "Wait a few seconds before next note")
        return

    update_last_note_time(db, user_id)
    bot.answer_callback_query(call.id)

    generating = bot.send_message(user_id, "Generating...")
    try:
        questions = generate_questions(note, num_questions)
        if not questions:
            bot.send_message(user_id, "An error occurred while generating questions. Please try again.")
            return
        bot.delete_message(user_id, generating.id)
        letters = ["A", "B", "C", "D"]
        for idx, q in enumerate(questions, start=1):
            time.sleep(delay)
            if q_format == "text":
                text = f"{idx}. {q['question']}\n"
                for i, c in enumerate(q["choices"]):
                    prefix = letters[i] if i < len(letters) else str(i + 1)
                    text += f"{prefix}. {c}\n"
                text += f"\n<b>Correct Answer</b>: {letters[q['answer_index']]} - {q['choices'][q['answer_index']]}"
                explanation = (q.get("explanation") or "")
                if explanation:
                    text += f"\n<b>Explanation:</b> {explanation[:195]}"
                bot.send_message(target, text, parse_mode="HTML")
            else:
                bot.send_poll(
                    target,
                    q["question"],
                    q["choices"],
                    type="quiz",
                    correct_option_id=q["answer_index"],
                    explanation=(q.get("explanation") or "")[:195],
                )
        increment_quota(db, user_id)
        increase_total_notes(db, user_id)
        bot.send_message(user_id, "✅ Questions generated successfully.", reply_markup=home_keyboard())
    except Exception as e:
        bot.send_message(user_id, f"Something went wrong: {e}")
    finally:
        pending_notes.pop(user_id, None)


@bot.callback_query_handler(func=lambda call: call.data == "doschedule")
def do_schedule(call: CallbackQuery):
    user_id = call.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        bot.answer_callback_query(call.id)
        return
    state["stage"] = "await_schedule_time"
    bot.answer_callback_query(call.id)
    bot.send_message(user_id, "Send schedule time in format YYYY-MM-DD HH:MM (UTC). Example: 2025-01-01 12:30")


@bot.message_handler(func=lambda m: m.from_user and m.from_user.id in pending_notes and pending_notes[m.from_user.id].get("stage") == "await_schedule_time")
def handle_schedule_time(message: Message):
    user_id = message.from_user.id
    state = pending_notes.get(user_id)
    if not state:
        return
    try:
        dt = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        bot.reply_to(message, "Invalid format. Use YYYY-MM-DD HH:MM (UTC)")
        return

    # Save schedule
    user = users_repo.get(user_id) or {}
    num_questions = int(user.get("questions_per_note", 5))
    q_format = (user.get("default_question_type") or cfg.question_type_default).lower()

    schedules_repo.create(
        {
            "user_id": user_id,
            "target_chat_id": state.get("target_chat_id", user_id),
            "target_label": state.get("target_label", "PM"),
            "note": state.get("note", ""),
            "num_questions": num_questions,
            "question_type": q_format,
            "delay_seconds": int(state.get("delay_seconds", 5)),
            "scheduled_at": dt,
            "status": "pending",
            "created_at": datetime.utcnow(),
        }
    )
    pending_notes.pop(user_id, None)
    bot.send_message(user_id, "📅 Scheduled successfully.", reply_markup=home_keyboard())


# Settings
@bot.callback_query_handler(func=lambda call: call.data == "settings")
def handle_settings(call: CallbackQuery):
    user_id = call.from_user.id
    user = users_repo.get(user_id)
    if not user:
        bot.answer_callback_query(call.id, "User not found.")
        return

    question_type = user.get("default_question_type", "text")
    questions_per_note = user.get("questions_per_note", 5)
    msg = f"**Settings**\n• Question Type: `{question_type}`\n• Questions per Note: `{questions_per_note}`"

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("Change Question Type", callback_data="change_qtype"),
        InlineKeyboardButton("Change Questions/Note", callback_data="change_qpernote"),
        InlineKeyboardButton("Back to Home", callback_data="home"),
    )

    try:
        bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        bot.send_message(user_id, msg, parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "change_qtype")
def change_question_type(call: CallbackQuery):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Text", callback_data="set_qtype_text"),
        InlineKeyboardButton("Poll", callback_data="set_qtype_poll"),
        InlineKeyboardButton("Back", callback_data="settings"),
    )
    try:
        bot.edit_message_text("Choose a question type:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, "Choose a question type:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_qtype_"))
def set_question_type(call: CallbackQuery):
    user_id = call.from_user.id
    new_type = call.data.split("_")[-1]
    users_repo.set_default_qtype(user_id, new_type)
    bot.answer_callback_query(call.id, f"Question type updated to {new_type.capitalize()}")
    handle_settings(call)


@bot.callback_query_handler(func=lambda call: call.data == "change_qpernote")
def change_questions_per_note(call: CallbackQuery):
    markup = InlineKeyboardMarkup(row_width=5)
    buttons = [InlineKeyboardButton(str(i), callback_data=f"set_qpernote_{i}") for i in range(1, 11)]
    for i in range(0, len(buttons), 5):
        markup.row(*buttons[i : i + 5])
    markup.add(InlineKeyboardButton("Back", callback_data="settings"))
    try:
        bot.edit_message_text("Choose number of questions per note:", call.message.chat.id, call.message.message_id, reply_markup=markup)
    except Exception:
        bot.send_message(call.message.chat.id, "Choose number of questions per note:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("set_qpernote_"))
def set_questions_per_note(call: CallbackQuery):
    user_id = call.from_user.id
    new_value = int(call.data.split("_")[-1])
    max_limit = 10
    if new_value > max_limit:
        bot.answer_callback_query(call.id, f"Limit is {max_limit} for your plan.")
        return
    users_repo.set_questions_per_note(user_id, new_value)
    bot.answer_callback_query(call.id, f"Updated to {new_value} questions per note.")
    handle_settings(call)


@bot.callback_query_handler(func=lambda call: call.data == "home")
def handle_home(call: CallbackQuery):
    user_id = call.from_user.id
    pending_notes.pop(user_id, None)
    handle_start(call.message)


@bot.callback_query_handler(func=lambda call: call.data == "faq")
def handle_faq(call: CallbackQuery):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    text = (
        "📚 Frequently Asked Questions (FAQs)\n\n"
        "1) Why limits? Resource management.\n"
        "2) 24/7? Use a VPS for always-on.\n"
        "3) Why slow? Free hosting limits.\n"
        "4) Updates? Yes, more features coming.\n"
        "5) Note size? Up to Telegram limits (~4096 chars).\n"
        "6) AI? Gemini by Google.\n"
        "7) Poll mode? Settings → Question Type → Poll.\n"
    )
    bot.send_message(call.message.chat.id, text, reply_markup=home_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "about")
def handle_about(call: CallbackQuery):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    text = (
        "ℹ️ <b>About the Bot</b>\n\n"
        "🤖 Version: <b><i>v2.0.0</i></b>\n"
        "📚 Converts your text notes into MCQ quizzes.\n"
        "🎓 For students, educators, creators.\n\n"
        "🛠 New: MongoDB, user channels, delay, scheduling.\n"
    )
    bot.send_message(call.message.chat.id, text, parse_mode="HTML", reply_markup=home_keyboard())


# Simple payment flow (pending → accept/decline)
@bot.callback_query_handler(func=lambda call: call.data == "subscribe_premium")
def subscribe_premium_start(call: CallbackQuery):
    user_id = call.from_user.id
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("Telebirr", callback_data="pay_telebirr"),
        InlineKeyboardButton("CBE", callback_data="pay_cbe"),
    )
    kb.row(
        InlineKeyboardButton("USDT TRC-20", callback_data="pay_trc"),
        InlineKeyboardButton("USDT ERC-20", callback_data="pay_erc"),
    )
    kb.row(InlineKeyboardButton("🔙 Home", callback_data="home"))
    amount = cfg.premium_price
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, f"Premium is {amount} ETB or ~0.5 USDT per month. Choose payment method:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def choose_payment_method(call: CallbackQuery):
    user_id = call.from_user.id
    method = call.data.split("_")[1]
    pending_subscriptions[user_id] = {"method": method}

    if method == "telebirr":
        numbers = cfg.telebirr_numbers
    elif method == "cbe":
        numbers = cfg.cbe_numbers
    else:
        numbers = ["TRC20 Wallet: <provide>", "ERC20 Wallet: <provide>"]

    amount = cfg.premium_price
    number_list = "\n".join(numbers)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, f"Send {amount} ETB or 0.5 USDT to:\n{number_list}\nAfter payment send a screenshot.")
    bot.send_message(user_id, "Send the transaction screenshot now (as a photo).", reply_markup=home_keyboard())


@bot.message_handler(content_types=["photo"]) 
def handle_payment_photo(message: Message):
    user_id = message.from_user.id
    if user_id not in pending_subscriptions:
        return
    pending_subscriptions[user_id]["screenshot"] = message.photo[-1].file_id
    kb = InlineKeyboardMarkup()
    kb.row(InlineKeyboardButton("Done", callback_data="confirm_payment"), InlineKeyboardButton("Cancel", callback_data="cancel_payment"))
    bot.send_message(user_id, "Submit this payment?", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "cancel_payment")
def cancel_payment(call: CallbackQuery):
    user_id = call.from_user.id
    pending_subscriptions.pop(user_id, None)
    bot.delete_message(call.message.chat.id, call.message.message_id)
    bot.send_message(user_id, "Payment process canceled.", reply_markup=home_keyboard())


@bot.callback_query_handler(func=lambda call: call.data == "confirm_payment")
def confirm_payment(call: CallbackQuery):
    user_id = call.from_user.id
    info = pending_subscriptions.get(user_id)
    if not info:
        return

    method = info["method"]
    screenshot_id = info.get("screenshot")
    if not screenshot_id:
        bot.send_message(user_id, "Please send a photo of your payment.")
        return

    amount = cfg.premium_price
    payments_repo.insert(user_id, method, amount, screenshot_id)

    # Notify admins: for demo, anyone with role admin in DB
    admins = [u.get("id") for u in db["users"].find({"role": "admin"})]
    for admin_id in admins:
        kb = InlineKeyboardMarkup()
        kb.row(
            InlineKeyboardButton("Accept", callback_data=f"acceptpay_{user_id}"),
            InlineKeyboardButton("Decline", callback_data=f"declinepay_{user_id}"),
        )
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.send_photo(admin_id, screenshot_id, caption=f"New Payment\nUser: {user_id}\nMethod: {method}\nAmount: {amount}", reply_markup=kb)

    bot.send_message(user_id, "Payment submitted for review. You'll be notified soon.", reply_markup=home_keyboard())
    pending_subscriptions.pop(user_id, None)


@bot.callback_query_handler(func=lambda call: call.data.startswith("acceptpay_"))
def accept_payment(call: CallbackQuery):
    # Only admins should accept
    admin_user = users_repo.get(call.from_user.id)
    if (admin_user or {}).get("role") != "admin":
        return
    user_id = int(call.data.split("_")[1])
    users_repo.set_premium(user_id, 30)
    payments_repo.update_status(user_id, "accepted")
    bot.send_message(user_id, f"Your premium subscription for {cfg.premium_price} Birr has been approved!")
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    if cfg.payment_channel:
        try:
            bot.send_message(cfg.payment_channel, f"New Premium Subscription\nUser ID: {user_id}\nAmount Paid: {cfg.premium_price}\nDate: {now}")
        except Exception:
            pass


@bot.callback_query_handler(func=lambda call: call.data.startswith("declinepay_"))
def decline_payment(call: CallbackQuery):
    admin_user = users_repo.get(call.from_user.id)
    if (admin_user or {}).get("role") != "admin":
        return
    user_id = int(call.data.split("_")[1])
    payments_repo.update_status(user_id, "declined")
    bot.send_message(user_id, "Your premium request was declined. If this is a mistake, please try again.")


# FAQ/About handlers already added

@bot.callback_query_handler(func=lambda call: call.data == "schedule_menu")
def handle_schedule_menu(call: CallbackQuery):
    user_id = call.from_user.id
    items = schedules_repo.get_user_schedules(user_id)
    if not items:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))
        bot.answer_callback_query(call.id)
        bot.send_message(user_id, "No schedules yet. Use Generate → pick destination → Schedule.", reply_markup=kb)
        return
    kb = InlineKeyboardMarkup(row_width=1)
    for s in items:
        sched_id = str(s.get("_id"))
        when = s.get("scheduled_at")
        label = f"{s.get('target_label','PM')} @ {when} ({s.get('status','pending')})"
        kb.add(InlineKeyboardButton(f"❌ Delete {label}", callback_data=f"delsch_{sched_id}"))
    kb.add(InlineKeyboardButton("🔙 Home", callback_data="home"))
    try:
        bot.edit_message_text("Your schedules:", call.message.chat.id, call.message.message_id, reply_markup=kb)
    except Exception:
        bot.send_message(user_id, "Your schedules:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.startswith("delsch_"))
def handle_delete_schedule(call: CallbackQuery):
    user_id = call.from_user.id
    sched_id = call.data.split("_")[1]
    ok = schedules_repo.delete(user_id, sched_id)
    bot.answer_callback_query(call.id, "Deleted" if ok else "Not found")
    handle_schedule_menu(call)


print("Bot running...")
if __name__ == "__main__":
    bot.infinity_polling()