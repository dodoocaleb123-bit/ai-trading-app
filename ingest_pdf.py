import os
from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
from supabase import create_client, Client

# ==========================================
# 1. SUPABASE CREDENTIALS
# ==========================================
SUPABASE_URL = "https://ersudsbrhlpcgdifooyu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVyc3Vkc2JyaGxwY2dkaWZvb3l1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODY0MDQ3MTAsImV4cCI6MjEwMTk4MDcxMH0.L69IJYofSGiq7zAgvt1SzTUVT8kLi3h6ycWCF-h8Z-o"  # Paste your actual anon key here

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Load lightweight embedding model (384 dimensions)
embedding_model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')

def ingest_all_pdfs_in_folder(folder_path="."):
    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    
    if not pdf_files:
        print("❌ No PDF files found in the directory.")
        return

    print(f"📚 Found {len(pdf_files)} PDF(s) to process: {pdf_files}\n")

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=50
    )

    total_chunks_processed = 0

    for pdf_file in pdf_files:
        file_path = os.path.join(folder_path, pdf_file)
        print(f"📄 Processing: {pdf_file}...")
        
        try:
            reader = PdfReader(file_path)
            full_text = ""
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    full_text += text + "\n"
                    
            if not full_text.strip():
                print(f"⚠️ Warning: No text found in {pdf_file}. Skipping...\n")
                continue

            chunks = text_splitter.split_text(full_text)
            print(f"   └─ Split into {len(chunks)} chunks.")

            rows_to_insert = []
            for chunk in chunks:
                vector = embedding_model.encode(chunk).tolist()
                rows_to_insert.append({
                    "content": f"[{pdf_file}] {chunk}",
                    "embedding": vector
                })

            # Batch insert in chunks of 15 to prevent API timeout/payload errors
            batch_size = 15
            for i in range(0, len(rows_to_insert), batch_size):
                batch = rows_to_insert[i:i + batch_size]
                supabase.table("strategy_rules").insert(batch).execute()

            total_chunks_processed += len(chunks)
            print(f"   └─ ✅ Successfully saved to Supabase.\n")

        except Exception as e:
            print(f"   └─ ❌ Error processing {pdf_file}: {e}\n")

    print(f"🎉 Complete! Processed {len(pdf_files)} PDFs and saved {total_chunks_processed} strategy rules into AI memory.")

if __name__ == "__main__":
    ingest_all_pdfs_in_folder(".")