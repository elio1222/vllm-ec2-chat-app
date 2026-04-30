from fastapi import FastAPI, Response, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Integer, String, create_engine, DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker, relationship
from datetime import datetime, timezone, timedelta
from pathlib import Path
import logging
import time
import bcrypt
import secrets
import hashlib
import os
import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).with_name(".env"))

MODEL_NAME = os.getenv("MODEL_NAME", "HuggingFaceTB/SmolLM2-135M-Instruct")
MODEL_API_URL = os.getenv("MODEL_API_URL", "")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
MODEL_REQUEST_TIMEOUT_SECONDS = int(os.getenv("MODEL_REQUEST_TIMEOUT_SECONDS", "30"))
MODEL_CONTEXT_MESSAGE_LIMIT = int(os.getenv("MODEL_CONTEXT_MESSAGE_LIMIT", "5"))

logging.basicConfig(
    filename="app.log",
    filemode="w",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] - %(message)s",
)

logger = logging.getLogger(__name__)

def hash_password(plain_password: str) -> str:
    bytes = plain_password.encode("utf-8")
    salt = bcrypt.gensalt()
    hash = bcrypt.hashpw(bytes, salt)
    return hash

def verify_password(plain_password: str, stored_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), stored_hash)

def hash_session_token(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()

def revoke_session(session_token: str) -> None:
    session_hash = hash_session_token(session_token=session_token)
    with Session() as session:
        session_obj = session.query(Sessions).filter(Sessions.session_hash == session_hash).first()
        if session_obj is None:
            return

        session_obj.revoked_at = datetime.now(timezone.utc)
        session.commit()

def load_user_from_valid_session(session_token: str):
    with Session() as session:
        session_hash = hash_session_token(session_token=session_token)
        session_obj = (
            session.query(Sessions)
            .filter(Sessions.session_hash == session_hash)
            .filter(Sessions.revoked_at.is_(None))
            .filter(Sessions.expires_at > datetime.now(timezone.utc))
            .first()
        )
        if session_obj is None:
            return None
        
        return session_obj.user

def get_current_user(request: Request) -> "Users":
    session_token = request.cookies.get("session_id")
    if not session_token:
        raise HTTPException(status_code=401)
    user = load_user_from_valid_session(session_token=session_token)
    if user is None:
        raise HTTPException(status_code=401)
    return user

def generate_vllm_model_reply(messages: list[dict[str, str]]) -> str:
    if not MODEL_API_URL:
        raise HTTPException(
            status_code=500,
            detail="MODEL_API_URL is not configured.",
        )

    if not MODEL_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="MODEL_API_KEY is not configured.",
        )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {MODEL_API_KEY}",
    }

    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "max_tokens": 100,
        "temperature": 0.7,
    }

    try:
        response = requests.post(
            MODEL_API_URL,
            headers=headers,
            json=payload,
            timeout=MODEL_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        logger.exception("Model request failed")
        raise HTTPException(
            status_code=502,
            detail="Could not reach the model backend.",
        ) from exc
    except ValueError as exc:
        logger.exception("Model backend returned invalid JSON")
        raise HTTPException(
            status_code=502,
            detail="Model backend returned an invalid response.",
        ) from exc

    return data["choices"][0]["message"]["content"]


def serialize_chat(chat: "Chats") -> dict[str, object]:
    return {
        "id": chat.id,
        "role": chat.role,
        "content": chat.content,
        "created_at": chat.created_at,
    }


def build_conversation_messages(
    existing_chats: list["Chats"],
    latest_user_prompt: str,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": chat.role,
            "content": chat.content,
        }
        for chat in existing_chats
        if chat.role in {"user", "assistant"}
    ]
    if MODEL_CONTEXT_MESSAGE_LIMIT > 0:
        messages = messages[-MODEL_CONTEXT_MESSAGE_LIMIT:]
    messages.append({"role": "user", "content": latest_user_prompt})
    return messages

engine = create_engine(url="sqlite:///my_db.db", connect_args={"autocommit": False})

class Base(DeclarativeBase):
    pass

