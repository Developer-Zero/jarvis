import os
from docx import Document
from pptx import Presentation
from openpyxl import load_workbook

from backend.tools.base import Tool, ToolResult


TEXT_EXTENSIONS = {
    "txt", "py", "json", "md", "log", "js", "ts",
    "html", "css", "xml", "csv", "yml", "yaml", "ini", "cfg"
}


def get_extension(path: str) -> str:
    return path.lower().split(".")[-1]


def read_text(path: str) -> ToolResult:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return ToolResult(status="ok", content=file.read())
    except UnicodeDecodeError:
        return ToolResult(status="error", error="UTF-8 decode error")


def read_docx(path: str) -> ToolResult:
    doc = Document(path)
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return ToolResult(status="ok", content=text)


def read_pptx(path: str) -> ToolResult:
    prs = Presentation(path)
    text = []

    for slide in prs.slides:
        for shape in slide.shapes:
            if hasattr(shape, "text") and shape.text:
                text.append(shape.text)

    return ToolResult(status="ok", content="\n".join(text))


def read_xlsx(path: str) -> ToolResult:
    wb = load_workbook(path, data_only=True)
    result = {}

    for sheet_name in wb.sheetnames:
        sheet = wb[sheet_name]
        rows = []

        for row in sheet.iter_rows(values_only=True):
            rows.append(["" if cell is None else str(cell) for cell in row])

        result[sheet_name] = rows

    return ToolResult(status="ok", content=result)


def read_file(path: str) -> ToolResult:
    if not os.path.exists(path):
        return ToolResult(status="error", error="File path does not exist")

    ext = get_extension(path)

    if ext in TEXT_EXTENSIONS:
        return read_text(path)

    if ext == "docx":
        return read_docx(path)

    if ext == "pptx":
        return read_pptx(path)

    if ext == "xlsx":
        return read_xlsx(path)

    return ToolResult(status="error", error=f"Unsupported file type: .{ext}")


def list_files(path: str) -> ToolResult:
    if not os.path.exists(path):
        return ToolResult(status="error", error="Directory does not exist")

    if not os.path.isdir(path):
        return ToolResult(status="error", error="Path is not a directory")

    return ToolResult(status="ok", content=os.listdir(path))


FILE_TOOLS = [
    Tool(
        name="read_file",
        description="Read the content of a local file. Supports text, docx, pptx and xlsx files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
        function=read_file,
    ),
    Tool(
        name="list_files",
        description="List files and folders inside a local directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
        },
        function=list_files,
    ),
]