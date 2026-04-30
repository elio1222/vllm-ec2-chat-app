# CSC410 Assignment 5

This project is a small full-stack chat application with email/password authentication, cookie-based sessions, persistent chat history, and a model-backed assistant reply flow.

The codebase under `/code` contains three main pieces:

- `app/`: a FastAPI backend with SQLite, SQLAlchemy models, authentication, session management, and chat endpoints
- `frontend/`: a static HTML/CSS/JavaScript client for register, login, and chat
- `nginx/`: reverse proxy configuration that serves the frontend and forwards `/api/*` to FastAPI

## Features

- User registration with email and password
- User login with an `HttpOnly` session cookie
- Session validation through `/me`
- Logout with server-side session revocation
- Stored chat history per user
- Conversation context passed to a model API when generating replies
- Health check endpoint for service monitoring

## Architecture

### Backend

The backend is defined in `code/app/main.py` and uses:

- `FastAPI` for the HTTP API
- `SQLAlchemy` ORM with a local SQLite database file `my_db.db`
- `bcrypt` for password hashing
- `requests` to call an external chat model API
- `python-dotenv` to load environment variables from `code/app/.env`

The database includes three tables:

- `users`: registered accounts
- `sessions`: hashed session tokens with expiry and revocation timestamps
- `chats`: saved user and assistant messages

### Frontend

The frontend is plain HTML, CSS, and JavaScript:

- `index.html`: login page
- `register.html`: registration page
- `chat.html`: authenticated chat UI
- `app.js`: page behavior, API calls, and chat rendering
- `styles.css`: shared styling for auth and chat screens

The client chooses its API base URL like this:

- If opened directly from the filesystem (`file:`), it calls `http://127.0.0.1:8000`
- If served over HTTP, it calls `/api`

### Reverse Proxy

`code/nginx/nginx.conf` is set up so that:

- `/` goes to the frontend container
- `/api/` goes to the FastAPI container
- `/health` proxies to the backend health endpoint

## API Endpoints

These routes are implemented in `code/app/main.py`:

- `GET /health`: returns `{"status": "ok"}`
- `GET /me`: returns the authenticated user's `id` and `email`
- `POST /register`: creates a new user
- `POST /index`: logs a user in and sets the `session_id` cookie
- `POST /logout`: revokes the current session and clears the cookie
- `GET /chats`: returns the current user's saved chat history
- `POST /chat`: stores the user's prompt, sends recent conversation context to the model API, stores the assistant reply, and returns both new messages

## Environment Variables

The backend expects an `.env` file at `code/app/.env`. Based on the code, these variables are used:

- `MODEL_NAME`: defaults to `HuggingFaceTB/SmolLM2-135M-Instruct`
- `MODEL_API_URL`: URL for the model backend
- `MODEL_API_KEY`: bearer token for the model backend
- `MODEL_REQUEST_TIMEOUT_SECONDS`: request timeout, default `30`
- `MODEL_CONTEXT_MESSAGE_LIMIT`: number of recent messages included in model context, default `5`

If `MODEL_API_URL` or `MODEL_API_KEY` is missing, chat generation returns a `500` error.

## Running With Docker Compose

From the `code/` directory:

```bash
docker compose up --build
```

This starts:

- `api`: FastAPI on internal port `8000`
- `frontend`: static site served by Nginx on internal port `80`
- `nginx`: public entrypoint on port `80`

Then open:

```text
http://localhost
```

## Authentication Flow

1. A user registers through `register.html`, which sends `POST /register`.
2. A user logs in through `index.html`, which sends `POST /index`.
3. On successful login, the backend sets a `session_id` cookie.
4. Protected endpoints use that cookie to load the current user.
5. Logging out revokes the session record and deletes the cookie.

## Chat Flow

1. `chat.html` loads the current user through `GET /me`.
2. Existing messages are loaded through `GET /chats`.
3. Sending a prompt calls `POST /chat`.
4. The backend loads the user's previous chats, keeps the most recent messages based on `MODEL_CONTEXT_MESSAGE_LIMIT`, appends the new prompt, and forwards that conversation to the configured model API.
5. The new user message and assistant reply are saved to the database and returned to the client.

## Notes

- The login endpoint is named `POST /index` because the frontend derives the API path from the page name.
- Session cookies are configured as `HttpOnly`, `SameSite=Lax`, and `secure=False`.
- Request logging is enabled in the backend and written to `app.log`.
- The SQLite database file is created automatically when the backend starts.
