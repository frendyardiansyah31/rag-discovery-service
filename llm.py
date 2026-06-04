import os
from dotenv import load_dotenv
load_dotenv()

from openai import AsyncOpenAI

client = AsyncOpenAI(
    api_key=os.getenv("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1",
)


async def generate_answer(query: str, sources: list, context: str = "") -> str:
    # Use pre-assembled context if provided (from PDF chunks),
    # otherwise fall back to building context from source abstracts.
    if not context:
        context = "\n\n".join([
            f"[{i+1}] Title: {s['title']}\nAbstract: {s.get('abstract', '')}"
            for i, s in enumerate(sources)
        ])

    resp = await client.chat.completions.create(
        model="llama-3.1-8b-instant",
        max_tokens=512,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are UIII Library assistant. Answer users questions based on "
                    "available collections. Always respond in English, clearly and "
                    "concisely. Cite the relevant source titles in your answer."
                ),
            },
            {
                "role": "user",
                "content": f"Question: {query}\n\nAvailable Collection:\n{context}",
            },
        ],
    )
    return resp.choices[0].message.content
