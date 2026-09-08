"""
Índice léxico/estrutural dos repositórios — RAG sem LLM.

Varre o código dos repos declarados em `inputs/mapa-servicos.yaml` e extrai
sinais estáticos (rotas HTTP, entidades, códigos de status, campos, stack).
Serve a dois propósitos:

1. **Assertividade do de/para**: o vocabulário real do código entra na pontuação
   das seções do documento (`src/marcar.py`), com peso por IDF.
2. **Assertividade da história**: o artefato passa a dizer o que já existe no
   repo e o que é gap, em vez de descrever tudo como novo.

  python -m src.repo_index --workspace ~/dev/repos
  python -m src.repo_index --show gestao-de-ofertas
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.servicos import load_mapa  # noqa: E402

INDEX_PATH = ROOT / "state" / "repo_index.json"

IGNORE_DIRS = {
    ".git", ".idea", ".vscode", ".gradle", ".terraform", ".next", ".nuxt", ".mvn",
    "node_modules", "target", "build", "dist", "out", "bin", "obj", "vendor",
    "venv", ".venv", "__pycache__", "coverage", "htmlcov", "migrations",
}
CODE_EXTS = {
    ".java", ".kt", ".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".cs", ".rb",
    ".php", ".sql", ".proto", ".yaml", ".yml",
}
MAX_FILE_BYTES = 256 * 1024
MAX_FILES_PER_REPO = 4000

# --- rotas ------------------------------------------------------------------
# base da classe: @RequestMapping("/v1/ofertas") (Spring) / @Controller('ofertas') (Nest)
BASE_PATH_RE = re.compile(
    r'@(?:RequestMapping|Controller)\(\s*(?:value\s*=\s*)?["\']([^"\']*)["\']'
)
# (regex, grupo_metodo|None, grupo_path, usa_base)
ROUTE_PATTERNS: list[tuple[re.Pattern[str], int | None, int, bool]] = [
    # Spring: @GetMapping("/ativas")
    (re.compile(r'@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*)?["\']([^"\']*)'), 1, 2, True),
    (re.compile(r"@(Get|Post|Put|Delete|Patch)Mapping\(\s*\)"), 1, 0, True),
    # Nest: @Get('/vitrine')
    (re.compile(r'@(Get|Post|Put|Delete|Patch)\(\s*["\']([^"\']*)["\']'), 1, 2, True),
    # Express/Fastify: router.get('/ofertas')
    (re.compile(r'\b(?:app|router|api|server)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)'), 1, 2, False),
    # FastAPI: @app.get("/ofertas")
    (re.compile(r'@(?:app|router|bp)\.(get|post|put|delete|patch)\(\s*["\']([^"\']+)'), 1, 2, False),
    # Flask: @app.route("/ofertas")
    (re.compile(r'@(?:app|router|bp)\.route\(\s*["\']([^"\']+)'), None, 1, False),
    # Go (gin/echo/chi): r.GET("/ofertas")
    (re.compile(r'\.(GET|POST|PUT|DELETE|PATCH)\(\s*"([^"]+)"'), 1, 2, False),
]


def _join_path(base: str, rota: str) -> str:
    base = ("/" + base.strip("/")) if base.strip("/") else ""
    rota = rota.strip()
    if rota and not rota.startswith("/"):
        rota = "/" + rota
    if base and rota.startswith(base):
        return rota
    completo = f"{base}{rota}" or "/"
    return re.sub(r"//+", "/", completo)


def _extract_routes(conteudo: str) -> list[str]:
    """`METODO /caminho` já concatenado com a base da classe, quando existir."""
    base_match = BASE_PATH_RE.search(conteudo)
    base = base_match.group(1) if base_match else ""
    achadas: list[str] = []
    for regex, g_metodo, g_path, usa_base in ROUTE_PATTERNS:
        for m in regex.finditer(conteudo):
            rota = (m.group(g_path) if g_path else "") or ""
            if len(rota) > 120:
                continue
            metodo = m.group(g_metodo).upper() if g_metodo else "ANY"
            completo = _join_path(base, rota) if usa_base else _join_path("", rota)
            if completo and completo != "/":
                achadas.append(f"{metodo} {completo}")
    # só a base (controller sem método reconhecido) ainda é informação útil
    if not achadas and base:
        achadas.append(f"ANY {_join_path(base, '')}")
    return achadas

# --- códigos de status -----------------------------------------------------
STATUS_NAME_RES = [
    re.compile(r"HttpStatus(?:Code)?\.([A-Z][A-Z_]{2,})"),
    re.compile(r"http\.Status([A-Z][A-Za-z]+)"),
]
STATUS_NUM_RES = [
    re.compile(r"ResponseEntity\.status\(\s*(\d{3})"),
    re.compile(r"(?:sendStatus|statusCode|status_code|status)\s*[=(]\s*(\d{3})"),
    re.compile(r"HTTPException\(\s*status_code\s*=\s*(\d{3})"),
]
STATUS_NAMES = {
    "OK": 200, "CREATED": 201, "ACCEPTED": 202, "NOCONTENT": 204, "NO_CONTENT": 204,
    "BADREQUEST": 400, "BAD_REQUEST": 400, "UNAUTHORIZED": 401,
    "PAYMENTREQUIRED": 402, "PAYMENT_REQUIRED": 402, "FORBIDDEN": 403,
    "NOTFOUND": 404, "NOT_FOUND": 404, "CONFLICT": 409,
    "PRECONDITIONFAILED": 412, "PRECONDITION_FAILED": 412,
    "UNPROCESSABLEENTITY": 422, "UNPROCESSABLE_ENTITY": 422,
    "TOOMANYREQUESTS": 429, "TOO_MANY_REQUESTS": 429,
    "INTERNALSERVERERROR": 500, "INTERNAL_SERVER_ERROR": 500,
    "SERVICEUNAVAILABLE": 503, "SERVICE_UNAVAILABLE": 503,
    "GATEWAYTIMEOUT": 504, "GATEWAY_TIMEOUT": 504,
}

# --- classes, tabelas, campos ---------------------------------------------
CLASS_RES = [
    re.compile(r"\b(?:public\s+|export\s+)?(?:final\s+|abstract\s+)*class\s+([A-Z][A-Za-z0-9_]+)"),
    re.compile(r"\b(?:export\s+)?interface\s+([A-Z][A-Za-z0-9_]+)"),
    re.compile(r"\brecord\s+([A-Z][A-Za-z0-9_]+)\s*\("),
    re.compile(r"\btype\s+([A-Z][A-Za-z0-9_]+)\s+struct"),
]
TABLE_RES = [
    re.compile(r'@Table\(\s*(?:name\s*=\s*)?["\']([^"\']+)'),
    re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"']?(\w+)", re.I),
]
FIELD_RES = [
    re.compile(r"\bprivate\s+(?:final\s+)?[\w<>\[\],.\s]+?\s+([a-z][A-Za-z0-9_]*)\s*[;=]"),
    re.compile(
        r"^\s*(?:readonly\s+)?([a-z][A-Za-z0-9_]{2,})\s*\??:\s*"
        r"(?:string|number|boolean|Date|str|int|float|bool|Decimal|BigDecimal)",
        re.M,
    ),
]
OPENAPI_PATH_RE = re.compile(r"^\s{2,}(/[\w{}\-/.]*)\s*:\s*$", re.M)

CLASS_SUFFIXES = (
    "Controller", "Service", "ServiceImpl", "Repository", "Entity", "Dto", "DTO",
    "Request", "Response", "Mapper", "Config", "Configuration", "Handler",
    "Exception", "Test", "Tests", "Factory", "Builder", "Client", "Adapter",
    "UseCase", "Port", "Gateway", "Resource", "Facade", "Validator",
)
# termos genéricos de engenharia: não distinguem serviço, então saem do vocabulário
STOP_TERMS = {
    "api", "app", "application", "base", "bean", "body", "build", "cache", "class",
    "client", "cloud", "code", "common", "config", "configuration", "controller",
    "core", "data", "date", "default", "delete", "domain", "dto", "entity", "enum",
    "error", "event", "exception", "factory", "field", "file", "filter", "get",
    "handler", "header", "health", "http", "https", "impl", "index", "info", "init",
    "input", "integration", "interface", "internal", "item", "java", "json", "key",
    "lib", "list", "log", "logger", "main", "map", "mapper", "message", "meta",
    "method", "model", "module", "name", "new", "null", "number", "object", "output",
    "page", "param", "params", "patch", "path", "port", "post", "put", "query",
    "record", "repository", "request", "resource", "response", "rest", "result",
    "schema", "server", "service", "src", "start", "state", "static", "status",
    "string", "system", "table", "task", "test", "tests", "text", "time", "type",
    "update", "url", "user", "util", "utils", "validate", "validator", "value",
    "version", "web", "worker", "id", "uuid",
}


def _split_camel(name: str) -> list[str]:
    return [p.lower() for p in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+", name)]


def _strip_suffix(name: str) -> str:
    for suf in sorted(CLASS_SUFFIXES, key=len, reverse=True):
        if name.endswith(suf) and len(name) > len(suf):
            return name[: -len(suf)]
    return name


def _detect_stack(repo: Path) -> list[str]:
    stack: list[str] = []
    checks = {
        "pom.xml": "java/maven",
        "build.gradle": "java/gradle",
        "build.gradle.kts": "kotlin/gradle",
        "package.json": "node",
        "go.mod": "go",
        "requirements.txt": "python",
        "pyproject.toml": "python",
        "Gemfile": "ruby",
        "Dockerfile": "docker",
    }
    for arquivo, rotulo in checks.items():
        if (repo / arquivo).exists():
            stack.append(rotulo)
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            deps = json.loads(pkg.read_text(encoding="utf-8", errors="ignore"))
            todas = {**(deps.get("dependencies") or {}), **(deps.get("devDependencies") or {})}
            for marca, rotulo in (
                ("@nestjs/core", "nestjs"), ("express", "express"), ("next", "nextjs"),
                ("react", "react"), ("fastify", "fastify"), ("@angular/core", "angular"),
            ):
                if marca in todas:
                    stack.append(rotulo)
        except (json.JSONDecodeError, OSError):
            pass
    if (repo / "src" / "main" / "java").exists():
        stack.append("spring-layout")
    return sorted(set(stack))


def index_repo(repo: Path) -> dict[str, Any]:
    """Extrai sinais estáticos de um repositório. Sem execução de código."""
    rotas: Counter[str] = Counter()
    status: Counter[str] = Counter()
    classes: Counter[str] = Counter()
    tabelas: Counter[str] = Counter()
    campos: Counter[str] = Counter()
    termos: Counter[str] = Counter()
    arquivos = 0

    for path in repo.rglob("*"):
        if arquivos >= MAX_FILES_PER_REPO:
            break
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in CODE_EXTS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            conteudo = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        arquivos += 1

        for rota in _extract_routes(conteudo):
            rotas[rota] += 1
            for seg in re.split(r"[/{}\-_.]", rota.split(" ", 1)[-1]):
                if seg and not seg.isdigit():
                    termos[seg.lower()] += 1

        if path.suffix.lower() in {".yaml", ".yml"} and "paths:" in conteudo:
            for m in OPENAPI_PATH_RE.finditer(conteudo):
                rotas[f"SPEC {m.group(1)}"] += 1
                for seg in re.split(r"[/{}\-_.]", m.group(1)):
                    if seg and not seg.isdigit():
                        termos[seg.lower()] += 1

        for regex in STATUS_NAME_RES:
            for m in regex.finditer(conteudo):
                nome = m.group(1).upper()
                num = STATUS_NAMES.get(nome.replace("_", "")) or STATUS_NAMES.get(nome)
                if num:
                    status[str(num)] += 1
        for regex in STATUS_NUM_RES:
            for m in regex.finditer(conteudo):
                status[m.group(1)] += 1

        for regex in CLASS_RES:
            for m in regex.finditer(conteudo):
                nome = m.group(1)
                classes[nome] += 1
                for tok in _split_camel(_strip_suffix(nome)):
                    termos[tok] += 1
        for regex in TABLE_RES:
            for m in regex.finditer(conteudo):
                tabelas[m.group(1).lower()] += 1
                for tok in re.split(r"[_\-]", m.group(1).lower()):
                    termos[tok] += 1
        for regex in FIELD_RES:
            for m in regex.finditer(conteudo):
                campo = m.group(1)
                campos[campo] += 1
                for tok in _split_camel(campo):
                    termos[tok] += 1

        for tok in _split_camel(path.stem):
            termos[tok] += 1

    limpos = {
        t: n for t, n in termos.items() if len(t) >= 4 and t not in STOP_TERMS and not t.isdigit()
    }
    return {
        "arquivos_lidos": arquivos,
        "stack": _detect_stack(repo),
        "rotas": [r for r, _ in rotas.most_common(60)],
        "status": sorted(status, key=lambda s: -status[s]),
        "classes": [c for c, _ in classes.most_common(40)],
        "tabelas": sorted(tabelas),
        "campos": [c for c, _ in campos.most_common(40)],
        "termos": dict(sorted(limpos.items(), key=lambda kv: -kv[1])[:150]),
    }


def index_workspace(workspace: Path, mapa: dict[str, Any]) -> dict[str, Any]:
    servicos: dict[str, Any] = {}
    for sid, meta in (mapa.get("servicos") or {}).items():
        repos_idx: dict[str, Any] = {}
        for nome in meta.get("repos") or []:
            caminho = workspace / nome
            if not caminho.is_dir():
                continue
            repos_idx[nome] = index_repo(caminho)
        if not repos_idx:
            continue

        agregado_termos: Counter[str] = Counter()
        rotas: list[str] = []
        status: list[str] = []
        classes: list[str] = []
        campos: list[str] = []
        tabelas: list[str] = []
        stack: list[str] = []
        for nome, idx in repos_idx.items():
            agregado_termos.update(idx["termos"])
            rotas.extend(f"{nome}: {r}" for r in idx["rotas"])
            status.extend(idx["status"])
            classes.extend(idx["classes"])
            campos.extend(idx["campos"])
            tabelas.extend(idx["tabelas"])
            stack.extend(idx["stack"])
        servicos[sid] = {
            "repos": repos_idx,
            "termos": dict(agregado_termos.most_common(200)),
            "rotas": rotas[:80],
            "status": sorted(set(status), key=int),
            "classes": sorted(set(classes))[:60],
            "campos": sorted(set(campos))[:60],
            "tabelas": sorted(set(tabelas))[:40],
            "stack": sorted(set(stack)),
        }
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "workspace": str(workspace),
        "servicos": servicos,
    }


def load_index(path: Path | None = None) -> dict[str, Any] | None:
    p = path or INDEX_PATH
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if data.get("servicos") else None


def service_terms(index: dict[str, Any] | None, sid: str) -> dict[str, int]:
    if not index:
        return {}
    return ((index.get("servicos") or {}).get(sid) or {}).get("termos") or {}


def service_evidence(index: dict[str, Any] | None, sid: str) -> dict[str, Any]:
    if not index:
        return {}
    return dict(((index.get("servicos") or {}).get(sid) or {}))


def save_index(data: dict[str, Any], path: Path | None = None) -> Path:
    p = path or INDEX_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def main() -> None:
    p = argparse.ArgumentParser(description="Índice léxico dos repos (RAG sem LLM)")
    p.add_argument("--workspace", metavar="DIR", help="pasta com todos os repos")
    p.add_argument("--mapa", metavar="FILE")
    p.add_argument("--out", metavar="FILE", help=f"default: {INDEX_PATH}")
    p.add_argument("--show", metavar="SERVICE_ID", help="resumo de um serviço já indexado")
    args = p.parse_args()

    if args.show:
        index = load_index(Path(args.out) if args.out else None)
        if not index:
            raise SystemExit("erro: índice ausente. rode --workspace primeiro")
        ev = service_evidence(index, args.show)
        if not ev:
            raise SystemExit(f"erro: serviço {args.show} não está no índice")
        print(json.dumps({k: v for k, v in ev.items() if k != "repos"}, ensure_ascii=False, indent=2))
        return

    if not args.workspace:
        raise SystemExit("erro: informe --workspace DIR ou --show SERVICE_ID")
    ws = Path(args.workspace).expanduser()
    if not ws.is_dir():
        raise SystemExit(f"erro: workspace inválido: {ws}")

    mapa = load_mapa(Path(args.mapa) if args.mapa else None)
    if not mapa:
        raise SystemExit(
            "erro: mapa-servicos.yaml ausente.\n"
            "      gere com: ./scripts/scan-repos.sh --workspace " + str(ws)
        )

    data = index_workspace(ws, mapa)
    destino = save_index(data, Path(args.out) if args.out else None)
    resumo = {
        "indice": str(destino),
        "servicos": {
            sid: {
                "repos": list(ev["repos"].keys()),
                "arquivos": sum(r["arquivos_lidos"] for r in ev["repos"].values()),
                "rotas": len(ev["rotas"]),
                "status": ev["status"],
                "termos": len(ev["termos"]),
                "stack": ev["stack"],
            }
            for sid, ev in (data.get("servicos") or {}).items()
        },
    }
    print(json.dumps(resumo, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