class Users(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    sessions: Mapped[list["Sessions"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    chats: Mapped[list["Chats"]] = relationship(back_populates="user", cascade="all, delete-orphan")

class Sessions(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    session_hash: Mapped[str] = mapped_column(String, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["Users"] = relationship(back_populates="sessions")

class Chats(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_Id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime)

    user: Mapped["Users"] = relationship(back_populates="chats")

Base.metadata.create_all(bind=engine)
Session = sessionmaker(bind=engine)

class UserCreate(BaseModel):
    email: str
    password: str

class ChatPrompt(BaseModel):
    prompt: str


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:3000",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    started_at = time.perf_counter()
    logger.info(
        "HTTP request started method=%s path=%s client=%s",
        request.method,
        request.url.path,
        request.client.host if request.client else "unknown",
    )

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - started_at) * 1000
        logger.exception(
            "HTTP request failed method=%s path=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

    duration_ms = (time.perf_counter() - started_at) * 1000
    logger.info(
        "HTTP request completed method=%s path=%s status=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

@app.get("/health")
async def get_health_check():
    return {"status": "ok"}

@app.get("/me")
async def get_me(user: "Users" = Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
    }

@app.post("/register")
async def register(user: UserCreate):

    with Session() as session:
        user_email = session.query(Users).filter(Users.email == user.email).first()
        if user_email:
            raise HTTPException(status_code=400, detail="User already registered")
        
        password_hash = hash_password(user.password)
        new_user = Users(email=user.email, password_hash=password_hash)

        session.add(new_user)
        session.commit()

        return {"message": f"User {new_user.id} registered successfully"}

@app.post("/index")
async def login_user(user: UserCreate, response: Response):
    with Session() as session:
        requesting_user = session.query(Users).filter(Users.email == user.email).first()
        if requesting_user is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        if not verify_password(user.password, requesting_user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")
        
        session_id = secrets.token_urlsafe(32)
        session_hash = hash_session_token(session_token=session_id)

        new_session_record = Sessions(user_id=requesting_user.id, session_hash=session_hash, expires_at= datetime.now(timezone.utc) + timedelta(hours=1))
        session.add(new_session_record)
        session.commit()

        response.set_cookie(
            key="session_id",
            value=session_id,
            httponly=True,
            max_age=3600,
            samesite="lax",
            secure=False
        )
        return {"message": f"logged in as {requesting_user.email}"}
    
@app.post("/logout")
async def logout(request: Request):
    session_token = request.cookies.get("session_id")
    user = load_user_from_valid_session(session_token=session_token) if session_token else None

    if user is None:
        response = Response(
            content='{"message":"No active session. You are already logged out."}',
            media_type="application/json",
        )
        response.delete_cookie("session_id", path="/")
        return response

    revoke_session(session_token=session_token)
    response = Response(
        content=f'{{"message":"Successfully logged out {user.email}"}}',
        media_type="application/json",
    )
    response.delete_cookie("session_id", path="/")
    return response
    
@app.get("/chats")
async def get_chat_history(User = Depends(get_current_user)):
    with Session() as session:
        chats = (
            session.query(Chats)
            .filter(Chats.user_Id == User.id)
            .order_by(Chats.created_at.asc())
            .all()
        )

        return {
            "messages": [serialize_chat(chat) for chat in chats]
        }

@app.post("/chat")
async def create_chat(prompt: ChatPrompt, User = Depends(get_current_user)):
    cleaned_prompt = prompt.prompt.strip()
    if not cleaned_prompt:
        raise HTTPException(status_code=400, detail="Prompt cannot be empty.")

    with Session() as session:
        existing_chats = (
            session.query(Chats)
            .filter(Chats.user_Id == User.id)
            .order_by(Chats.created_at.asc())
            .all()
        )
        conversation_messages = build_conversation_messages(existing_chats, cleaned_prompt)
        assistant_reply = generate_vllm_model_reply(conversation_messages)
        created_at = datetime.now(timezone.utc)

        user_message = Chats(
            user_Id=User.id,
            role="user",
            content=cleaned_prompt,
            created_at=created_at,
        )
        assistant_message = Chats(
            user_Id=User.id,
            role="assistant",
            content=assistant_reply,
            created_at=datetime.now(timezone.utc),
        )

        session.add(user_message)
        session.add(assistant_message)
        session.commit()

        return {
            "messages": [
                serialize_chat(user_message),
                serialize_chat(assistant_message),
            ]
        }
    
# testing purposes
# @app.get("/all-sessions")
# async def get_all_sessions(User = Depends(get_current_user)):

#     with Session() as session:
#         users = session.query(Users).all()

#         emails = []
#         session_hashes = []

#         for u in users:
#             emails.append(u.email)
#             session_hashes.append(u.sessions)

#         return {
#             "logged_in_user": User,
#             "emails": emails,
#             "sessions": session_hashes
#         }

# this was directly accessible to the public, which needs to be fixed for admin only purposes
# @app.get("/users")
# async def get_all_users():
#     with Session() as session:
#         users = session.query(Users).options(joinedload(Users.sessions)).all()
#         result = []
#         for user in users:
#             result.append({
#                 "id": user.id,
#                 "email": user.email,
#                 "sessions": [
#                     {"session_hash": s.session_hash, "expires_at": s.expires_at, "revoked_at": s.revoked_at} 
#                     for s in user.sessions
#                 ]
#             })

#         return {"users": result}
