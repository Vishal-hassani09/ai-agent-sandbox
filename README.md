AI Coder Sandbox

An autonomous full-stack coding agent that connects a cloud-hosted React Web Studio and FastAPI backend with your local filesystem via a zero-config PyPI CLI device bridge (ai-coder-sandbox).

Live Demo

Watch the 75s Walkthrough: Full End-to-End Demo (demo.mp4)

Live Web Studio: https://ai-agent-sandbox-frontend.onrender.com

Backend API: https://ai-agent-sandbox-backend-dgcj.onrender.com

PyPI Package: ai-coder-sandbox

Key Features

Local Device Bridge (ai-coder ui): Launches a lightweight local WebSocket bridge in your active directory and pairs with the cloud Web Studio—giving the remote agent direct read, write, and command execution access to your local workspace without manual file uploads.

Interactive Terminal TUI (ai-coder cli): Terminal-native coding agent built with prompt_toolkit and rich, backed by the same cloud authentication and persistent session history.

Human-in-the-Loop Tool Permissions: Explicit approval prompts (Allow once, Always allow during this session, Deny) before executing shell commands or modifying local files.

Multi-Step Autonomous Tool Loop: Supports file reading, targeted editing, file search, directory listing, and sandboxed shell execution powered by Groq LLMs.

Persistent Sessions & Auth: JWT + email OTP verification (with SVG CAPTCHA rate-limiting), auto-generated session titles, and full conversation persistence in Neon PostgreSQL.

Architecture

+-----------------------------------+        HTTPS / WSS        +-----------------------------------+
|        Local Developer Machine    | <-----------------------> |     Render Cloud (FastAPI API)    |
|                                   |                           |                                   |
|  $ ai-coder ui                    |                           |  - JWT Auth & OTP Verification    |
|  - Local WebSocket Device Bridge  |                           |  - Agent Orchestrator (Groq SDK)  |
|  - Local Tool Executor (fs/shell) |                           |  - WebSocket Bridge Router        |
+-----------------------------------+                           +-----------------+-----------------+
                  ^                                                               |
                  | Opens Browser (?bridge_id=...)                                | Async SQLAlchemy
                  v                                                               v
+-----------------------------------+                           +-----------------------------------+
|     Render Cloud (React Studio)   |                           |       Neon PostgreSQL (Cloud)     |
|                                   |                           |                                   |
|  - Real-time Streaming UI         |                           |  - Users, Sessions & Messages     |
|  - Interactive Approval Modals    |                           |  - Persistent Workspace History   |
+-----------------------------------+                           +-----------------------------------+


Quick Start

1. Install the CLI Globally from PyPI

pip install ai-coder-sandbox
# or with pipx:
pipx install ai-coder-sandbox


2. Launch Web Studio Mode (Recommended)

Navigate to any local project folder and start the device bridge:

cd your-project-folder
ai-coder ui


This prints a paired URL (https://ai-agent-sandbox-frontend.onrender.com/?bridge_id=...), connects your local directory over WebSockets once you sign in, and lets you collaborate with the agent directly on your local files.

3. Launch Pure Terminal CLI Mode

ai-coder cli


Tech Stack

Backend: Python 3.12, FastAPI, Uvicorn, WebSockets, SQLAlchemy (Async), Pydantic Settings, Groq SDK

Database: PostgreSQL (Neon Serverless) / SQLite (Test Suite)

Frontend: React, Vite, Custom Streaming Client

CLI & Packaging: prompt_toolkit, rich, httpx, websockets, published on PyPI (setuptools)

Deployment & CI: Docker, Render Blueprint (render.yaml), GitHub Actions (pytest + vitest)

Local Development

git clone https://github.com/Vishal-hassani09/ai-agent-sandbox.git
cd ai-agent-sandbox

# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn app.api.main:app --reload

# Frontend (in a second terminal)
cd ../frontend
npm install
npm run dev
