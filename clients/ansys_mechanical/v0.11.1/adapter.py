"""Local, structured tool adapter for Mechanical 2025 R2. No LLM credentials required."""
import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
from datetime import datetime
import copy
import tempfile
import shutil
from loads import (ENTITY_TYPES, MECHANICAL_CLASS, REACTION_CLASSES, UNITS, VALUE_FIELDS, validate_load)
from verification import RULE_VERSION, validate_verification, compare_levels, evaluate
from environment_manager import digest, find_ansys_executable

# exe lookup is lazy: probing the filesystem at import time is pure overhead in
# the short-lived worker processes spawned by api_core / visual_selection.
HERE = Path(__file__).resolve().parent
SCRIPT_FILES = ("mechanical_loads.py", "mechanical_tools.py")
_TABLES = {"load_class": MECHANICAL_CLASS, "scope_type": ENTITY_TYPES, "value_field": VALUE_FIELDS,
           "unit": UNITS, "reaction_class": REACTION_CLASSES}
_SOURCE_CACHE = {}


def script_parts():
    """Fixed script text sent to Mechanical, rebuilt only when a fragment changes.

    Returns (header, body): the request payload must be injected between them.
    The load tables travel as JSON so loads.py stays the only place where a load
    type is defined; user values also remain JSON data, never executable code.
    """
    paths = [HERE / name for name in SCRIPT_FILES]
    try:
        stamp = tuple(path.stat().st_mtime_ns for path in paths)
    except OSError:
        stamp = None
    if _SOURCE_CACHE.get("stamp") != stamp or "header" not in _SOURCE_CACHE:
        header = ["import json\n", "TABLES = json.loads(" + repr(json.dumps(_TABLES)) + ")\n"]
        header += ["{0} = TABLES['{1}']\n".format(name, key) for name, key in
            (("LOAD_CLASSES", "load_class"), ("SCOPE_TYPES", "scope_type"),
             ("VALUE_FIELDS", "value_field"), ("UNITS", "unit"), ("REACTION_CLASSES", "reaction_class"))]
        _SOURCE_CACHE.update(stamp=stamp, header="".join(header),
            body="\n".join(path.read_text(encoding="utf-8") for path in paths))
    return _SOURCE_CACHE["header"], _SOURCE_CACHE["body"]


def validate(config):
    allowed = {"project", "analysis_name", "force_name", "cases"}
    if set(config) != allowed:
        raise ValueError("Config requires exactly: " + ", ".join(sorted(allowed)))
    project = Path(config["project"]).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".mechdat":
        raise ValueError("Supply an existing standalone .mechdat template; .wbpj is not supported yet.")
    for key in ("analysis_name", "force_name"):
        if not isinstance(config[key], str) or not config[key].strip():
            raise ValueError(key + " must be a nonempty, exact object name")
    cases = config["cases"]
    if not isinstance(cases, list) or not 1 <= len(cases) <= 20:
        raise ValueError("cases must contain 1 to 20 load cases")
    seen = set()
    for case in cases:
        if set(case) != {"name", "force_N"}:
            raise ValueError("Each case requires name and force_N only")
        name = case["name"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise ValueError("Case name must be 1-40 ASCII letters, digits, underscores or hyphens")
        if name.upper() in {"CON", "PRN", "AUX", "NUL"} or re.fullmatch(r"(?:COM|LPT)[1-9]", name.upper()):
            raise ValueError("Windows reserved case name")
        if name.lower() in seen:
            raise ValueError("Case names must be unique ignoring case")
        seen.add(name.lower())
        force = case["force_N"]
        if not isinstance(force, list) or len(force) != 3:
            raise ValueError("force_N must be [Fx, Fy, Fz] in global axes, in N")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in force):
            raise ValueError("Force components must be finite numbers")
    return {**config, "project": str(project)}


