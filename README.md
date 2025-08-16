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
