from dataclasses import dataclass

from pydantic import BaseModel
from starlette.requests import Request


@dataclass
class Arguments[TInputs: BaseModel, TContext]:
    request: Request
    inputs: TInputs
    context: TContext
