"""JSON-lines bridge for an agent host; this is not an MCP server or an LLM client."""
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
from adapter import Adapter, run_cases, run_static_workflow, validate, validate_workflow
from knowledge import search_knowledge


def execute(request):
    name = request["name"]
    arguments = request["arguments"]
    if name == "search_engineering_knowledge":
        return search_knowledge(arguments["query"])
    if name == "validate_static_plan":
        return {"state": "validated_config_only", "config": validate(arguments["config"])}
    if name not in ("mechanical_status", "inspect_project", "review_static_model", "run_static_cases", "run_static_workflow"):
        raise ValueError("Unknown tool")
    if name == "inspect_project":
        project = Path(arguments["project"]).resolve()
        if not project.is_file() or project.suffix.lower() != ".mechdat":
            raise ValueError("An existing standalone .mechdat is required")
    elif name == "review_static_model":
        project = Path(arguments["project"]).resolve()
        if not project.is_file() or project.suffix.lower() != ".mechdat":
            raise ValueError("An existing standalone .mechdat is required")
    elif name == "run_static_cases":
        validate(arguments["config"])
    elif name == "run_static_workflow":
        validate_workflow(arguments)
    adapter = Adapter()
    try:
        if name == "mechanical_status":
            return {"connected": True, "session": str(adapter.session),
                    "model": adapter.call("inspect", project=None)}
        if name == "inspect_project":
            return adapter.call("inspect", project=str(project))
        if name == "review_static_model":
            return adapter.call("review", project=str(project),
                analysis_name=arguments["analysis_name"], force_name=arguments["force_name"])
        if name == "run_static_workflow":
            return run_static_workflow(adapter, arguments)
        return run_cases(adapter, arguments["config"], Path(arguments["output_directory"]))
    finally:
        adapter.close()


def main():
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            with redirect_stdout(sys.stderr):
                result = execute(request)
            response = {"id": request.get("id"), "ok": True, "result": result}
        except Exception as error:
            response = {"id": request.get("id") if isinstance(request, dict) else None,
                        "ok": False, "error": str(error)}
        print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