def validate_workflow(config):
    required = {"project", "analysis_name", "support_name", "support_face_ids",
        "force_name", "mesh_element_size_mm", "output_directory"}
    required.add("human_confirmation")
    if "load" not in config:required.update({"force_face_ids","force_N"})
    if not required.issubset(config) or set(config) - required - {"verification","load","force_face_ids","force_N"}:
        raise ValueError("Workflow requires exactly: " + ", ".join(sorted(required)))
    validate_verification(config.get("verification", {}))
    project = Path(config["project"]).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".mechdat":
        raise ValueError("首版工作流要求已有的独立 .mechdat 模型")
    for key in ("analysis_name", "support_name", "force_name"):
        if not isinstance(config[key], str) or not config[key].strip() or len(config[key]) > 100:
            raise ValueError(key + " must be a nonempty name up to 100 characters")
    if config["support_name"] == config["force_name"]:
        raise ValueError("support_name and force_name must be different")
    if config["human_confirmation"] is not True:
        raise ValueError("人工核对确认是执行建模和求解的必要条件")
    def ids(key):
        values = config[key]
        if not isinstance(values, list) or not 1 <= len(values) <= 1000:
            raise ValueError(key + " must contain 1 to 1000 geometry face IDs")
        if any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in values):
            raise ValueError(key + " must contain positive integer face IDs")
        if len(set(values)) != len(values):
            raise ValueError(key + " contains duplicate IDs")
        return values
    support_ids = ids("support_face_ids")
    if "load" in config:
        load=validate_load(config["load"])
        force_ids=load.get("entity_ids",[]) if load["type"] in ("force","pressure","moment","remote_force") else []
        force=load.get("force_N",[0,0,0])
        config={**config,"load":load,"force_face_ids":force_ids,"force_N":force}
    else:
        force_ids=ids("force_face_ids")
        force=config["force_N"]
        load=validate_load({"type":"force","entity_ids":force_ids,"force_N":force})
    if set(support_ids).intersection(force_ids):
        raise ValueError("Fixed support faces and force faces cannot overlap")
    size = config["mesh_element_size_mm"]
    if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or size <= 0:
        raise ValueError("mesh_element_size_mm must be a positive finite number")
    output = Path(config["output_directory"]).expanduser().resolve()
    if output.exists():
        raise FileExistsError("Output directory already exists: " + str(output))
    return {**config, "project": str(project), "support_face_ids": support_ids,
        "force_face_ids": force_ids, "output_directory": str(output)}


class Adapter:
    def __init__(self, exe=None, batch=True):
        exe = exe or find_ansys_executable()
        if not exe or not Path(exe).is_file():
            raise FileNotFoundError("未找到 Mechanical 2025 R2，请在环境设置中选择 AnsysWBU.exe。")
        from ansys.mechanical.core import launch_mechanical
        self.scratch=[]
        self.session = launch_mechanical(exec_file=exe, batch=batch, cleanup_on_exit=True,
            start_instance=True, ip="127.0.0.1", transport_mode="insecure", start_timeout=90)

    def call(self, action, **params):
        # A fixed script handles all operations. User values enter as JSON data, never source code.
        payload = json.dumps({"action": action, **params}, ensure_ascii=True)
        header, body = script_parts()
        source = header + "REQUEST = json.loads(" + repr(payload) + ")\n" + body
        result = json.loads(self.session.run_python_script(source))
        if "tool_error" in result:
            raise RuntimeError(result["tool_error"])
        return result

    def close(self):
        self.session.exit()
        for temporary in self.scratch:temporary.cleanup()


