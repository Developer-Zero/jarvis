import json
import time
import threading


#from backend.robusts import formatJson # Fixing json with robusting
from config import ttt_mode, ttt_model, max_message_history, max_query_length, max_steps
from backend.tools.registry import build_default_registry, tool_result_for_model

SYSTEM_PROMPT = """
You are a Jarvis-like AI assistant.

# CORE ROLE
- Your primary goal is to execute user requests.
- Your behavior is conservative, precise, and controlled.
- Do not generate unnecessary explanations.

# DECISION MAKING
- Internally break down complex tasks into steps when needed
- Never expose hidden reasoning
- You are allowed to act autonomously.
- You are allowed to make assumptions
- Request clerification if the action is critical or destructive

# COMMUNICATION STYLE
- Assistant-like (Jarvis-inspired tone)
- Sarcastic if the user's request is irracional
- No slang, no filler text
- No unnecessary verbosity
- Speak Hungarian
- Adress the user as "Uram"
- Always give a short response

# ERROR HANDLING
- On first failure: retry using an alternative approach.
- On repeated failure: return an readable error report as the final anwser

# OUTPUT FORMAT RULES
- FINAL ANSWERS must ALWAYS be plain text only that can be read alound.
- JSON is ONLY allowed in tool communication.
- No custom characters like '{'
- No links, no file paths
- User will only see the final anwser

# PRIORITY ORDER
1. Correct execution
2. Minimalism
3. Reliability
4. Communication quality


# SYSTEM DESIGN VIEW

This is not a chatbot.

It is a tool-driven execution agent with a natural language interface.
"""

class Agent:
    def __init__(self):
        self.messages = [] # Message history with system prompt
        self.prompt = SYSTEM_PROMPT
        self.tool_registry = build_default_registry()
        self.tools = self.tool_registry.get_openai_schemas()
        
        self.max_history = max_message_history
        self.max_query_length = max_query_length
        self.max_steps = max_steps

        if ttt_mode == "openai":
            from openai import OpenAI
            self.client = OpenAI()
    
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
                response = self.client.chat.completions.create(
                        model=ttt_model,
                        tools=self.tools,
                        tool_choice="auto",
                        messages=([{"role": "system", "content": self.prompt}] + self.get_safe_history()),
                        temperature=0.3
                )
                return response
            except Exception as e:
                print(f"Error calling OpenAI API: {e}")
                raise
        else:
            raise ValueError(f"Unsupported ttt_mode: {ttt_mode}")
    

    def ask_agent(self, input):
        self.messages.append({"role": "user", "content": input})

        steps = 0
        while True:
            steps += 1
            if steps == self.max_steps - 1:
                self.messages.append({"role": "system", "content": "You must give a final answer now. No tool calls allowed."})
            elif steps >= self.max_steps:
                return "Hiba: Túl sok lépés"

            print(f"Asking model | Messages: {self.messages}")
            try:
                response = self.ask_model()
            except Exception as e:
                print(f"Error getting model response: {e}")
                return f"Hiba: {str(e)}"
            message = response.choices[0].message
            
            # Add assistant response with tool_calls to 'messages'
            assistant_message = {
                "role": "assistant",
                "content": message.content or ""
            }

            if message.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    }
                    for tool_call in message.tool_calls
                ]

            self.messages.append(assistant_message)
            
            print("Model responded: executing tasks")
            if message.tool_calls:
                self.execute_commands(message.tool_calls)
            else:
                return message.content



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
                continue

            tool_result = self.tool_registry.execute(name, args)
            result = tool_result_for_model(name, tool_result)

            self.messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result[:self.max_query_length],
            })


# Module-level instance and function for easy import
_agent_instance = Agent()

def ask_agent(input_text):
    """Module-level function to ask the agent"""
    return _agent_instance.ask_agent(input_text)
