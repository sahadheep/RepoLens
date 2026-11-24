from pydantic import BaseModel
from typing import List, Optional


class AnalyzeRequest(BaseModel):
    url: str
    sync: bool = False


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SymbolInfo(BaseModel):
    kind: str
    name: str
    start_line: int
    end_line: int
    id: Optional[str] = None
    enclosing_class: Optional[str] = None
    signature: Optional[str] = None
    fields: List[str] = []
    calls: List[str] = []


class FileInfo(BaseModel):
    path: str
    language: str
    symbols: List[SymbolInfo]
    imports: List[str]


class StructureResponse(BaseModel):
    repo_id: int
    files: List[FileInfo]


class ImportantFile(BaseModel):
    path: str
    score: float
    rank: int


class ImportantFilesResponse(BaseModel):
    repo_id: int
    files: List[ImportantFile]


class SearchResult(BaseModel):
    file_path: str
    symbol_name: str
    kind: str
    start_line: int
    end_line: int
    score: float
    snippet: str


class SearchResponse(BaseModel):
    repo_id: int
    query: str
    results: List[SearchResult]


class AnalyzeResponse(BaseModel):
    repo_id: int
    url: str
    status: str = "READY"
    files_processed: int = 0
    message: str = ""


class RepoStatusResponse(BaseModel):
    repo_id: int
    url: str
    status: str
    progress: int
    files_processed: int = 0
    error_message: Optional[str] = None
    message: Optional[str] = None


class CallEdgeModel(BaseModel):
    caller: str
    callee: str


class RepoDumpResponse(BaseModel):
    repo_id: int
    repo_root: str
    files: List[FileInfo]
    call_graph: List[CallEdgeModel]


class GraphResponse(BaseModel):
    repo_id: int
    nodes: List[dict]
    edges: List[dict]
