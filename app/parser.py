from pathlib import Path
from dataclasses import dataclass, field

import tree_sitter_python as tspython
import tree_sitter_javascript as tsjavascript
import tree_sitter_java as tsjava
from tree_sitter import Language, Parser


PY_LANGUAGE = Language(tspython.language())
JS_LANGUAGE = Language(tsjavascript.language())
JAVA_LANGUAGE = Language(tsjava.language())


@dataclass
class Symbol:
    kind: str
    name: str
    start_line: int
    end_line: int
    source: str
    id: str | None = None
    enclosing_class: str | None = None
    signature: str | None = None
    fields: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


@dataclass
class FileAnalysis:
    path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


def _make_parser(language: Language) -> Parser:
    return Parser(language)


def _node_text(node, source_bytes: bytes) -> str:
    return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _first_named_child_text(node, kind: str, source_bytes: bytes) -> str | None:
    for child in node.children:
        if child.type == kind:
            return _node_text(child, source_bytes)
    return None


def _parse_python(source: str) -> tuple[list[Symbol], list[str]]:
    parser = _make_parser(PY_LANGUAGE)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    symbols: list[Symbol] = []
    imports: list[str] = []

    def visit(node, current_class: str | None = None, depth: int = 0):
        if depth > 3:
            return

        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            sig_line = source.splitlines()[node.start_point[0]].strip() if node.start_point[0] < len(source.splitlines()) else f"def {name}()"
            sym_id = f"{current_class}#{name}" if current_class else name
            symbols.append(Symbol(
                id=sym_id,
                kind="function" if not current_class else "method",
                name=name,
                enclosing_class=current_class,
                signature=sig_line,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source=_node_text(node, source_bytes),
            ))

        elif node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            symbols.append(Symbol(
                id=name,
                kind="class",
                name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source=_node_text(node, source_bytes),
            ))
            for child in node.children:
                visit(child, current_class=name, depth=depth + 1)
            return

        elif node.type == "import_statement":
            for child in node.children:
                if child.type in ("dotted_name", "aliased_import"):
                    raw = _node_text(child, source_bytes)
                    imports.append(raw.split(" as ")[0].strip())

        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            if module_node:
                imports.append(_node_text(module_node, source_bytes))

        for child in node.children:
            visit(child, current_class=current_class, depth=depth)

    visit(root)
    return symbols, imports


def _parse_javascript(source: str) -> tuple[list[Symbol], list[str]]:
    parser = _make_parser(JS_LANGUAGE)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    symbols: list[Symbol] = []
    imports: list[str] = []

    def visit(node, current_class: str | None = None, depth: int = 0):
        if depth > 3:
            return

        if node.type == "function_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            symbols.append(Symbol(
                id=f"{current_class}#{name}" if current_class else name,
                kind="function",
                name=name,
                enclosing_class=current_class,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source=_node_text(node, source_bytes),
            ))

        elif node.type == "class_declaration":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            symbols.append(Symbol(
                id=name,
                kind="class",
                name=name,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source=_node_text(node, source_bytes),
            ))
            for child in node.children:
                visit(child, current_class=name, depth=depth + 1)
            return

        elif node.type == "method_definition":
            name_node = node.child_by_field_name("name")
            name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            symbols.append(Symbol(
                id=f"{current_class}#{name}" if current_class else name,
                kind="function",
                name=name,
                enclosing_class=current_class,
                start_line=node.start_point[0] + 1,
                end_line=node.end_point[0] + 1,
                source=_node_text(node, source_bytes),
            ))

        elif node.type in ("lexical_declaration", "variable_declaration"):
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")
                    if name_node and value_node and value_node.type in (
                        "arrow_function", "function_expression"
                    ):
                        name = _node_text(name_node, source_bytes)
                        symbols.append(Symbol(
                            id=name,
                            kind="function",
                            name=name,
                            start_line=child.start_point[0] + 1,
                            end_line=child.end_point[0] + 1,
                            source=_node_text(child, source_bytes),
                        ))

        elif node.type == "import_statement":
            source_node = node.child_by_field_name("source")
            if source_node:
                raw = _node_text(source_node, source_bytes).strip("'\"")
                imports.append(raw)

        elif node.type == "call_expression":
            fn = node.child_by_field_name("function")
            args = node.child_by_field_name("arguments")
            if fn and _node_text(fn, source_bytes) == "require" and args:
                for arg in args.children:
                    if arg.type == "string":
                        raw = _node_text(arg, source_bytes).strip("'\"")
                        imports.append(raw)

        for child in node.children:
            visit(child, current_class=current_class, depth=depth)

    visit(root)
    return symbols, imports


