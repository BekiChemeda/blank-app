# SmartQuiz Bot (MongoDB)

Telegram bot that turns notes into quizzes, supports user-managed channels, delivery delays, and scheduling with MongoDB persistence.

## Quick start

1. Copy env and fill values
```bash
cp .env.example .env
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Run
```bash
python -m app.bot
```

## Features
- Gemini-powered quiz generation
- User-managed channels (verify bot as admin)
- Choose target: PM or any added channel
- Delay between questions (5s - 60s)
- Schedule quiz delivery (APScheduler + MongoDB)
- Premium, quotas, force-subscription, payments (basic flow)

## Admin Guide

Grant yourself admin (DB must contain your user with role=admin):
- Ask an existing admin to run: `/addadmin <your_user_id>`

Then you can manage runtime settings stored in MongoDB:

- Force subscription
  - Enable/disable: `/setforcesub on` or `/setforcesub off`
  - Set required channels: `/setforcechannels @ChannelA @ChannelB`

- Premium settings
  - Set price (ETB): `/setpremiumprice 40`
  - Set payment channel (where approvals are announced): `/setpaymentchannel @PaymentsChannel`
  - Add payment receivers:
    - Telebirr: `/addtelebirr 0912345678`
    - CBE: `/addcbe 1000123456`

- Quotas
  - Max notes per day: `/setmaxnotes regular 5` or `/setmaxnotes premium 10`
  - Max questions per note: `/setmaxquestions regular 5` or `/setmaxquestions premium 10`

- Maintenance mode
  - `/maintenancemode on` or `/maintenancemode off`

- Admin management
  - Promote: `/addadmin <user_id>`
  - Demote: `/removeadmin <user_id>`

Notes:
- These commands update the `settings` collection; the bot reads DB values at runtime (env vars are fallbacks).
- Keep secrets like `BOT_TOKEN`, `GEMINI_API_KEY`, and DB credentials in `.env`.
- For channels: ensure both the user and the bot are admins of the target channel.
