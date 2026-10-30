# Runs inside Mechanical's IronPython engine. REQUEST is injected as JSON data.
import json
import os
import time
import units


def quantity_value(value, target_unit):
    return float(units.ConvertUnit(float(value.Value), unicode(value.Unit), target_unit))


def kind(obj):
    return unicode(obj.GetType().Name)


def brief(obj):
    result = {"id": int(obj.ObjectId), "name": unicode(obj.Name), "type": kind(obj)}
    for attribute in ("Suppressed", "Material", "Status", "LargeDeflection", "AnalysisType"):
        if hasattr(obj, attribute):
            result[attribute] = unicode(getattr(obj, attribute))
    if hasattr(obj, "Location"):
        try:
            result["location_ids"] = [int(i) for i in obj.Location.Ids]
        except Exception:
            result["location"] = unicode(obj.Location)
    return result


def walk(obj):
    if obj is None:
        return
    yield obj
    if hasattr(obj, "Children"):
        for child in obj.Children:
            for descendant in walk(child):
                yield descendant


def unique(objects, name):
    matches = [o for o in objects if unicode(o.Name) == name]
    if len(matches) != 1:
        raise Exception("Expected exactly one object named '{0}', found {1}".format(name, len(matches)))
    return matches[0]


def geometry_faces(model):
    faces = []
    for body in [b for b in walk(model.Geometry) if kind(b) == "Body" and not b.Suppressed]:
        geo_body = body.GetGeoBody()
        for face in geo_body.Faces:
            faces.append(face)
    return faces


