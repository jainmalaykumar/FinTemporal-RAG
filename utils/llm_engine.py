import logging
from langchain_community.llms import Ollama
from langchain_core.prompts import PromptTemplate

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

import os
from dotenv import load_dotenv

load_dotenv()

class FinRAGGenerator:
    def __init__(self):
        try:
            # Initialize the Ollama model pointing strictly to "qwen:7b" or env var
            self.model_name = os.getenv("OLLAMA_MODEL", "qwen7b:latest")
            self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            self.llm = Ollama(model=self.model_name, base_url=self.base_url, temperature=0.1)
            
            # Define the strict financial analyst prompt template exactly as requested
            self.prompt_template = PromptTemplate(
                input_variables=["context", "query"],
                template=(
                    "You are an elite Financial AI Analyst. Answer the user's question using ONLY the provided financial context below. "
                    "Data-Source Hierarchy: if a live market chunk (Yahoo Finance / yfinance) states a metric as 'N/A', 'None', 'null', "
                    "or otherwise missing, that alone is not sufficient grounds to refuse — first check the uploaded documents "
                    "(PDF/Excel tables) and YouTube transcript chunks in the context for that same metric, or for the raw components "
                    "needed to derive it, and use those instead. "
                    "If the information is insufficient to answer the query, state: 'I do not have sufficient context to answer this question.'\n\n"
                    "Context:\n"
                    "{context}\n\n"
                    "Question:\n"
                    "{query}\n\n"
                    "Answer:"
                )
            )
            logging.info(f"FinRAGGenerator initialized successfully with model {self.model_name}.")
        except Exception as e:
            logging.error(f"Failed to initialize FinRAGGenerator: {e}")
            raise

    def generate_response(self, user_query: str, context_chunks: list) -> str:
        """
        Formats context chunks into a clean, numbered string list, 
        injects them into the prompt along with the query,
        and generates a deterministic response using the local LLM.
        """
        if not user_query:
            return "No query provided."

        if not context_chunks:
            return "I do not have sufficient context to answer this question."

        # Format context chunks into a clean, numbered string list
        formatted_context = ""
        for idx, chunk in enumerate(context_chunks, 1):
            formatted_context += f"{idx}. {chunk}\n"

        try:
            # Build the final prompt string
            prompt = self.prompt_template.format(context=formatted_context.strip(), query=user_query)
            
            # Generate the response via the LLM
            print(f"[LLM REQUEST]: Model: {self.model_name}, URL: {self.base_url}")
            logging.info(f"Generating response for query: '{user_query}'")
            response = self.llm.invoke(prompt)
            return response.strip()
            
        except Exception as e:
            print(f"[LLM ERROR]: {str(e)}")
            logging.error(f"Error during response generation: {e}")
            return f"An error occurred while generating response: {str(e)}. (Model: {self.model_name}, URL: {self.base_url})"

if __name__ == "__main__":
    generator = FinRAGGenerator()
    
    dummy_context = [
        "Tata Motors revenue grew by 15% in Q3.",
        "Reliance released a new energy strategy."
    ]
    
    test_query = "What was Tata Motors revenue growth?"
    
    print("\n--- Testing LLM Engine ---")
    print(f"Query: {test_query}\n")
    print("Context Provided:")
    for idx, c in enumerate(dummy_context, 1):
        print(f"{idx}. {c}")
        
    print("\nGenerating Response...")
    try:
        response = generator.generate_response(test_query, dummy_context)
        print(f"\nResponse:\n{response}")
    except Exception as e:
        print(f"\nFailed to generate response. Is Ollama running with 'qwen7b'? Error: {e}")
