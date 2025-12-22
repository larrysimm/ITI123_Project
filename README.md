Here is a clean, professional **README.md** focused on introducing the application effectively.

You can copy-paste this directly into your GitHub repository.

```markdown
# Poly-to-Pro (P2P): The Competency Alignment Validator

![Status](https://img.shields.io/badge/Status-Prototype-orange)
![Stack](https://img.shields.io/badge/Tech-React_|_LangChain_|_Python-blue)
![Context](https://img.shields.io/badge/Data-Singapore_SkillsFuture-red)

> **"Don't just practice. Validate your skills against Industry Standards."**

---

## 🧐 What is this App?

**Poly-to-Pro (P2P)** is a specialized Interview Simulator designed to solve the "Articulation Gap" faced by Singapore Polytechnic graduates.

Many graduates possess strong technical skills but fail job interviews because they cannot map their school projects to corporate terminology. **P2P** changes the interview preparation process from a passive "chat" into an active **Competency Validation**.

Unlike generic AI wrappers, this application grounds every piece of feedback in the official **Singapore SkillsFuture Framework**. It ensures that when a student claims they "checked the numbers," they are coached to say they "performed Financial Reconciliation in accordance with audit standards."

---

## 💡 The Problem it Solves

1.  **The Keyword Mismatch:** Students miss out on jobs because their resumes and answers lack the specific keywords used by Applicant Tracking Systems (ATS) and Hiring Managers.
2.  **The Structure Deficit:** Students often ramble when answering behavioral questions, failing to demonstrate the "Result" of their work.
3.  **Generic Advice:** Standard tools like ChatGPT give generic, global advice. P2P gives advice specific to **Singaporean Job Roles**.

---

## ⚙️ How It Works (The Dual-Agent Engine)

The application uses a **Dual-Agent Architecture** to simulate a high-stakes interview panel.

### 🕵️ Agent A: The Hiring Manager (Technical Validator)
* **Role:** The Skeptic.
* **Logic:** It reads the user's answer and performs a semantic search against a Vector Database containing **SkillsFuture CSV Data**.
* **Output:** If you miss a critical industry term (e.g., "Data Sanitization"), it flags it immediately in a **Red Critique Card**.

### 🎓 Agent B: The Career Coach (Behavioral Strategist)
* **Role:** The Mentor.
* **Logic:** It analyzes the *structure* of the answer using the **STAR Method** (Situation, Task, Action, Result).
* **Output:** It rewrites the student's story to be punchy and persuasive in a **Green Coaching Card**.

---

## 🏗️ System Architecture

The app features a **Persistent Context Sidebar** that "locks" the user's resume into the session, ensuring the AI never forgets who it is talking to.

```mermaid
graph LR
    classDef sidebarContainer fill:#0f172a,stroke:#334155,color:#fff
    classDef goldResult fill:#fffbeb,stroke:#f59e0b,color:#78350f,stroke-width:2px

    subgraph APP [Poly-to-Pro Application Flow]
        direction TB
        
        subgraph SIDEBAR [1. Context Engine]
            RESUME[📄 Resume PDF]
            ROLE[🎯 Target Role]
        end

        subgraph AGENTS [2. The Validator Engine]
            MGR[😠 Manager Agent\n(Checks SkillsFuture Keywords)]
            COACH[🤓 Coach Agent\n(Checks STAR Structure)]
        end
        
        RESULT[🏆 Final Model Answer]
    end

    RESUME --> MGR
    ROLE --> MGR
    MGR --> RESULT
    COACH --> RESULT
    
    class SIDEBAR sidebarContainer
    class RESULT goldResult

```

---

## 🛠️ Tech Stack

* **Frontend:** React.js, Tailwind CSS, Lucide-React Icons.
* **Backend:** Python (FastAPI/Flask).
* **AI Orchestration:** LangChain (Sequential Chains).
* **Database:** ChromaDB (Vector Store for Skills Data).
* **Deployment:** Vercel (Frontend) + Railway (Backend).

---

## 🚀 Getting Started

### 1. Clone the Repo

```bash
git clone [https://github.com/your-username/poly-to-pro.git](https://github.com/your-username/poly-to-pro.git)

```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt
# Add your OPENAI_API_KEY to .env
python app.py

```

### 3. Frontend Setup

```bash
cd frontend
npm install
npm start

```

---

## 👨‍💻 Author

**Sim Chung Boon Larry**

* *Submitted for ITI123 Generative AI & Deep Learning Capstone*

```

```