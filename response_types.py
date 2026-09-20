from pydantic import BaseModel, Field
from typing import Optional, List

class CodeBlock(BaseModel):
    language: str = ""
    code: str
    label: str = ""

class AssistantResponse(BaseModel):
    success: bool = True
    intent: str = "conversation"
    message: str
    spoken_text: str = ""
    code_blocks: List[CodeBlock] = Field(default_factory=list)
    actions_taken: List[dict] = Field(default_factory=list)
    error: Optional[str] = None
