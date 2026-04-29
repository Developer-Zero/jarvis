import json

from config import (
    max_message_history,
    max_query_length,
    max_steps,
    semantic_memory_enabled,
    ttt_language,
    ttt_mode,
    ttt_model,
)
from backend.memory import SemanticMemory, format_memories_for_prompt
from backend.tools.registry import build_default_registry, tool_result_for_model
from runtime.userdata import get_openai_api_key


SYSTEM_PROMPT = f"""
You are a Jarvis-like AI execution agent.

ROLE
Execute user requests using tools. This is not a chatbot.

PRIORITY
1. Correct execution
2. Reliability and safety
3. Minimal output
4. Communication quality

BEHAVIOR
- Be precise and controlled
- No unnecessary explanations
- Internally break down tasks if needed
- Never reveal reasoning

AUTONOMY
- Act without confirmation if safe, reversible, low impact
- Ask for clarification if destructive, irreversible, critical, or unclear
- Make reasonable assumptions if intent is clear and risk is low

COMMUNICATION
- Tone: professional assistant (Jarvis-like)
- Language: '{ttt_language}' only
- Address user: "Uram"
- Keep responses short
- No slang, no filler
- Mild sarcasm only if request is irrational

ERROR HANDLING
- First failure: retry differently
- Repeated failure: return clear error message

OUTPUT RULES
- Final answer: plain text only (TTS-friendly)
- No JSON, links, file paths, or special characters like {{ }}
- JSON only for tool calls
- User only sees final answer

MEMORY
- Relevant long-term memories may be supplied as context
- Treat memories as helpful context, not guaranteed current truth
- Save durable user facts/preferences only when useful for future conversations
- Save memories when the user explicitly asks you to remember something
- Search memory if the user asks what you remember or past context is needed

CONSTRAINTS
- Do not explain reasoning
- Do not describe internal steps

MENTAL MODEL
Interpret -> decide -> act via tools -> return short spoken response
"""


class Agent:
    def __init__(self):
        self.messages = []
        self.prompt = SYSTEM_PROMPT
        self.client = None

        self.max_history = max_message_history
        self.max_query_length = max_query_length
        self.max_steps = max_steps
        self.memory = None
        self.active_memory_context = ""

        if ttt_mode == "openai":
            from openai import OpenAI

            api_key = get_openai_api_key()
            self.client = OpenAI(api_key=api_key) if api_key else OpenAI()

        if semantic_memory_enabled:
            self.memory = SemanticMemory(client=self.client)

        self.tool_registry = build_default_registry(self.memory)
        self.tools = self.tool_registry.get_openai_schemas()

    def get_safe_history(self):
        history = self.messages[-self.max_history:]

        while history and history[0]["role"] == "tool":
            history.pop(0)

        valid_tool_call_ids = set()

        for msg in history:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tool_call in msg["tool_calls"]:
                    if isinstance(tool_call, dict):
                        valid_tool_call_ids.add(tool_call["id"])
                    else:
                        valid_tool_call_ids.add(tool_call.id)

        safe_history = []

        for msg in history:
            if msg["role"] == "tool":
                if msg.get("tool_call_id") not in valid_tool_call_ids:
                    continue

            safe_history.append(msg)

        return safe_history

    def ask_model(self):
        if ttt_mode == "openai":
            try:
                messages = [{"role": "system", "content": self.prompt}]
                if self.active_memory_context:
                    messages.append({
                        "role": "system",
                        "content": self.active_memory_context,
                    })
                messages.extend(self.get_safe_history())

                response = self.client.chat.completions.create(
                    model=ttt_model,
                    tools=self.tools,
                    tool_choice="auto",
                    messages=messages,
                )
                return response
            except Exception as e:
                print(f"Error calling OpenAI API: {e}")
                raise
        else:
            raise ValueError(f"Unsupported ttt_mode: {ttt_mode}")

    def ask_agent(self, input):
        self.messages.append({"role": "user", "content": input})
        self.active_memory_context = self._build_memory_context(input)

        try:
            steps = 0
            while True:
                steps += 1
                if steps == self.max_steps - 1:
                    self.messages.append({
                        "role": "system",
                        "content": "You must give a final answer now. No tool calls allowed.",
                    })
                elif steps >= self.max_steps:
                    return "Hiba: Túl sok lépés"

                #print(f"Asking model | Messages: {self.messages}")
                try:
                    response = self.ask_model()
                except Exception as e:
                    print(f"Error getting model response: {e}")
                    return f"Hiba: {str(e)}"
                message = response.choices[0].message

                assistant_message = {
                    "role": "assistant",
                    "content": message.content or "",
                }

                if message.tool_calls:
                    assistant_message["tool_calls"] = [
                        {
                            "id": tool_call.id,
                            "type": tool_call.type,
                            "function": {
                                "name": tool_call.function.name,
                                "arguments": tool_call.function.arguments,
                            },
                        }
                        for tool_call in message.tool_calls
                    ]
                
                print(f"Jarvis: {message.content}")

                self.messages.append(assistant_message)

                print("Model responded: executing tasks")
                if message.tool_calls:
                    self.execute_commands(message.tool_calls)
                else:
                    print(f"Final answer given with {steps} steps")
                    return message.content
        finally:
            self.active_memory_context = ""

    def _build_memory_context(self, input_text: str) -> str:
        if not self.memory:
            return ""

        memories = self.memory.search(input_text)
        return format_memories_for_prompt(memories)

    def execute_commands(self, tool_calls):
        for tool_call in tool_calls:
            name = tool_call.function.name

            try:
                args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError as e:
                result = json.dumps({
                    "name": name,
                    "status": "error",
                    "error": f"Invalid JSON arguments: {e}",
                }, ensure_ascii=False)

                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result[:self.max_query_length],
                })
                print(f"Tool: {result[:self.max_query_length]}")
                continue

            tool_result = self.tool_registry.execute(name, args)
            result = tool_result_for_model(name, tool_result)

            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result[:self.max_query_length],
            })
            print(f"Tool: {result[:self.max_query_length]}")

_agent_instance = Agent()


def ask_agent(input_text):
    return _agent_instance.ask_agent(input_text)