def _parse_java(source: str) -> tuple[list[Symbol], list[str]]:
    parser = _make_parser(JAVA_LANGUAGE)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    symbols: list[Symbol] = []
    imports: list[str] = []
    package_name = ""

    for child in root.children:
        if child.type == "package_declaration":
            for sub in child.children:
                if sub.type in ("scoped_identifier", "identifier"):
                    package_name = _node_text(sub, source_bytes).strip()
        elif child.type == "import_declaration":
            for sub in child.children:
                if sub.type in ("scoped_identifier", "identifier"):
                    imports.append(_node_text(sub, source_bytes).strip())

    import_map = {}
    for imp in imports:
        simple = imp.split(".")[-1]
        import_map[simple] = imp

    for child in root.children:
        if child.type in ("class_declaration", "interface_declaration", "record_declaration"):
            name_node = child.child_by_field_name("name")
            class_name = _node_text(name_node, source_bytes) if name_node else "<anonymous>"
            full_class_id = f"{package_name}.{class_name}" if package_name else class_name

            fields: list[str] = []
            field_types: dict[str, str] = {}
            body_node = child.child_by_field_name("body")

            if body_node:
                for member in body_node.children:
                    if member.type == "field_declaration":
                        field_text = _node_text(member, source_bytes).strip()
                        fields.append(field_text)

                        type_node = member.child_by_field_name("type")
                        declarator = member.child_by_field_name("declarator")
                        if type_node and declarator:
                            t_name = _node_text(type_node, source_bytes).strip()
                            v_name = _node_text(declarator.child_by_field_name("name") or declarator, source_bytes).strip()
                            field_types[v_name] = t_name

                symbols.append(Symbol(
                    id=full_class_id,
                    kind="class",
                    name=class_name,
                    start_line=child.start_point[0] + 1,
                    end_line=child.end_point[0] + 1,
                    source=_node_text(child, source_bytes),
                    fields=fields,
                ))

                for member in body_node.children:
                    if member.type in ("method_declaration", "constructor_declaration"):
                        m_name_node = member.child_by_field_name("name")
                        m_name = _node_text(m_name_node, source_bytes) if m_name_node else "<init>"

                        m_body = member.child_by_field_name("body")
                        if m_body:
                            sig_bytes = source_bytes[member.start_byte:m_body.start_byte]
                            signature = sig_bytes.decode("utf-8", errors="replace").strip()
                        else:
                            signature = _node_text(member, source_bytes).strip().rstrip(";")

                        params_node = member.child_by_field_name("parameters")
                        param_types = []
                        if params_node:
                            for param in params_node.children:
                                if param.type == "formal_parameter":
                                    p_type = param.child_by_field_name("type")
                                    if p_type:
                                        param_types.append(_node_text(p_type, source_bytes).strip())
                        param_str = ",".join(param_types)
                        method_id = f"{full_class_id}#{m_name}({param_str})"

                        calls: list[str] = []
                        if m_body:
                            def find_calls(node):
                                if node.type == "method_invocation":
                                    call_name_node = node.child_by_field_name("name")
                                    call_name = _node_text(call_name_node, source_bytes) if call_name_node else ""
                                    obj_node = node.child_by_field_name("object")
                                    obj_name = _node_text(obj_node, source_bytes) if obj_node else ""

                                    target_class = ""
                                    if obj_name in field_types:
                                        raw_type = field_types[obj_name]
                                        target_class = import_map.get(raw_type, f"{package_name}.{raw_type}" if package_name else raw_type)
                                    elif obj_name in import_map:
                                        target_class = import_map[obj_name]
                                    elif obj_name == "this" or not obj_name:
                                        target_class = full_class_id
                                    else:
                                        target_class = obj_name

                                    callee_id = f"{target_class}#{call_name}" if target_class else call_name
                                    if callee_id not in calls:
                                        calls.append(callee_id)

                                for c in node.children:
                                    find_calls(c)

                            find_calls(m_body)

                        symbols.append(Symbol(
                            id=method_id,
                            kind="method",
                            name=m_name,
                            enclosing_class=full_class_id,
                            signature=signature,
                            start_line=member.start_point[0] + 1,
                            end_line=member.end_point[0] + 1,
                            source=_node_text(member, source_bytes),
                            calls=calls,
                        ))

    return symbols, imports


def parse_file(file_path: Path, repo_root: Path) -> FileAnalysis | None:
    lang_map = {".py": "python", ".js": "javascript", ".java": "java"}
    language = lang_map.get(file_path.suffix.lower())
    if not language:
        return None

    try:
        source = file_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[PARSER] Could not read {file_path}: {e}")
        return None

    if len(source.strip()) < 5:
        return None

    try:
        if language == "python":
            symbols, imports = _parse_python(source)
        elif language == "javascript":
            symbols, imports = _parse_javascript(source)
        elif language == "java":
            symbols, imports = _parse_java(source)
        else:
            return None
    except Exception as e:
        print(f"[PARSER] Parse error in {file_path}: {e}")
        return None

    rel_path = str(file_path.relative_to(repo_root))

    return FileAnalysis(
        path=rel_path,
        language=language,
        symbols=symbols,
        imports=imports,
    )
