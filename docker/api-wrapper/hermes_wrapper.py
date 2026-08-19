"""
FastAPI wrapper for Hermes CLI agent.
Exposes OpenAI-compatible /v1/chat/completions endpoint.
Executes Hermes CLI via subprocess.
"""

import asyncio
import json
import logging
import subprocess
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Hermes API Wrapper")


class Message(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    max_tokens: Optional[int] = 1000


class Choice(BaseModel):
    index: int
    message: Message
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    model: str
    choices: list[Choice]
    usage: dict


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "hermes-wrapper"}


@app.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """
    OpenAI-compatible chat completions endpoint for Hermes.
    Executes real Hermes CLI and returns structured response.
    """
    try:
        # Extract last user message
        user_message = None
        for msg in reversed(request.messages):
            if msg.role == "user":
                user_message = msg.content
                break

        if not user_message:
            raise HTTPException(status_code=400, detail="No user message found")

        # Call Hermes CLI
        response_text = await call_hermes_cli(user_message)

        return ChatCompletionResponse(
            model=request.model,
            choices=[
                Choice(
                    index=0,
                    message=Message(role="assistant", content=response_text),
                    finish_reason="stop"
                )
            ],
            usage={
                "prompt_tokens": len(user_message.split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message.split()) + len(response_text.split())
            }
        )
    except Exception as e:
        logger.error(f"Error in chat_completions: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


async def call_hermes_cli(prompt: str) -> str:
    """
    Execute real Hermes CLI via subprocess.
    Sends prompt and captures response.
    """
    try:
        # Run hermes with the prompt as stdin
        process = await asyncio.create_subprocess_exec(
            "hermes",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Send prompt and get response
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(input=prompt.encode('utf-8')),
            timeout=60.0
        )

        # Decode output
        stdout = stdout_bytes.decode('utf-8', errors='ignore')
        stderr = stderr_bytes.decode('utf-8', errors='ignore')

        # Parse Hermes output
        # Hermes includes UI elements, we need to extract the actual response
        response_text = parse_hermes_output(stdout, stderr)

        if not response_text:
            raise Exception(f"No response from Hermes. stderr: {stderr}")

        logger.info(f"Hermes response length: {len(response_text)}")
        return response_text

    except asyncio.TimeoutError:
        raise Exception("Hermes CLI timeout (60s)")
    except Exception as e:
        logger.error(f"Error calling Hermes: {str(e)}")
        raise


def parse_hermes_output(stdout: str, stderr: str) -> str:
    """
    Extract the actual response from Hermes CLI output.
    Hermes includes UI elements, config warnings, etc.
    We need to find the actual agent response.
    """
    # Log full output for debugging
    logger.debug(f"Hermes stdout:\n{stdout}")
    logger.debug(f"Hermes stderr:\n{stderr}")

    # Try to find the response between the prompt and the next section
    lines = stdout.split('\n')

    # Find where the actual response starts
    # Usually after "─────────────────────────────────────"
    response_lines = []
    capture = False

    for line in lines:
        # Skip UI elements
        if any(x in line for x in ['╔', '╚', '║', '⚠', '⚕', '●', '✦', 'Welcome to', 'Type your', 'message or', '/help', 'for commands', 'Tip:', 'personality', 'Warning:', 'Input is not', 'terminal', 'Initializing', 'provider:', 'toolsets:', 'nemotron', 'Shutting', 'finalizing']):
            if capture and line.strip() == '':
                break
            continue

        # Skip separator lines
        if all(c in '─ ' for c in line):
            capture = True
            continue

        # Skip config warnings
        if 'Config issues' in line or 'Unknown' in line:
            continue

        if capture and line.strip():
            response_lines.append(line.strip())

    response = ' '.join(response_lines).strip()

    # If we got nothing, try a simpler approach - just grab non-empty lines
    if not response:
        response_lines = [line.strip() for line in lines
                         if line.strip()
                         and not any(x in line for x in ['╔', '╚', '║', '⚠', '⚕', '●', '✦', 'Welcome', 'Type', 'Tip:', 'Warning:', 'Input', 'Initializing', 'provider:', 'toolsets:', 'Config', 'Unknown', 'Shutting', 'finalizing', '─'])]
        response = ' '.join(response_lines)

    return response if response else "No response"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
