import os
import re
import time
from dotenv import load_dotenv

import sqlite3

from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_chroma import Chroma
from langchain_classic.chains import create_retrieval_chain
from langchain_classic.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()

def load_documents_from_folder(folder_path):
    documents = []
    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        
        if file.endswith(".pdf"):
            print(f"Loading PDF: {file}")
            loader = PyPDFLoader(file_path)
            documents.extend(loader.load())
            
        elif file.endswith(".docx"):
            print(f"Loading DOCX: {file}")
            loader = Docx2txtLoader(file_path)
            documents.extend(loader.load())
            
    return documents

def run_rag_pipeline():
    print("Starting LangChain pipeline...")

    # 2. Load Documents from your folder
    docs = load_documents_from_folder("docs")
    
    if not docs:
        print("Error: No documents found! Please put a PDF or DOCX file in the 'docs' folder.")
        return

    # 3. Chunk the Documents
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    splits = text_splitter.split_documents(docs)

    # 4. Vectorize and Store (With Rate Limit Protection)
    print(f"Total document chunks to process: {len(splits)}")
    
    # Set up the embedding model and an empty Chroma database
    embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
    if os.path.exists("./chroma_db"):
        print("Found existing database. Loading from disk (this will be instant!)...")
        vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
        
    else:
        print("No database found. Building from scratch...")
        # 1. Load your documents
        documents = load_documents_from_folder("./docs")
        
        # 2. Split your documents
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)
        
        # 3. Build and batch to avoid API limits
        print(f"Total document chunks to process: {len(splits)}")
        vectorstore = Chroma(persist_directory="./chroma_db", embedding_function=embeddings)
        
        batch_size = 90 
        for i in range(0, len(splits), batch_size):
            batch = splits[i : i + batch_size]
            print(f"Adding batch {i} to {i + len(batch)} into ChromaDB...")
            vectorstore.add_documents(batch)
            
            if i + batch_size < len(splits):
                print("Approaching API limit. Sleeping for 60 seconds...")
                time.sleep(60)
                
        print("Database built successfully!")

    """vectorstore = Chroma.from_documents(
        documents=splits, 
        embedding=GoogleGenerativeAIEmbeddings(model="gemini-embedding-001"),
        persist_directory="./chroma_db"
    )"""

    retriever = vectorstore.as_retriever(search_kwargs={"k": 1})

    # 5. Set up the LLM and the Prompt
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    system_prompt = (
        "You are a helpful assistant for Holy Child Catholic School students. "
        "Use the following pieces of retrieved context to answer the question. "
        "If you do not know the answer based on the context, say that you do not know. "
        "Context: {context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}"),
    ])

    # 6. Build the Chains
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)

    # 7. Ask a Question
    print("\nSystem Ready.")
    
    while True:
        user_input = input("\nAsk a question (or type 'quit'): ")
        if user_input.lower() == 'quit':
            print("Shutting down chatbot...")
            break
        
        # Log the question to the database for the clustering engine
        log_query_to_db(user_input)
        
        # Send the user's question to the RAG chain and print the answer
        print("Thinking...")
        results = rag_chain.invoke({"input": user_input})
        print(f"\nChatbot: {results['answer']}")

def log_query_to_db(query_text):
    """saves the questions to the database"""
    try:
        conn = sqlite3.connect('analytics.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO user_queries (query_text) VALUES (?)", (query_text,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Logging error (ignoring so chat doesn't break): {e}")

if __name__ == "__main__":
    run_rag_pipeline()