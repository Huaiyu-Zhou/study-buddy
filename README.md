# AI Study Buddy (WebRTC Edition)

AI Study Buddy is a proactive AI coaching system. It runs in the background, monitors your active application window or browser tab on Windows, compares it with your study plan, and speaks up unprompted over WebRTC when you get distracted.

This version uses a split client-server architecture:
- **FastAPI Bot Server (WSL / Linux)**: Manages the Pipecat pipeline (Deepgram STT + OpenAI LLM + Fish Audio TTS), creates Daily.co WebRTC rooms, and runs the AI supervisor bot.
- **Watchdog Client (Windows)**: A lightweight client that monitors active window processes and Chromium URLs using `pywin32` and UI Automation, posting updates to the server.
- **Interactive Web Interface**: A premium dark-themed browser dashboard where you set your study plan, select your supervisor persona, connect to the WebRTC audio channel, and view live focus metrics and logs.

---

## Architecture Diagram

```
┌────────────────────────────────────────┐         ┌─────────────────────────────────┐
│         Windows Host Browser           │         │   WSL / Linux Bot Server        │
│                                        │         │                                 │
│  ┌──────────────┐      ┌────────────┐  │ WebRTC  │  ┌───────────────────────────┐  │
│  │  daily-js    │◀════▶│ Speaker /  │  │◀═══════▶│  │ DailyTransport (Bot)      │  │
│  │  WebRTC SDK   │      │ Microphone │  │  UDP    │  └─────────────┬─────────────┘  │
│  └──────┬───────┘      └────────────┘  │         │                │                 │
│         │ user updates                 │         │                ▼                 │
│         ▼                              │         │       [Pipecat Pipeline]         │
│  ┌──────────────┐                      │         │  ┌───────┐   ┌───────┐   ┌─────┐ │
│  │ Dashboard UI │                      │         │  │ STT   │──▶│ LLM   │──▶│ TTS │ │
│  │ (index.html) │                      │         │  │(Deep- │   │(Open- │   │(Fish│ │
│  └──────────────┘                      │         │  │ gram) │   │  AI)  │   │Audio│ │
└─────────┬──────────────────────────────┘         │  └───────┘   └───────┘   └─────┘ │
          │ HTTP POST                              │                                 │
          │ /activity                              │  ┌───────────┐   ┌────────────┐ │
          ▼                                        │  │ Session   │   │ MemPalace  │ │
┌─────────────────┐                                │  │ (State)   │   │ (Memory)   │ │
│ win_watchdog.py │                                │  └───────────┘   └────────────┘ │
│ (pywin32 tool)  │                                └─────────────────────────────────┘
└─────────────────┘
```

---

## Prerequisites & API Keys

To run the WebRTC Study Buddy, you will need the following API Keys configured in your `.env` file:

- **Daily.co API Key**: Sign up at [Daily.co](https://dashboard.daily.co/) to get a free WebRTC API key.
- **Deepgram API Key**: Sign up at [Deepgram](https://deepgram.com/) for cloud-based, low-latency STT.
- **OpenAI API Key**: Used for LLM coaching response generation.
- **Fish Audio API Key**: Used for streaming high-quality TTS.

---

## Setup & Running Instructions

### ⚡ One-Click Quick Start (Windows + WSL)
If you are on Windows and have WSL (Ubuntu) installed, you can start the entire application (both server, client, and browser dashboard) with a single script:

1. Double-click the **[start_study_buddy.bat](file:///c:/Users/huaiy/OneDrive/Desktop/study-buddy/start_study_buddy.bat)** script in the project root directory.
2. The script will automatically:
   - Install/update Python packages inside WSL.
   - Run the server in WSL.
   - Run the watchdog client on your Windows host.
   - Open the web dashboard in your browser.

---

### Manual Setup & Running Instructions

### 1. Configure the Environment
Create a `.env` file in the root of the project (on both Windows and WSL if they are separate workspaces, or in the shared directory):
```env
DAILY_API_KEY=your_daily_api_key_here
DEEPGRAM_API_KEY=your_deepgram_api_key_here
OPENAI_API_KEY=your_openai_api_key_here
FISH_AUDIO_API_KEY=your_fish_audio_api_key_here
FISH_AUDIO_REFERENCE_ID=7f92f8afb8ec43bf81429cc1c9199cb1
```

### 2. Start the Bot Server (WSL / Linux)
Because the `daily-python` library is only supported on Linux/macOS, you must run the server inside a WSL (Windows Subsystem for Linux) terminal or a separate Linux environment:

```bash
# Create a virtual environment and install requirements
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Run the FastAPI server
python server.py
```
The server will start on port `7860`.

### 3. Start the Watchdog Client (Windows Host)
On your Windows host, open a PowerShell or Command Prompt terminal in the project directory:

```powershell
# Activate local virtual environment
.\venv\Scripts\activate

# Run the watchdog client
python win_watchdog.py
```
This client will monitor your active window title/process and active browser tab URLs, sending them to the Bot Server every 5 seconds.

### 4. Start Coaching
1. Open your browser and navigate to: [http://localhost:7860](http://localhost:7860)
2. Enter your **Subject**, **Study Plan Goal**, and select your **Supervisor Persona**.
3. Click **Start Coaching** and allow microphone access.
4. Interact with the coach! If you switch to an off-task window (e.g. YouTube or Reddit), the watchdog will report it, and the coach will interrupt you.