def run_cases(adapter, config, output):
    config = validate(config)
    original = digest(config["project"])
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "request.json").write_text(json.dumps(config, indent=2), encoding="utf-8")
    report = {"state": "running", "started": datetime.now().astimezone().isoformat(),
              "source_sha256": original, "preflight_review": None, "cases": [],
              "engineering_review": "human_signoff_required"}
    try:
        preflight = adapter.call("review", project=config["project"],
            analysis_name=config["analysis_name"], force_name=config["force_name"])
        report["preflight_review"] = preflight
        if preflight.get("state") not in ("ready", "human_review_required"):
            raise RuntimeError("求解前复核未通过: " + json.dumps(preflight, ensure_ascii=False))
        for case in config["cases"]:
            directory = output / case["name"]
            directory.mkdir()
            record = {"name": case["name"], "force_N": case["force_N"], "state": "running"}
            report["cases"].append(record)
            record["result"] = adapter.call("solve_case", project=config["project"],
                analysis_name=config["analysis_name"], force_name=config["force_name"],
                force_N=case["force_N"], output=str(directory))
            if not record["result"].get("reaction_balance", {}).get("passed", False):
                record["state"] = "failed_review"
                raise RuntimeError("工况 {0} 的支反力平衡复核未通过".format(case["name"]))
            record["state"] = "completed"
        report["state"] = "completed"
        report["calculation_checks"] = "passed"
        report["engineering_acceptance"] = "human_review_required"
    except Exception as exc:
        report["state"] = "failed"
        report["error"] = str(exc)
        if report["cases"] and report["cases"][-1]["state"] == "running":
            report["cases"][-1]["state"] = "failed"
        raise
    finally:
        report["source_unchanged"] = digest(config["project"]) == original
        report["finished"] = datetime.now().astimezone().isoformat()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        with (output / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            fields = ["case", "state", "Fx_N", "Fy_N", "Fz_N", "deformation_max", "stress_max", "reaction_x", "reaction_y", "reaction_z", "reaction_balance_passed", "reaction_balance_residual_N"]
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            for record in report["cases"]:
                result = record.get("result", {})
                writer.writerow(dict(zip(fields, [record["name"], record["state"], *record["force_N"],
                    result.get("deformation_max"), result.get("stress_max"),
                    result.get("reaction_x"), result.get("reaction_y"), result.get("reaction_z"),
                    result.get("reaction_balance", {}).get("passed"),
                    json.dumps(result.get("reaction_balance", {}).get("residual_force_N"), ensure_ascii=False)])))
        if not report["source_unchanged"]:
            raise RuntimeError("Source file changed during run; inspect report.json")
    return report


def run_static_workflow(adapter, config):
    config = validate_workflow(config)
    source_hash = digest(config["project"])
    output = Path(config["output_directory"])
    output.mkdir(parents=True, exist_ok=False)
    report = {"state": "running", "started": datetime.now().astimezone().isoformat(),
        "source": config["project"], "source_sha256": source_hash,
        "human_confirmation": config["human_confirmation"], "inputs": {k: v for k, v in config.items() if k not in ("project", "output_directory")},
        "engineering_acceptance": "human_review_required", "rule_version": RULE_VERSION, "levels": []}
    report["implementation_sha256"] = {name: digest(HERE / name) for name in
        ("mechanical_tools.py", "mechanical_loads.py", "loads.py", "verification.py", "rules.ansys252.json", "knowledge_catalog.json") if (HERE / name).is_file()}
    (output / "request.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        options = config.get("verification", {})
        mesh = options.get("mesh_convergence")
        convergence = {"status": "warn", "reason": "未启用网格收敛检查，仍需人工验证"}
        count = mesh["max_levels"] if mesh else 1
        for level in range(count):
            if digest(config["project"]) != source_hash:
                raise RuntimeError("源模型在网格比较过程中发生变化，已停止")
            directory = output / ("mesh_%02d" % (level + 1)) if mesh else output
            if mesh:
                directory.mkdir()
            params = {k: copy.deepcopy(config[k]) for k in ("project", "analysis_name", "support_name",
                "support_face_ids", "force_name", "force_face_ids", "force_N", "mesh_element_size_mm")}
            params["mesh_element_size_mm"] *= mesh["refinement_factor"] ** level if mesh else 1
            solver_directory=directory
            if not str(directory).isascii():
                temporary=tempfile.TemporaryDirectory(prefix="AnsysSolve_",ignore_cleanup_errors=True)
                solver_directory=Path(temporary.name)
                if not str(solver_directory).isascii():raise RuntimeError("求解临时目录必须是纯英文路径")
                adapter.scratch.append(temporary)
            params["output"] = str(solver_directory)
            if "load" in config:params["load"]=copy.deepcopy(config["load"])
            if mesh:
                params["max_elements"] = mesh["max_elements"]
            record = {"level": level + 1, "mesh_size_mm": params["mesh_element_size_mm"],
                "directory": str(directory), "state": "running"}
            report["levels"].append(record)
            # Every level starts from the same original; material, force and constraints remain fixed.
            result = adapter.call("workflow_solve", **params)
            if solver_directory!=directory:
                adapter.call("selection_copy",output=str(directory/"case.mechdat"))
                artifacts=[]
                for artifact in result.get("artifacts",[]):
                    image=Path(artifact)
                    if image.parent!=solver_directory:raise RuntimeError("Unexpected solver artifact path")
                    destination=directory/image.name
                    shutil.copy2(image,destination);artifacts.append(str(destination))
                result["artifacts"]=artifacts
                record["solver_used_ascii_staging"]=True
            record.update(state="completed", result=result)
            report["result"] = result
            if result.get("reaction_balance", {}).get("passed") is False or result.get('moment_balance',{}).get('passed') is False:
                convergence = {"status": "block", "reason": "支反力或反力矩平衡失败，停止细化"}
                break
            if mesh and level:
                convergence = compare_levels(report["levels"][-2]["result"], result, mesh["relative_tolerance"])
                record["comparison"] = convergence
                if convergence["status"] == "pass" or "relative_change" not in convergence:
                    break
            # Save progress even if a later mesh/solve fails.
            (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["convergence"] = convergence
        if "result" not in report:
            # No level produced evidence; keep the report writable instead of raising KeyError.
            raise RuntimeError("没有可用的求解结果，无法进行规则复核")
        report["verification"] = evaluate(report["result"], options, convergence)
        report["calculation_checks"] = report["verification"]["status"]
        report["state"] = "failed_review" if report["calculation_checks"] == "blocked" else "completed"
    except Exception as exc:
        report["state"] = "failed"
        report["error"] = str(exc)
        report["calculation_checks"] = "incomplete"
        if report["levels"] and report["levels"][-1]["state"] == "running":
            report["levels"][-1]["state"] = "failed"
            report["levels"][-1]["error"] = str(exc)
    finally:
        report["source_unchanged"] = digest(config["project"]) == source_hash
        if not report["source_unchanged"]:
            report["state"] = "source_integrity_error"
        report["finished"] = datetime.now().astimezone().isoformat()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", default="", help="AnsysWBU.exe path; auto-detected when omitted")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("smoke", help="Launch a fresh empty Mechanical instance and inspect it")
    inspect = commands.add_parser("inspect", help="Read a standalone .mechdat template")
    inspect.add_argument("project", type=Path)
    inspect.add_argument("--out", type=Path)
    for name in ("plan", "review", "run"):
        command = commands.add_parser(name)
        command.add_argument("config", type=Path)
        if name == "run":
            command.add_argument("--out", type=Path, required=True, help="New directory; existing directories are rejected")
    args = parser.parse_args()
    config = None
    if args.command in ("plan", "review", "run"):
        config = validate(json.loads(args.config.read_text(encoding="utf-8-sig")))
        if args.command == "plan":
            print(json.dumps({"state": "validated_config_only", "config": config,
                "note": "No Mechanical launch, model validation or solve was performed."}, ensure_ascii=False, indent=2))
            return
    if args.command == "inspect":
        project = args.project.resolve()
        if not project.is_file() or project.suffix.lower() != ".mechdat":
            raise ValueError("Supply an existing standalone .mechdat file")
        if args.out and args.out.exists():
            raise FileExistsError(args.out)
        if args.out and args.out.resolve() == project:
            raise ValueError("Inspection output cannot overwrite input")
    adapter = Adapter(args.exe)
    try:
        if args.command == "run":
            result = run_cases(adapter, config, args.out)
        elif args.command == "review":
            result = adapter.call("review", project=config["project"],
                analysis_name=config["analysis_name"], force_name=config["force_name"])
        else:
            result = adapter.call("inspect", project=str(project) if args.command == "inspect" else None)
            if args.command == "inspect" and args.out:
                args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"state": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
