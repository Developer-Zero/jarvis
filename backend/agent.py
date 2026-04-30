import json
import uuid

from config import (
    episodic_memory_enabled,
    max_message_history,
    max_query_length,
    max_steps,
    semantic_memory_enabled,
    ttt_language,
    ttt_mode,
    ttt_model,
)
from backend.episodic_memory import EpisodicMemory
from backend.semantic_memory import SemanticMemory
from backend.memory_context import MemoryContextBuilder
from backend.memory_observer import MemoryObserver
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
- Be precise about outcomes, not internal details
- Do not mention file paths, install folders, source locations, or search details unless the user asks
- Do not over-explain choices, alternatives, or implementation details
- Internally break down tasks if needed
- Never reveal reasoning

AUTONOMY
- Act without confirmation when the request is safe, reversible, low impact, or the user's intent is clear
- Pick the most likely useful action instead of asking about minor details
- Use tools proactively to complete the task, including follow-up steps needed for a useful result
- Ask for clarification only if the action is destructive, irreversible, critical, unsafe, or genuinely ambiguous
- Make reasonable assumptions if intent is clear and risk is low

COMMUNICATION
- Tone: professional assistant (Jarvis-like)
- Language: '{ttt_language}' only
- Address user: "Uram"
- Keep responses short
- No slang, no filler
- Mild sarcasm only if request is irrational
- Confirm only what matters to the user
- After opening or launching something, confirm only that it is open
- Do not mention where an app, shortcut, file, or command was found

ERROR HANDLING
- On failure, retry up to 2 times with a different reasonable approach
- After 2 failed retries, return a short clear error and the useful next step

OUTPUT RULES
- Final answer must be plain spoken text, ready for text-to-speech
- Do not include JSON, links, raw file paths, stack traces, IDs, or technical syntax in the final answer
- Do not mention hidden execution details in the final answer
- If a path or technical detail is necessary, summarize it naturally instead of reading the raw value
- Do not repeat tool results, semantic memory text, episodic memory text, or context details verbatim
- Never include concrete source locations in confirmations

MEMORY
- Relevant semantic and episodic memories may be supplied as context
- Save relevant semantic memories proactively
- Save immediately when the user states a durable preference, personal fact, project fact, environment detail, recurring workflow, correction, or instruction

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
        self.semantic_memory = None
        self.episodic_memory = None
        self.memory_observer = None
        self.memory_context_builder = None
        self.session_id = uuid.uuid4().hex
        self.active_memory_context = ""

        if ttt_mode == "openai":
            from openai import OpenAI

            api_key = get_openai_api_key()
            self.client = OpenAI(api_key=api_key) if api_key else OpenAI()

        if semantic_memory_enabled:
            self.semantic_memory = SemanticMemory(client=self.client)

        if episodic_memory_enabled:
            self.episodic_memory = EpisodicMemory(client=self.client)
            self.memory_observer = MemoryObserver(
                self.episodic_memory,
                client=self.client,
            )

        if self.semantic_memory or self.episodic_memory:
            self.memory_context_builder = MemoryContextBuilder(
                semantic_memory=self.semantic_memory,
                episodic_memory=self.episodic_memory,
                client=self.client,
            )

        self.tool_registry = build_default_registry(self.semantic_memory)
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
        tool_events = []

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
                    self._observe_turn(input, "Hiba: tul sok lepes", tool_events)
                    return "Hiba: Túl sok lépés"

                print(f"Asking model | Messages: {self.messages}")
                try:
                    response = self.ask_model()
                except Exception as e:
                    print(f"Error getting model response: {e}")
                    answer = f"Hiba: {str(e)}"
                    self._observe_turn(input, answer, tool_events)
                    return answer
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
                
                print(f"Jarvis: {assistant_message}")

                self.messages.append(assistant_message)

                print("Model responded: executing tasks")
                if message.tool_calls:
                    tool_events.extend(self.execute_commands(message.tool_calls))
                else:
                    print(f"Final answer given with {steps} steps")
                    answer = message.content or ""
                    self._observe_turn(input, answer, tool_events)
                    return answer
        finally:
            self.active_memory_context = ""

    def _build_memory_context(self, input_text: str) -> str:
        if not self.memory_context_builder:
            return ""

        return self.memory_context_builder.build(input_text)

    def _observe_turn(self, input_text: str, answer: str, tool_events: list[dict]) -> None:
        if not self.memory_observer:
            return

        try:
            self.memory_observer.observe_turn(
                session_id=self.session_id,
                user_text=input_text,
                assistant_text=answer,
                tool_events=tool_events,
            )
        except Exception as exc:
            print(f"Memory observer failed: {exc}")

    def execute_commands(self, tool_calls):
        events = []
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
                print({"role": "tool","tool_call_id": tool_call.id,"content": result[:self.max_query_length],})
                events.append({
                    "name": name,
                    "status": "error",
                    "error": f"Invalid JSON arguments: {e}",
                })
                continue

            tool_result = self.tool_registry.execute(name, args)
            result = tool_result_for_model(name, tool_result)

            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result[:self.max_query_length],
            })
            print({"role": "tool","tool_call_id": tool_call.id,"content": result[:self.max_query_length],})

            events.append({
                "name": name,
                "status": tool_result.status,
                "error": tool_result.error,
            })

        return events

_agent_instance = Agent()


def ask_agent(input_text):
    return _agent_instance.ask_agent(input_text)
