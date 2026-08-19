#!/usr/bin/env python3
"""Quick test to verify Hermes and OpenClaw agents are accessible."""

import asyncio
import httpx
import json
import os
import sys

async def test_agent(name: str, endpoint: str, port: int) -> bool:
    """Test if an agent endpoint is responding."""
    print(f"\nTesting {name} on {endpoint}:{port}")
    print("-" * 50)

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test 1: Health check
        try:
            health_url = f"http://{endpoint}:{port}/health"
            print(f"1. Health check: {health_url}")
            response = await client.get(health_url)
            if response.status_code == 200:
                print(f"   ✓ Health check passed (status {response.status_code})")
            else:
                print(f"   ✗ Health check failed (status {response.status_code})")
                print(f"   Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"   ✗ Health check error: {e}")
            return False

        # Test 2: Chat completions API
        try:
            chat_url = f"http://{endpoint}:{port}/v1/chat/completions"
            print(f"\n2. Chat completions: {chat_url}")

            payload = {
                "model": "default",
                "messages": [
                    {"role": "user", "content": "Say 'Hello from agent'"}
                ],
                "max_tokens": 50,
                "temperature": 0.5
            }

            # Add auth headers for Hermes
            headers = {}
            if name == "Hermes":
                headers["Authorization"] = f"Bearer {os.environ.get('BENCH_HERMES_API_KEY', 'changeme')}"
            if name == "OpenClaw":
                headers["Authorization"] = f"Bearer {os.environ.get('BENCH_OPENCLAW_API_KEY', 'changeme')}"

            response = await client.post(chat_url, json=payload, headers=headers)

            if response.status_code == 200:
                data = response.json()
                if "choices" in data and len(data["choices"]) > 0:
                    message = data["choices"][0]["message"]["content"]
                    print(f"   ✓ Chat API responded")
                    print(f"   Response: {message[:100]}")
                    return True
                else:
                    print(f"   ✗ Unexpected response format: {data}")
                    return False
            else:
                print(f"   ✗ Chat API failed (status {response.status_code})")
                print(f"   Response: {response.text[:200]}")
                return False
        except Exception as e:
            print(f"   ✗ Chat API error: {e}")
            return False

async def main():
    """Test both agents."""
    print("=" * 60)
    print("AgentAssistBench — Docker Agent Health Check")
    print("=" * 60)

    agents = [
        ("Hermes", "localhost", 8001),
        ("OpenClaw", "localhost", 8002),
    ]

    results = {}
    for name, endpoint, port in agents:
        try:
            healthy = await test_agent(name, endpoint, port)
            results[name] = "✓ Healthy" if healthy else "✗ Failed"
        except Exception as e:
            print(f"\nError testing {name}: {e}")
            results[name] = f"✗ Error: {e}"

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for name, status in results.items():
        print(f"{name:12} {status}")

    all_healthy = all("✓" in status for status in results.values())
    if all_healthy:
        print("\n✓ All agents healthy! Ready to run benchmarks.")
        return 0
    else:
        print("\n✗ Some agents failed. Check logs with: docker compose logs")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
