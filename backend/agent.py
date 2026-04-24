import json
import time
import threading


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

SYSTEM_TOOLS = [
{
    "type": "function",
    "function": {
        "name": "open_url",
        "description": "Open a website in the default browser",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string"
                }
            },
            "required": ["url"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "open_file",
        "description": "Launch a file at a given path",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                }
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "set_volume",
        "description": "Change system volume",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down"]
                },
                "amount": {
                    "type": "number",
                    "description": "Change amount in percentages"
                }
            },
            "required": ["direction", "amount"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "wait",
        "description": "Pause execution for a given number of seconds",
        "parameters": {
            "type": "object",
            "properties": {
                    "seconds": {
                        "type": "number"
                    }
                },
            "required": ["seconds"]
        }
    }
},
# Query
{
    "type": "function",
    "function": {
        "name": "list_files",
        "description": "List files and folders in a given directory path",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                }
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read the content of a file as text",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string"
                }
            },
            "required": ["path"]
        }
    }
}
]


#from backend.robusts import formatJson # Fixing json with robusting
from config import ttt_mode, ttt_model, max_message_history, max_query_length, max_steps
import backend.commands as commands

class Agent:
    def __init__(self):
        self.messages = [] # Message history with system prompt
        self.prompt = SYSTEM_PROMPT
        self.tools = SYSTEM_TOOLS
        
        self.max_history = max_message_history
        self.max_query_length = max_query_length
        self.max_steps = max_steps

        if ttt_mode == "openai":
            from openai import OpenAI
            self.client = OpenAI()
    
    def ask_model(self):
        if ttt_mode == "openai":
            try:
                response = self.client.chat.completions.create(
                        model=ttt_model,
                        tools=self.tools,
                        tool_choice="auto",
                        messages=([{"role": "system", "content": f"{self.prompt}"}] + self.messages[-self.max_history:]),
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
                return "Hiba: Lépések száma túllépte a maximális számot"

            print(f"Asking model | Messages: {self.messages}")
            try:
                response = self.ask_model()
            except Exception as e:
                print(f"Error getting model response: {e}")
                return f"Hiba: {str(e)}"
            message = response.choices[0].message
            
            # Add assistant response with tool_calls to 'messages'
            assistant_message = {"role": "assistant", "content": message.content or ""}
            if message.tool_calls:
                assistant_message["tool_calls"] = message.tool_calls
            self.messages.append(assistant_message)
            
            print("Model responded: executing tasks")
            if message.tool_calls:
                self.execute_commands(message.tool_calls)
            else:
                return message.content



    def execute_commands(self, tool_calls):
        if tool_calls:
            for tool in tool_calls:
                name = tool.function.name
                args = json.loads(tool.function.arguments)
                result = ""
                
                if name == "open_url":
                    commands.open_url(args["url"])
                    result = json.dumps({"name": name, "url": args["url"]})
                elif name == "set_volume":
                    commands.set_volume(args["direction"], args["amount"])
                    result = json.dumps({"name": name, "direction": args["direction"], "amount": args["amount"]})
                elif name == "wait":
                    time.sleep(args["seconds"])
                    result = json.dumps({"name": name, "seconds": args["seconds"]})
                elif name == "open_file":
                    message = commands.open_file(args["path"])
                    if message["status"] == "error":
                        result = json.dumps({"name": name, "path": args["path"], "status": "error", "error": message["content"]})
                    else:
                        result = json.dumps({"name": name, "path": args["path"], "status": "ok"})
                elif name == "read_file":
                    message = commands.read_file(args["path"])
                    if message["status"] == "error":
                        result = json.dumps({"name": name, "path": args["path"], "status": "error", "error": message["content"]})
                    else:
                        result = json.dumps({"name": name, "path": args["path"], "status": "ok", "query": message["content"]})
                elif name == "list_files":
                    message = commands.list_files(args["path"])
                    if message["status"] == "error":
                        result = json.dumps({"name": name, "path": args["path"], "status": "error", "error": message["content"]})
                    else:
                        result = json.dumps({"name": name, "path": args["path"], "status": "ok", "query": message["content"]})
                else:
                    result = json.dumps({"name": name, "status": "error", "error": "Requested tool doesn't exist"})

                if result:
                    self.messages.append({"role": "tool", "tool_call_id": tool.id, "content": result[:self.max_query_length]})


# Module-level instance and function for easy import
_agent_instance = Agent()

def ask_agent(input_text):
    """Module-level function to ask the agent"""
    return _agent_instance.ask_agent(input_text)
