# RAG Chatbot & Query Clustering

## Folder Structure Overview
* `app.py`: Main Streamlit application entry point.
* `src/`: Core logic and AI integrations (`rag_engine.py`, `cluster_engine.py`).
* `scripts/`: Utility and testing scripts (`test_clustering.py`, `view_results.py`).
* `pages/`: Contains the analytics dashboard interface (`dashboard.py`).
* `db_tools/`: Scripts for initializing, seeding, and resetting the databases.
* `docs/`: Contains the source documents (e.g., `cleaned student handbook.docx`).
* `archive/`: Stores deprecated or legacy code.
* `README.md`: Project documentation.
* `requirements.txt`: Python dependencies.

## Local Setup Instructions

Follow these steps to get the project running on your own machine.

### 1. Clone the Repository
```bash
git clone https://github.com/nathanielchaz10-bit/Web-Based-RAG-Powered-Campus-Information-Chatbot-With-Automated-Query-Clustering
cd RAGV6
```

### 2. Set Up the Virtual Environment
```bash
python -m venv venv
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
You need a Google Gemini API key to run the LLM. You can get a free tier key from Google AI Studio.

a. Copy the .env.example file and rename the copy to .env.

b. Open newly named .env and paste your Gemini API key here:
```bash
GEMINI_API_KEY=your_actual_key_here
```
c. Paste the team LangSmith API key (ask the project lead for this key via direct message).
```bash    
LANGCHAIN_API_KEY=actual_team_key_here
```

### 5. Initialize the Databases
Before running the app, you need to set up your local SQLite and Chroma vector databases. Run the setup scripts provided in the tools folder:
```bash
python db_tools/init_db.py
python db_tools/seed_db.py
```

6. Run the Application
Start the Streamlit server:
```bash
streamlit run app.py
```

```
Project Structure 

hccs_rag_chatbot/
│
├── 📄 .env.example                     # Template — never commit the real .env
├── 📄 .gitignore
├── 📄 requirements.txt
├── 📄 README.md
├── 📄 main.py                          # FastAPI app entry point
│
├── 📁 app/
│   ├── 📄 __init__.py
│   │
│   ├── 📁 api/
│   │   ├── 📄 __init__.py
│   │   ├── 📄 auth.py
│   │   ├── 📄 chat.py
│   │   ├── 📄 documents.py
│   │   ├── 📄 clusters.py
│   │   ├── 📄 dashboard.py
│   │   ├── 📄 settings.py
│   │   └── 📄 users.py
│   │
│   ├── 📁 core/
│   │   ├── 📄 __init__.py
│   │   ├── 📄 config.py
│   │   ├── 📄 database.py
│   │   ├── 📄 security.py
│   │   ├── 📄 rate_limiter.py
│   │   └── 📄 exceptions.py
│   │
│   ├── 📁 models/
│   │   ├── 📄 __init__.py
│   │   ├── 📄 role.py
│   │   ├── 📄 user_account.py
│   │   ├── 📄 auth_log.py
│   │   ├── 📄 chat_session.py
│   │   ├── 📄 document.py
│   │   ├── 📄 document_chunk.py
│   │   ├── 📄 clustering_run.py
│   │   ├── 📄 cluster.py
│   │   ├── 📄 cluster_keyword.py
│   │   ├── 📄 query_log.py
│   │   ├── 📄 chat_response.py
│   │   └── 📄 system_metrics.py
│   │
│   ├── 📁 schemas/
│   │   ├── 📄 __init__.py
│   │   ├── 📄 auth.py
│   │   ├── 📄 chat.py
│   │   ├── 📄 document.py
│   │   ├── 📄 cluster.py
│   │   ├── 📄 dashboard.py
│   │   ├── 📄 settings.py
│   │   └── 📄 user.py
│   │
│   ├── 📁 services/
│   │   ├── 📄 __init__.py
│   │   │
│   │   ├── 📁 auth/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 google_oauth.py
│   │   │   ├── 📄 session.py
│   │   │   └── 📄 domain_validator.py
│   │   │
│   │   ├── 📁 rag/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 pipeline.py
│   │   │   ├── 📄 embedder.py
│   │   │   ├── 📄 retriever.py
│   │   │   ├── 📄 prompt_builder.py
│   │   │   ├── 📄 generator.py
│   │   │   └── 📄 fallback.py
│   │   │
│   │   ├── 📁 documents/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 preprocessor.py
│   │   │   ├── 📄 extractor.py
│   │   │   ├── 📄 cleaner.py
│   │   │   ├── 📄 chunker.py
│   │   │   └── 📄 vector_store.py
│   │   │
│   │   ├── 📁 clustering/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 pipeline.py
│   │   │   ├── 📄 preprocessor.py
│   │   │   ├── 📄 vectorizer.py
│   │   │   ├── 📄 algorithm.py
│   │   │   ├── 📄 labeler.py
│   │   │   └── 📄 scheduler.py
│   │   │
│   │   ├── 📁 analytics/
│   │   │   ├── 📄 __init__.py
│   │   │   ├── 📄 dashboard.py
│   │   │   ├── 📄 query_stats.py
│   │   │   └── 📄 system_health.py
│   │   │
│   │   └── 📁 nlp/
│   │       ├── 📄 __init__.py
│   │       ├── 📄 sentiment.py
│   │       ├── 📄 intent.py
│   │       └── 📄 speech_to_text.py
│   │
│   └── 📁 middleware/
│       ├── 📄 __init__.py
│       ├── 📄 auth_middleware.py
│       └── 📄 cors.py
│
├── 📁 database/
│   ├── 📄 __init__.py
│   ├── 📄 init_db.py
│   └── 📄 seed.py
│
├── 📁 vector_store/
│   └── 📄 .gitkeep                     # Keeps folder tracked, chroma_db ignored
│
├── 📁 uploads/
│   ├── 📁 pdf/
│   │   └── 📄 .gitkeep
│   ├── 📁 docx/
│   │   └── 📄 .gitkeep
│   └── 📁 txt/
│       └── 📄 .gitkeep
│
├── 📁 frontend/
│   ├── 📄 index.html                   # Login page
│   │
│   ├── 📁 student/
│   │   └── 📄 index.html               # Student chatbot interface
│   │
│   ├── 📁 admin/
│   │   ├── 📄 dashboard.html
│   │   ├── 📄 clusters.html
│   │   ├── 📄 documents.html
│   │   └── 📄 settings.html
│   │
│   ├── 📁 css/
│   │   ├── 📄 global.css
│   │   ├── 📄 login.css
│   │   ├── 📄 chat.css
│   │   └── 📄 admin.css
│   │
│   ├── 📁 js/
│   │   ├── 📄 auth.js
│   │   ├── 📄 router.js
│   │   ├── 📄 api.js
│   │   │
│   │   ├── 📁 student/
│   │   │   ├── 📄 chat.js
│   │   │   ├── 📄 history.js
│   │   │   └── 📄 voice.js
│   │   │
│   │   └── 📁 admin/
│   │       ├── 📄 dashboard.js
│   │       ├── 📄 clusters.js
│   │       ├── 📄 documents.js
│   │       └── 📄 settings.js
│   │
│   └── 📁 assets/
│       ├── 📁 images/
│       │   └── 📄 hccs-logo.png
│       └── 📁 icons/
│
└── 📁 tests/
    ├── 📄 __init__.py
    ├── 📄 conftest.py
    ├── 📄 test_auth.py
    ├── 📄 test_rag.py
    ├── 📄 test_documents.py
    ├── 📄 test_clustering.py
    ├── 📄 test_rate_limiter.py
    └── 📄 test_api.py
```
