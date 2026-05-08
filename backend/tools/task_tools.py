from backend.tasks import TaskError, default_task_store
from backend.tools.base import Tool, ToolResult


def list_tasks() -> ToolResult:
    return ToolResult(status="ok", content=default_task_store.list_tasks())


def create_task(
    event: str,
    prompt: str,
    repeat: bool = False,
    time: str | None = None,
    frequency: str | None = None,
    name: str | None = None,
) -> ToolResult:
    try:
        task = default_task_store.create_task(
            event=event,
            prompt=prompt,
            repeat=repeat,
            time=time,
            frequency=frequency,
            name=name,
        )
    except TaskError as exc:
        return ToolResult(status="error", error=str(exc))

    return ToolResult(status="ok", content=task)


def delete_task(task_id: str) -> ToolResult:
    if default_task_store.delete_task(task_id):
        return ToolResult(status="ok", content="Deleted task")

    return ToolResult(status="error", error="Task not found")


TASK_TOOLS = [
    Tool(
        name="list_tasks",
        description="List all saved Jarvis tasks with their event, schedule, repeat state, prompt, and run metadata.",
        parameters={
            "type": "object",
            "properties": {},
        },
        function=list_tasks,
    ),
    Tool(
        name="create_task",
        description=(
            "Create a saved Jarvis task. Events: on_start runs when Jarvis starts; "
            "on_time runs at a clock time while Jarvis is open; after_time runs after a delay from creation. "
            "For on_time, time should be HH:MM, HH:MM:SS, or an ISO datetime. "
            "For after_time and frequency, use durations like 10m, 2 hours, 01:30:00, or seconds. "
            "If repeat is false, the task is removed after it runs once."
        ),
        parameters={
            "type": "object",
            "properties": {
                "event": {
                    "type": "string",
                    "enum": ["on_start", "on_time", "after_time"],
                },
                "prompt": {"type": "string"},
                "repeat": {"type": "boolean"},
                "time": {"type": "string"},
                "frequency": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["event", "prompt"],
        },
        function=create_task,
    ),
    Tool(
        name="delete_task",
        description="Delete a saved Jarvis task by id.",
        parameters={
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
        function=delete_task,
    ),
]
