import asyncio
from sqlalchemy import select
from app.db.session import engine, AsyncSessionLocal
from app.db.models import User, ChatSession, ChatMessage

async def test_models():
    async with AsyncSessionLocal() as session:
        # Test users query
        user_res = await session.execute(select(User).limit(1))
        user = user_res.scalars().first()
        print(f"Users table accessible. Sample user: {user.email if user else 'No users yet'}")

        # Test sessions query
        session_res = await session.execute(select(ChatSession).limit(1))
        sess = session_res.scalars().first()
        print(f"Chat sessions table accessible. Sample session title: {sess.title if sess else 'No sessions yet'}")

        # Test messages query
        msg_res = await session.execute(select(ChatMessage).limit(1))
        msg = msg_res.scalars().first()
        print(f"Chat messages table accessible. Sample message: {msg.role if msg else 'No messages yet'}")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(test_models())