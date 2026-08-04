# Business Requirements Document (BRD)

## Project Name: **IssueMiner AI**

**Project Type:** Open-Source Git-Native Web Portal

**Target Architecture:** GitHub Actions + GitHub Pages + Gemini API

**Estimated Hosting/Operational Cost:** $0/month

---

## 1. Executive Summary

**IssueMiner AI** is an automated, self-updating web portal that mines public developer channels (Hacker News, Reddit, GitHub Issues) for real-world software pain points. It feeds these raw signals into an AI processing pipeline to generate structured project specifications, recommended tech stacks, and step-by-step implementation blueprints.

The entire application runs inside a single GitHub repository using **GitHub Actions** for daily automated ETL (Extract, Transform, Load) and **GitHub Pages** for static site hosting.

---

## 2. Project Goals & Success Criteria

### Core Objectives

* **Zero Infrastructure Overhead:** Run 100% serverless using GitHub’s free tier ecosystem.
* **High-Signal Data Ingestion:** Automatically pull developer pain points from unauthenticated public JSON/RSS feeds.
* **Structured Specification Generation:** Leverage LLM structured outputs to turn unstructured complaints into actionable software blueprints.
* **Open Source Showcase:** Demonstrate modern GitOps and AI engineering practices to builder communities.

### Key Performance Indicators (KPIs)

* **Build Execution Time:** Workflow runs under 2 minutes per execution.
* **Uptime:** 100% static availability on GitHub Pages.
* **Compliance:** 0 rate-limit violations across target public APIs.

---

## 3. System Architecture & Data Flow

```text
 ┌─────────────────────────────────────────────────────────────┐
 │                  DATA INGESTION (Python)                    │
 │  - Hacker News API ("Ask HN" story IDs)                     │
 │  - GitHub REST API (Open issues labeled "help wanted")      │
 │  - Reddit Public JSON (/r/SaaS & /r/webdev frustration)     │
 └──────────────┬──────────────────────────────────────────────┘
                │
                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │               AI BLUEPRINT ENGINE (Gemini API)              │
 │  - System Prompt: Extract problem & target user             │
 │  - Schema: Enforce structured Pydantic / JSON response      │
 │  - Output: Problem Statement, Tech Stack, Step-by-Step Plan │
 └──────────────┬──────────────────────────────────────────────┘
                │
                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │            STATIC GENERATION & DEPLOYMENT                   │
 │  - Script renders Tailwind CSS index.html                   │
 │  - GitHub Action commits & deploys to `gh-pages` branch    │
 │  - Website live at https://<username>.github.io/<repo>/    │
 └─────────────────────────────────────────────────────────────┘

```

---

## 4. Functional Requirements

### FR-1: Data Ingestion Module

The system must fetch public data from at least 2 public channels without requiring paid API keys:

1. **Hacker News API:** Query `[https://hacker-news.firebaseio.com/v0/askstories.json](https://hacker-news.firebaseio.com/v0/askstories.json)` for active developer discussions.
2. **GitHub REST API:** Query `[https://api.github.com/search/issues?q=label](https://api.github.com/search/issues?q=label):"help wanted"+state:open` with default GitHub token headers.
3. **Reddit Public JSON:** Query `[https://www.reddit.com/r/SaaS/new.json](https://www.reddit.com/r/SaaS/new.json)` using a custom `User-Agent` header.

### FR-2: AI Synthesis & Structured Extraction Engine

* The system must pass raw text payloads to `gemini-1.5-flash` using `google-genai`.
* The AI output **must** enforce a strict JSON schema containing:
* `problem_title`: Short 5-8 word name for the project.
* `source_url`: Link back to original thread/issue.
* `target_users`: Who benefits from this software.
* `proposed_solution`: 2-3 sentence core product concept.
* `tech_stack`: Array of recommended technologies (e.g., `["Next.js", "Tailwind", "FastAPI"]`).
* `implementation_steps`: Array of 4-5 ordered development steps.



### FR-3: Static Site Generator (SSG)

* The script must write a standalone `index.html` file populated with styled Tailwind CSS components.
* The frontend layout must include:
* **Header:** Title, last-updated timestamp, and GitHub repo badge.
* **Filterable/Grid Layout:** Responsive cards displaying each mined project blueprint.
* **Action Buttons:** "View Original Source" external link and a "Copy Prompt" button for builders.



### FR-4: CI/CD & Automation Workflow

* A `.github/workflows/deploy.yml` workflow must execute on:
1. **Schedule:** Cron schedule (`0 0 * * *` - daily at midnight UTC).
2. **Manual Trigger:** `workflow_dispatch` button in GitHub UI.


* Workflow secrets must securely ingest `GEMINI_API_KEY` without exposing it in repository files.

---

## 5. Non-Functional Requirements (NFRs)

| NFR ID | Category | Requirement |
| --- | --- | --- |
| **NFR-1** | **Cost** | Must run 100% within free tiers of GitHub Pages, GitHub Actions, and Gemini API. |
| **NFR-2** | **Security** | Zero hardcoded credentials. All API tokens passed via `env` variables. |
| **NFR-3** | **Performance** | Generated `index.html` must weigh under 500 KB and render in under 1 second. |
| **NFR-4** | **Compliance** | Workflow run times must remain under standard execution limits (target < 3 minutes). |

---

## 6. Project Repository & File Structure

```text
issue-miner-ai/
├── .github/
│   └── workflows/
│       └── deploy.yml          # Automated daily build & deployment workflow
├── src/
│   ├── fetchers.py             # Functions to pull from HN, Reddit, and GitHub
│   ├── ai_engine.py            # Gemini client call with structured Pydantic schema
│   └── generator.py            # HTML template compiler
├── main.py                     # Primary execution pipeline script
├── requirements.txt            # Python dependencies (google-genai, requests, pydantic)
├── README.md                   # Project overview & quickstart guide
└── .gitignore                  # Ignores local build artifacts & secrets

```

---

## 7. Prompt for Claude Implementation

When pasting this BRD into Claude, use the prompt below to generate the codebase in one pass:

> "Act as a Senior Python & DevOps Engineer. Based on the attached Business Requirements Document (BRD) for **IssueMiner AI**, please write the complete code for all project files:
> 1. `requirements.txt`
> 2. `src/fetchers.py` (with HN and GitHub issue fetchers)
> 3. `src/ai_engine.py` (using `google-genai` and Pydantic for structured outputs)
> 4. `src/generator.py` (generating a clean, modern Tailwind CSS `index.html`)
> 5. `main.py`
> 6. `.github/workflows/deploy.yml`
> 7. A comprehensive `README.md`
> 
> 
> Ensure all code is production-ready, fully typed, handles missing API data gracefully, and conforms strictly to $0 hosting via GitHub Pages."