def review_model(model, request):
    """Read-only Mechanical preflight. Any unknown/failed check remains visible."""
    findings = []
    def add(level, code, text):
        findings.append({"level": level, "code": code, "message": text})
    analysis = None
    try:
        analysis = unique(model.Analyses, request["analysis_name"])
    except Exception as error:
        add("block", "analysis", unicode(error))
    force = None
    support = None
    bodies = [b for b in walk(model.Geometry) if kind(b) == "Body" and not b.Suppressed]
    if not bodies:
        add("block", "body", "没有未抑制的实体 Body")
    for body in bodies:
        if not unicode(body.Material).strip():
            add("block", "material", "实体未分配材料: " + unicode(body.Name))
        else:
            add("human", "material_properties", "已分配材料“{0}”；需人工核对弹性模量、泊松比、单位及线弹性适用性".format(unicode(body.Material)))
    meshdata = None
    try:
        meshdata = analysis.MeshData if analysis is not None else None
        nodes = int(meshdata.NodeCount)
        elements = int(meshdata.ElementCount)
        if nodes <= 0 or elements <= 0:
            add("block", "mesh_empty", "网格节点或单元数量为零")
        mesh = model.Mesh
        mesh.ComputeMeshQualityMetrics()
        metrics = []
        for metric in mesh.GetVolumeMeshMetrics():
            row = {"name": unicode(mesh.GetVolumeMeshQualityName(metric)),
                   "worst": unicode(mesh.GetVolumeMeshQualityWorstMetricValue(metric)),
                   "average": unicode(mesh.GetVolumeMeshQualityAverageMetricValue(metric)),
                   "failed": int(mesh.GetVolumeMeshQualityCountFailed(metric)),
                   "warning_failed": int(mesh.GetVolumeMeshQualityWarningCountFailed(metric))}
            metrics.append(row)
            metric_name = row["name"].lower()
            is_min_edge = ("边长" in metric_name and "最小" in metric_name) or ("edge" in metric_name and "min" in metric_name)
            if is_min_edge:
                add("info", "mesh_min_edge", "记录最小单元边长及统计数；该尺寸指标不单独作为网格质量硬阻断条件")
            elif row["failed"] > 0:
                add("block", "mesh_quality", "网格质量指标 {0} 有 {1} 个超限单元".format(row["name"], row["failed"]))
            elif row["warning_failed"] > 0:
                add("human", "mesh_quality_warning", "网格质量指标 {0} 有 {1} 个警告单元".format(row["name"], row["warning_failed"]))
        mesh_summary = {"nodes": nodes, "elements": elements, "metrics": metrics}
    except Exception as error:
        mesh_summary = {"error": unicode(error)}
        add("human", "mesh_quality_unavailable", "未能读取网格数量/质量指标，需在 Mechanical 中人工检查: " + unicode(error))
    connections = [c for c in walk(model.Connections) if kind(c) == "ContactRegion" and not c.Suppressed]
    if connections:
        add("block", "contacts", "当前执行范围不支持活动接触")
    if analysis is not None:
        if unicode(analysis.AnalysisType) != "Static":
            add("block", "analysis_type", "当前工具仅支持 Static Structural")
        if analysis.AnalysisSettings.LargeDeflection:
            add("block", "large_deflection", "当前工具基线不支持大变形")
        if analysis.AnalysisSettings.NumberOfSteps != 1:
            add("block", "load_steps", "当前工具基线要求单载荷步")
        try:
            force = unique(analysis.Children, request["force_name"])
        except Exception as error:
            add("block", "force", unicode(error))
        supports = [c for c in analysis.Children if kind(c) == "FixedSupport" and not c.Suppressed]
        if len(supports) != 1:
            add("block", "support", "当前基线要求且仅允许一个活动 Fixed Support")
        else:
            support = supports[0]
        allowed = {"AnalysisSettings", "ANSYSAnalysisSettings", "Solution", "Force", "FixedSupport"}
        if request.get("load"):allowed.update(LOAD_CLASSES.values())
        unexpected = [unicode(c.Name) for c in analysis.Children if kind(c) not in allowed and not getattr(c, "Suppressed", False)]
        if unexpected:
            add("block", "unsupported_objects", "存在当前基线不支持的活动对象: " + ", ".join(unexpected))
        active_forces = [c for c in analysis.Children if kind(c) in (set(LOAD_CLASSES.values()) if request.get("load") else {"Force"}) and not c.Suppressed]
        if force is not None and len(active_forces) != 1:
            add("block", "force_count", "当前工作流只允许一个活动主载荷")
        for obj in [o for o in (force, support) if o is not None and kind(o) not in ("EarthGravity","Acceleration")]:
            try:
                ids = [int(i) for i in obj.Location.Ids]
                if not ids:
                    add("block", "empty_scope", "作用范围为空: " + unicode(obj.Name))
                elif any(i not in geometry_entities(model, "face" if obj is support else SCOPE_TYPES.get(request.get("load",{}).get("type","force"),"face")) for i in ids):
                    add("human", "scope_type", "需确认作用范围确为预期几何面: " + unicode(obj.Name))
            except Exception as error:
                add("human", "scope_read", "无法读取作用范围: {0}: {1}".format(unicode(obj.Name), unicode(error)))
    load_type=request.get("load",{}).get("type","force")
    if load_type in ("point_force","line_force"):
        add("human","local_singularity","点/边载荷的局部峰值应力可能随网格变化；需人工确认评价区域，不能用峰值直接验收")
    if load_type=="remote_force":add("human","remote_point","请人工核对远程作用点坐标、耦合范围及刚性/可变形行为")
    add("human", "mesh_convergence", "网格质量指标不能替代网格收敛性验证；请人工比较至少两档网格或与解析/基准结果对照")
    add("human", "scope_and_sign", "请人工核对几何作用面、载荷方向/大小、约束位置及单位")
    levels = [f["level"] for f in findings]
    state = "blocked" if "block" in levels else "human_review_required"
    return {"state": state, "checks": {"analysis": unicode(analysis.Name) if analysis else None,
        "force": unicode(force.Name) if force else None, "support": unicode(support.Name) if support else None,
        "mesh": mesh_summary}, "findings": findings,
        "human_signoff_required": True,
        "note": "自动复核只能发现已编码的异常，不能证明有限元工程结论绝对正确。"}


def configure_and_solve(model, request):
    return solve_configured_workflow(model, request)


