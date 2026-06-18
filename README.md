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
