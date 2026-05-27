# eThute Lenna 5.0 — Complete Setup, Testing & GitHub Guide

---

## PART 1 — SET UP YOUR PROJECT FOLDER IN VS CODE

### Step 1 — Rename your folder (remove the space)
Your folder is called `ethutelenna _finalland_app5` (has a space).
Rename it to `ethutelenna_app5` so there are no issues.

**How to rename:**
- Open File Explorer on your Desktop
- Right-click the folder → Rename
- Type: `ethutelenna_app5`
- Press Enter

### Step 2 — Open in VS Code
- Open VS Code
- Go to File → Open Folder
- Select `ethutelenna_app5`
- Click OK

### Step 3 — Make sure all required files are in the root folder
Your folder should look like this:
```
ethutelenna_app5/
├── main.py
├── app.html
├── index.html
├── config.py
├── debugger.py
├── requirements_1.txt   ← rename this to requirements.txt
├── railway.toml
├── Procfile
├── .gitignore
├── .env                 ← create this (see Part 2)
├── static/              ← create this folder
├── study_guide/         ← already exists with PDFs
└── previous_papers/     ← already exists with PDFs
```

### Step 4 — Rename requirements_1.txt to requirements.txt
- In VS Code Explorer, right-click `requirements_1.txt`
- Click Rename
- Type: `requirements.txt`

---

## PART 2 — RUN THE PROJECT LOCALLY IN VS CODE

### Step 1 — Open the terminal
Press **Ctrl + `** (backtick)

### Step 2 — Create a virtual environment
```bash
python -m venv venv
```

### Step 3 — Activate it
```bash
venv\Scripts\activate
```
You will see **(venv)** appear at the start of the line.

### Step 4 — Install all dependencies
```bash
pip install -r requirements.txt
```
Wait for everything to install (may take 5–10 minutes first time).

### Step 5 — Create your .env file
In VS Code Explorer, right-click the project folder → New File → name it `.env`

Inside `.env` type:
```
JWT_SECRET=eThuteLenna2025SecretKey
OPENROUTER_API_KEY=sk-or-v1-your-actual-key-here
```
Replace the OpenRouter key with your real key from https://openrouter.ai

### Step 6 — Create the static folder
```bash
mkdir static
```

### Step 7 — Run the app
```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO: Uvicorn running on http://127.0.0.1:8000
INFO: Application startup complete.
```

---

## PART 3 — TEST THE APP

### Test 1 — Landing page
Open your browser and go to:
```
http://localhost:8000
```
You should see your eThute Lenna landing page (index.html). ✅

### Test 2 — App page
```
http://localhost:8000/app
```
You should see the login screen. ✅

### Test 3 — API documentation
```
http://localhost:8000/docs
```
You should see the full Swagger API documentation. ✅

### Test 4 — Health check
```
http://localhost:8000/health
```
You should see: `{"status":"ok", ...}` ✅

### Test 5 — Register a user
On the app page (http://localhost:8000/app):
- Click Register tab
- Enter a username, date of birth, school, and password
- Click Create Account
- You should be redirected to the dashboard ✅

### Test 6 — Ask AI question
- After logging in, select a subject (e.g. Mathematics)
- Click on the subject
- Click the "Ask AI Question" tab
- Type a question like: "What is the quadratic formula?"
- The answer should come from the PDFs in study_guide/ ✅

---

## PART 4 — CREATE A GITHUB REPOSITORY

### Step 1 — Create a GitHub account (if you don't have one)
Go to: https://github.com
Click Sign Up and create a free account.

### Step 2 — Install Git on your computer
Check if Git is installed:
```bash
git --version
```
If it shows a version number, skip to Step 3.

If not installed, download from: https://git-scm.com/download/win
Install with all default settings.

### Step 3 — Configure Git with your name and email
In VS Code terminal:
```bash
git config --global user.name "Your Name"
git config --global user.email "your@email.com"
```
Use the same email as your GitHub account.

### Step 4 — Create a new repo on GitHub
- Go to https://github.com
- Click the green **New** button (top left)
- Repository name: `ethutelenna-app`
- Description: `eThute Lenna Grade 12 AI Study Assistant`
- Set to **Private** (recommended — your code is private)
- Do NOT tick "Add README" or "Add .gitignore"
- Click **Create repository**

GitHub will show you a page with commands. Keep this page open.

### Step 5 — Initialize Git in your project folder
In your VS Code terminal (make sure you are in your project folder):
```bash
git init
```

### Step 6 — Add all files
```bash
git add .
```

### Step 7 — Make your first commit
```bash
git commit -m "Initial commit — eThute Lenna 5.0"
```

### Step 8 — Connect to your GitHub repo
Copy the URL from your GitHub repo page. It looks like:
`https://github.com/YourUsername/ethutelenna-app.git`

Then run:
```bash
git remote add origin https://github.com/YourUsername/ethutelenna-app.git
git branch -M main
```

### Step 9 — Push to GitHub
```bash
git push -u origin main
```

GitHub will ask for your username and password.
**Important:** For the password, you need a **Personal Access Token** (not your GitHub password).

#### How to get a Personal Access Token:
1. Go to https://github.com → click your profile photo (top right)
2. Click **Settings**
3. Scroll down → click **Developer settings** (bottom left)
4. Click **Personal access tokens** → **Tokens (classic)**
5. Click **Generate new token (classic)**
6. Give it a name: `ethutelenna`
7. Tick **repo** checkbox
8. Click **Generate token**
9. **Copy the token immediately** — it won't show again
10. Use this token as your password when Git asks

### Step 10 — Confirm it worked
Go to `https://github.com/YourUsername/ethutelenna-app`
You should see all your files listed. ✅

---

## PART 5 — PUSHING FUTURE CHANGES

Every time you make changes to your code:
```bash
git add .
git commit -m "Describe what you changed"
git push
```

---

## IMPORTANT — What NOT to push to GitHub

Your `.gitignore` file already protects these, but double-check:
- ❌ Never push your `.env` file (contains your secret keys)
- ❌ Never push `venv/` folder (too large, not needed)
- ❌ Never push `chroma_db/` folder (auto-rebuilt from PDFs)
- ✅ PDFs in `study_guide/` and `previous_papers/` ARE included

---

## COMMON ERRORS & FIXES

| Error | Fix |
|---|---|
| `ModuleNotFoundError` | Run `pip install -r requirements.txt` again |
| `JWT_SECRET not set` | Check your `.env` file exists and has the key |
| `git: command not found` | Install Git from https://git-scm.com |
| `Authentication failed` on git push | Use Personal Access Token, not your password |
| `Port 8000 already in use` | Use `--port 8001` instead |
| `config.py not found` | Make sure config.py is in the same folder as main.py |