def perform(request):
    project = ExtAPI.DataModel.Project
    if request.get("project"):
        project.Open(request["project"])
    model = ExtAPI.DataModel.Project.Model
    if request["action"] == "selection_copy":
        project.SaveAs(request["output"], False)
        model.Geometry.Activate()
        ExtAPI.Graphics.Camera.SetFit()
        return {"copy": request["output"]}
    if request["action"] == "selection_read":
        selection = ExtAPI.SelectionManager.CurrentSelection
        if unicode(selection.SelectionType) != "GeometryEntities":
            raise Exception("请将选择过滤器切换为几何面；不能读取网格节点或单元选择")
        ids = [int(i) for i in selection.Ids]
        entity_type=request.get("entity_type","face")
        available=set(geometry_entities(model,entity_type))
        if not ids or any(i not in available for i in ids):
            raise Exception("请选择当前载荷所需的几何面、边或顶点；对象类型不能混用")
        return {"face_ids": ids if entity_type=="face" else [], "entity_ids":ids,"entity_type":entity_type,"selection_type": unicode(selection.SelectionType)}
    if request["action"] == "selection_highlight":
        ids = request["face_ids"]
        entity_type=request.get("entity_type","face")
        available=set(geometry_entities(model,entity_type))
        if not ids or any(type(i) is not int or i not in available for i in ids):
            raise Exception("预览对象 ID 必须属于当前模型且类型一致")
        selection = ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
        selection.Ids = ids
        model.Geometry.Activate()
        ExtAPI.SelectionManager.NewSelection(selection)
        return {"face_ids": ids if entity_type=="face" else [], "entity_ids":ids,"entity_type":entity_type}
    if request["action"] == "inspect":
        faces = []
        faces_error = None
        try:
            for face in geometry_faces(model):
                row = {"id": int(face.Id), "type": kind(face)}
                row['edge_ids']=[int(e.Id) for e in face.Edges]
                row['vertex_ids']=[int(v.Id) for v in face.Vertices]
                for attr in ("Area", "SurfaceType"):
                    if hasattr(face, attr): row[attr.lower()] = unicode(getattr(face, attr))
                faces.append(row)
        except Exception as error:
            faces_error = unicode(error)
        inventory=geometry_inventory(model)
        return dict(inventory, **{"unit_system": unicode(ExtAPI.Application.ActiveUnitSystem),
            "analyses": [{"object": brief(a), "children": [brief(c) for c in a.Children]} for a in model.Analyses],
            "named_selections": [brief(n) for n in model.NamedSelections.Children] if model.NamedSelections else [],
            "bodies": [brief(b) for b in walk(model.Geometry) if kind(b) == "Body"],
            "faces": faces, "faces_error": faces_error})
    if request["action"] == "review":
        return review_model(model, request)
    if request["action"] == "workflow_solve":
        return configure_and_solve(model, request)
    if request["action"] != "solve_case":
        raise Exception("Unsupported tool action")
    review = review_model(model, request)
    if review["state"] == "blocked":
        raise Exception("求解前复核未通过: " + json.dumps(review, ensure_ascii=False))
    analysis = unique(model.Analyses, request["analysis_name"])
    if unicode(analysis.AnalysisType) != "Static":
        raise Exception("Only Static structural analysis is supported; actual: " + unicode(analysis.AnalysisType))
    if analysis.AnalysisSettings.LargeDeflection:
        raise Exception("Large deflection is outside the linear baseline")
    if analysis.AnalysisSettings.NumberOfSteps != 1:
        raise Exception("First baseline requires exactly one load step")
    force = unique(analysis.Children, request["force_name"])
    if kind(force) != "Force" or force.Suppressed:
        raise Exception("Target must be an active standard Force object")
    supports = [c for c in analysis.Children if kind(c) == "FixedSupport" and not c.Suppressed]
    if len(supports) != 1:
        raise Exception("Baseline requires exactly one active FixedSupport for reaction extraction")
    allowed = {"AnalysisSettings", "ANSYSAnalysisSettings", "Solution", "Force", "FixedSupport"}
    unexpected = [unicode(c.Name) for c in analysis.Children if kind(c) not in allowed and not getattr(c, "Suppressed", False)]
    other_forces = [c for c in analysis.Children if kind(c) == "Force" and not c.Suppressed and c.ObjectId != force.ObjectId]
    if unexpected or other_forces:
        raise Exception("Baseline supports one Force and one FixedSupport only; inspect active loads/settings")
    for obj in [force, supports[0]]:
        if len(obj.Location.Ids) == 0:
            raise Exception("Empty scope on " + unicode(obj.Name))
    bodies = [b for b in walk(model.Geometry) if kind(b) == "Body" and not b.Suppressed]
    if not bodies or any(not unicode(b.Material).strip() for b in bodies):
        raise Exception("Template needs active bodies with assigned materials")
    contacts = [c for c in walk(model.Connections) if kind(c) == "ContactRegion" and not c.Suppressed]
    if contacts:
        raise Exception("First baseline excludes contact regions; use a verified continuous-body model")
    output = request["output"]
    # Switch to a new standalone file before modifying the model.
    project.SaveAs(os.path.join(output, "case.mechdat"), False)
    force.DefineBy = LoadDefineBy.Components
    global_systems = [c for c in model.CoordinateSystems.Children if unicode(c.Name) in ("Global Coordinate System", "全局坐标系")]
    if len(global_systems) != 1:
        raise Exception("不能唯一识别全局坐标系；为避免载荷方向错误，已停止求解")
    force.CoordinateSystem = global_systems[0]
    for component, value in zip([force.XComponent, force.YComponent, force.ZComponent], request["force_N"]):
        component.Output.DiscreteValues = [Quantity(unicode(value) + " [N]")]
    solution = analysis.Solution
    deformation = solution.AddTotalDeformation()
    deformation.Name = "Agent_TotalDeformation"
    stress = solution.AddEquivalentStress()
    stress.Name = "Agent_EquivalentStress"
    reaction = solution.AddForceReaction()
    reaction.Name = "Agent_ForceReaction"
    reaction.BoundaryConditionSelection = supports[0]
    solution.Solve(True)
    if unicode(solution.Status) != "Done":
        raise Exception("Solve did not complete: " + unicode(solution.Status))
    solution.EvaluateAllResults()
    reaction_values = [float(reaction.XAxis.Value), float(reaction.YAxis.Value), float(reaction.ZAxis.Value)]
    applied = [float(v) for v in request["force_N"]]
    residual = [reaction_values[i] + applied[i] for i in range(3)]
    force_norm = max([abs(v) for v in applied] + [0.0])
    reaction_ok = all(abs(v) <= max(1e-8, force_norm * 1e-4) for v in residual)
    result = {"status": unicode(solution.Status), "deformation_max": unicode(deformation.Maximum),
        "stress_max": unicode(stress.Maximum), "reaction_x": unicode(reaction.XAxis),
        "reaction_y": unicode(reaction.YAxis), "reaction_z": unicode(reaction.ZAxis),
        "messages": [], "artifacts": [], "export_errors": [],
        "preflight_review": review, "reaction_balance": {"applied_force_N": applied,
        "reaction_force_as_reported": [unicode(reaction.XAxis), unicode(reaction.YAxis), unicode(reaction.ZAxis)],
        "residual_force_N": residual, "tolerance_N": max(1e-8, force_norm * 1e-4),
        "passed": reaction_ok},
        "engineering_review": "human sign-off required: validate material properties, model scope and load direction, inspect solver messages, and verify mesh convergence"}
    for message in ExtAPI.Application.Messages:
        result["messages"].append({"severity": unicode(message.Severity), "text": unicode(message.DisplayString)})
    for obj, name in [(deformation, "deformation.png"), (stress, "stress.png")]:
        try:
            obj.Activate()
            ExtAPI.Graphics.Camera.SetFit()
            path = os.path.join(output, name)
            ExtAPI.Graphics.ExportImage(path)
            result["artifacts"].append(path)
        except Exception as error:
            result["export_errors"].append(unicode(error))
    project.Save()
    return result


try:
    RESPONSE = perform(REQUEST)
except Exception:
    import traceback
    RESPONSE = {"tool_error": traceback.format_exc()}
json.dumps(RESPONSE)
