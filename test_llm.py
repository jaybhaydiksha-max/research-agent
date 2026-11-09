import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
key = os.getenv("LLM_API_KEY", "")
print("Key loaded:", bool(key), "| length:", len(key), "| starts with:", key[:4])

client = OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL"))
try:
    r = client.chat.completions.create(
        model=os.getenv("LLM_MODEL"),
        messages=[{"role": "user", "content": "Say hello"}],
    )
    print(r.choices[0].message.content)
except Exception as e:
    print(type(e).__name__, e)