# agentic_project_builder_bot 🤖🚀

An integrated AI agent system operating via a Telegram Bot to transform project ideas into full-fledged applications and source code. Features automated planning, code generation, self-correction via extended error memory, and automatic deployment to GitHub.

---

## 📋 Overview

The project presents an Agentic Architecture managing the full software development lifecycle:
1. **Idea Reception**: The user sends a project concept (e.g., "REST API application with FastAPI and JWT") via Telegram Bot.
2. **Smart Planning (`PlannerAgent`)**: Analyzes and breaks down the idea into an action plan, file structure, and specific execution steps.
3. **Generation & Self-Correction (`CodeGeneratorAgent`)**: Generates source code and validates syntax based on historical error memory and resolution strategies.
4. **Memory & Error Management (`MemoryManager` & SQLite)**: Stores errors encountered during builds and automatically retrieves them to prevent recurrence and enhance LLM prompts.
5. **Deployment (`GitDeployer`)**: Initializes a local Git repository and deploys the project directly as a repository on GitHub.
6. **Workflow Orchestration (`WorkflowOrchestrator`)**: The core engine connecting all agents and displaying real-time progress updates to the user.

---

## ✨ Key Features

- 🤖 **Direct Telegram Interaction**: Real-time progress updates, error correction feedback, and project completion reports.
- 🧠 **Cumulative Error Memory Ledger**: Uses SQLite and `aiosqlite` to log errors and their solutions, injecting context into LLM prompts (Context Injection).
- 🔄 **Self-Correction Loop**: Automated code verification and refactoring upon detecting syntax errors (Syntax Rules/Validation).
- 🐙 **Automated GitHub Deployment**: Programmatically creates repositories and pushes completed project files along with initial configurations.
- ⚙️ **Secure Configuration Management**: Environment variables managed cleanly via `pydantic-settings`.
- 🧩 **Unified Data Schemas**: Flexible data and task exchange powered by `Pydantic` models.

---

## 🛠️ Prerequisites

- **Python**: Version 3.10 or higher.
- **Git**: Installed on the system environment.
- **Telegram Account**: To obtain `TELEGRAM_BOT_TOKEN` and your `Chat ID`.
- **OpenAI / LLM API Key**: Compatible API key for the `openai` SDK.
- **GitHub Account & Personal Access Token (PAT)**: For automated repository deployment.

---

## 📦 Installation

1. **Clone the repository:**
```bash
git clone https://github.com/your-username/agentic_project_builder_bot.git
cd agentic_project_builder_bot
```

2. **Create and activate a virtual environment:**
```bash
python -m venv venv
# On Linux/macOS:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

3. **Install dependencies:**
```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

Create a `.env` file in the root directory of the project and add the following environment variables:

```env
# Telegram Configuration
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
ALLOWED_USERS=123456789,987654321

# LLM / OpenAI Configuration
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o

# GitHub Configuration
GITHUB_TOKEN=your_github_personal_access_token
GITHUB_USERNAME=your_github_username

# System Paths & Settings
WORKSPACE_DIR=./workspace
DB_PATH=./data/project_memory.db
```

---

## 🚀 Usage

### 1. Running the Telegram Bot
To start the full system and receive project build requests via Telegram:

```bash
python bot.py
```

### 2. Available Bot Commands
- `/start` : Start interacting with the bot and verify user authorization.
- `/help` : View usage instructions and instructions on sending project ideas.
- `/history` : View project history and past memory records.
- **Sending Project Idea**: Send project details directly as text (e.g., *"Create a REST API application using FastAPI with JWT authentication system and SQLite database"*).

---

## 📁 Project Structure

```text
agentic_project_builder_bot/
│
├── config.py             # Settings and environment variables management
├── db.py                 # SQLite database initialization and interaction for logs and memory
├── memory_manager.py     # Memory management, cumulative error logs, and context retrieval
├── planner_agent.py      # Planning agent to break down ideas into actionable steps
├── code_generator.py     # Code generation agent with self-correction loop
├── git_deployer.py       # Git management and automated GitHub deployment
├── orchestrator.py       # Core orchestrator engine linking agents and workflow execution
├── bot.py                # Telegram bot interface and command handler
│
├── requirements.txt      # Project dependencies list
└── README.md             # Comprehensive project documentation
```

### Module Breakdown:

| File | Description / Exported Interfaces |
| :--- | :--- |
| `config.py` | Exports `Settings` and `settings` for directory paths and API key configurations. |
| `db.py` | Exports database initialization and query functions like `init_db`, `save_error_log`, and `get_project_memory`. |
| `memory_manager.py` | Exports `MemoryManager` to handle error contexts and prompt injections. |
| `planner_agent.py` | Exports `PlannerAgent`, `ProjectPlan`, and `TaskStep` for converting ideas into actionable steps. |
| `code_generator.py` | Exports `CodeGeneratorAgent` and `ExecutionResult` for generating, testing, and fixing code. |
| `git_deployer.py` | Exports `GitDeployer` and `deploy_to_github` for handling Git and GitHub operations. |
| `orchestrator.py` | Exports `WorkflowOrchestrator` to execute full workflows and send progress notifications. |
| `bot.py` | Exports `run_bot` and `main` to manage the Telegram interface and user interaction. |

---

## 🔄 Self-Correction & Learning Lifecycle

1. **Capture**: When errors occur during code generation or file writing, `CodeGeneratorAgent` captures the error message and context location.
2. **Log**: Error type, message, and execution context are saved into SQLite via `MemoryManager`.
3. **Inject**: On subsequent attempts to fix code or generate similar tasks, historical error logs and solutions are retrieved and injected into the `System Prompt`.
4. **Continuous Improvement**: The model avoids past mistakes and outputs corrected, robust code.

---

## 📜 License

This project is licensed under the **MIT License**. Feel free to use and enhance it.
