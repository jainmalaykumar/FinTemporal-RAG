try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter
    print("langchain text_splitter available")
except ImportError:
    print("langchain text_splitter NOT available")
try:
    from pypdf import PdfReader
    print("pypdf available")
except ImportError:
    print("pypdf NOT available")
try:
    import PyPDF2
    print("PyPDF2 available")
except ImportError:
    pass
