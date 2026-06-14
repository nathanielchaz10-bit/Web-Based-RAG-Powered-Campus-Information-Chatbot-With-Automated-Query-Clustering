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
from langchain_classic.chains import create_history_aware_retriever
from langchain_core.prompts import MessagesPlaceholder

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

    print()
    print("Starting RAG pipeline.")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    chroma_db_path = os.path.join(base_dir, 'chroma_db')
    docs_path = os.path.join(base_dir, 'docs')

    # set up the embedding model
    embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001", task_type=None)

    if os.path.exists(chroma_db_path):
        print()
        print("Found existing database. Loading from disk.")

        vectorstore = Chroma(
            persist_directory=chroma_db_path,
            embedding_function=embeddings
        )

    else:
        print()
        print("No database found. Building from scratch.")

        # 1. load documents ('docs' folder)
        docs = load_documents_from_folder(docs_path)
        if not docs:
            print()
            print("Error 404: Please put a PDF or DOCX file in the 'docs' folder.")
            return

        # 2. chunk the documents
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        
        # 3. filterng the chunks to remove garbage formatting
        # skipped to since lilinisin din natin mismong docs, JIC lang to
        
        cleaned_splits = []
        for split in splits:
            # removing hidden Word doc formatting codes and null characters
            clean_text = split.page_content.replace('\x00', '').replace('\xa0', ' ')
            
            # collapse spacing and empty line breaks into a single space
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            # if chunk has less than 15 valid characters, its garbage formatting.
            if len(clean_text) > 15:
                split.page_content = clean_text
                cleaned_splits.append(split)
                
        splits = cleaned_splits

        print()
        print(f"Total chunks to process for ChromaDB: {len(splits)}")
        print()

        vectorstore = Chroma(
            persist_directory=chroma_db_path,
            embedding_function=embeddings
        )

        successful_chunks = 0
        for i, split in enumerate(splits):
            try:
                # sends ONE document only. 
                vectorstore.add_documents([split])
                successful_chunks += 1
                
                # print progress every 50 chunks para sure di nagcrash
                if (i + 1) % 50 == 0:
                    print(f"Processed {i + 1}/{len(splits)}.")
                    
            except IndexError:
                print()
                print(f"Skipped chunk {i+1} (Google Safety Filter triggered, likely a disciplinary rule)")
            except Exception as e:
                print()
                print(f"Skipped chunk {i+1} due to an unknown API error.")
            
            time.sleep(0.5) 

        print()    
        print(f"Successfully embedded {successful_chunks}/{len(splits)} chunks.")

    # 5. set up retriever
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

    # 6. set up the LLM and prompt
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0)
    
    # para matandaan ng AI previous messages and use them as context, need to "contextualize" the question first.
    # prompt para sa AI mismo
    contextualize_q_system_prompt = (
        "Given a chat history and the latest user question "
        "which might reference context in the chat history, "
        "formulate a standalone question which can be understood "
        "without the chat history. Do NOT answer the question, "
        "just reformulate it if needed and otherwise return it as is."
    )
    # prompt para sa user input + chat history
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    history_aware_retriever = create_history_aware_retriever(
        llm, 
        retriever, 
        contextualize_q_prompt
    )

    # 7. build chains
    qa_system_prompt = (
        "You are a helpful assistant for Holy Child Catholic School students. "
        "Use the following pieces of retrieved context to answer the question. "
        "If you do not know the answer based on the context, say that you do not know. "
        "Context: {context}"
    )

    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])

    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

    print("RAG Chain Loaded Successfully.")
    return rag_chain

def log_query_to_db(query_text, answer_text=None):
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        db_path = os.path.join(base_dir, 'analytics.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        clean_query = query_text.lower().strip()
        cursor.execute(
            "INSERT INTO user_queries (query_text, answer_text) VALUES (?, ?)", 
            (clean_query, answer_text))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Logging error (ignoring so chat doesn't break): {e}")