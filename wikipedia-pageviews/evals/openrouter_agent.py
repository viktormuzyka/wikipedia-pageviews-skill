"""Minimal tool-using agent to test the skill on OpenRouter models (including free ones).

The model sees only the skill's name, description and location, like a real agent host,
and has two tools: bash and read_file. It runs shell commands the model asks for, so use
it in a container or another sandbox.

Usage:
  python3 evals/openrouter_agent.py --list-models
  OPENROUTER_API_KEY=... python3 evals/openrouter_agent.py --model qwen/qwen3.8-27b:free \
      "first user message" ["follow-up message" ...]

Each run gets a folder in evals/runs/ with the agent's files and transcript.json.
"""

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://openrouter.ai/api/v1"
MAX_STEPS = 25       # tool calls per user message before giving up
MAX_OUTPUT = 8000    # characters of tool output passed back to the model

TOOLS = [
    {"type": "function", "function": {
        "name": "bash", "description": "Run a shell command in the working directory; returns stdout and stderr.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "Read a text file (absolute path or relative to the working directory).",
        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
]


def skill_metadata() -> dict:
    """name and description from the SKILL.md frontmatter (one line each)."""
    with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
        frontmatter = f.read().split("---")[1]
    return dict(line.split(": ", 1) for line in frontmatter.splitlines() if line.startswith(("name:", "description:")))


def system_prompt(workdir: str) -> str:
    meta = skill_metadata()
    return (f"You are a helpful assistant with a Linux shell. Working directory: {workdir}\n\n"
            "Available skills (when a task matches a skill, read its SKILL.md first and follow it):\n"
            f"- name: {meta['name']}\n  description: {meta['description']}\n"
            f"  location: {SKILL_DIR}/SKILL.md\n\n"
            "Do not modify files inside the skill folder. Reply in the user's language.")


def request(path: str, body: dict | None = None) -> dict:
    """Call the OpenRouter API; free models are rate-limited, so retry 429 with backoff."""
    headers = {"Content-Type": "application/json", "X-Title": "wikipedia-pageviews skill eval"}
    if os.environ.get("OPENROUTER_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["OPENROUTER_API_KEY"]
    data = json.dumps(body).encode() if body else None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, data, headers), timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                sys.exit(f"OpenRouter error {e.code}: {e.read().decode()[:500]}")
            time.sleep(15 * (attempt + 1))


def run_tool(name: str, args: dict, workdir: str) -> str:
    if name == "bash":
        try:
            done = subprocess.run(args["command"], shell=True, cwd=workdir, capture_output=True,
                                  text=True, timeout=600)
            output = done.stdout + done.stderr + f"\n[exit code {done.returncode}]"
        except subprocess.TimeoutExpired:
            output = "[timed out after 600 s]"
    elif name == "read_file":
        try:
            with open(os.path.join(workdir, args["path"]), encoding="utf-8") as f:
                output = f.read()
        except OSError as e:
            output = f"[error: {e}]"
    else:
        output = f"[unknown tool {name}]"
    return output if len(output) <= MAX_OUTPUT else output[:MAX_OUTPUT] + "\n[output truncated]"


def answer(model: str, messages: list, workdir: str) -> str:
    """Let the model call tools until it replies with plain text."""
    for _ in range(MAX_STEPS):
        # A comma-separated list lets OpenRouter fall back to the next model when one is rate-limited.
        models = {"models": model.split(",")} if "," in model else {"model": model}
        reply = request("/chat/completions", {**models, "messages": messages, "tools": TOOLS})
        message = reply["choices"][0]["message"]
        messages.append(message)
        if not message.get("tool_calls"):
            return message.get("content") or ""
        for call in message["tool_calls"]:
            try:
                args = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {}
            print(f"  -> {call['function']['name']} {json.dumps(args, ensure_ascii=False)[:160]}", file=sys.stderr)
            output = run_tool(call["function"]["name"], args, workdir)
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": output})
    return "[stopped: too many tool calls]"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("prompts", nargs="*", help="user messages, sent one after another in one session")
    parser.add_argument("--model", default="qwen/qwen3.8-27b:free,google/gemma-4-31b-it:free,"
                                           "nvidia/nemotron-3-super-120b-a12b:free",
                        help="model id, or several comma-separated ids to fall back between")
    parser.add_argument("--list-models", action="store_true", help="free models that support tool calling")
    args = parser.parse_args()

    if args.list_models:
        models = request("/models?supported_parameters=tools")["data"]
        for m in sorted((m for m in models if m["id"].endswith(":free")), key=lambda m: m["id"]):
            print(f"{m['id']:55} context {m.get('context_length')}")
        return
    if not args.prompts or not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("Give at least one prompt and set OPENROUTER_API_KEY (see --help).")

    workdir = os.path.join(SKILL_DIR, "evals", "runs", f"{dt.datetime.now():%Y%m%d-%H%M%S}_{args.model.split(',')[0].replace('/', '_')}")
    os.makedirs(workdir)
    messages = [{"role": "system", "content": system_prompt(workdir)}]
    for prompt in args.prompts:
        print(f"\nUSER: {prompt}", file=sys.stderr)
        messages.append({"role": "user", "content": prompt})
        print(f"\nASSISTANT:\n{answer(args.model, messages, workdir)}")
    with open(os.path.join(workdir, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "messages": messages}, f, ensure_ascii=False, indent=1)
    print(f"\n[transcript: {workdir}/transcript.json]", file=sys.stderr)


if __name__ == "__main__":
    main()
