# Fixed IronPython helpers injected before mechanical_tools.py. Values remain JSON data.
# LOAD_CLASSES / SCOPE_TYPES / VALUE_FIELDS / UNITS / REACTION_CLASSES are injected as
# JSON by adapter.Adapter.call, so load definitions live in loads.py only.
import math


def geometry_entities(model, entity_type):
    result={}
    for body in walk(model.Geometry):
        if kind(body)!="Body" or body.Suppressed:continue
        for entity in getattr(body.GetGeoBody(),{"face":"Faces","edge":"Edges","vertex":"Vertices"}[entity_type]):
            result[int(entity.Id)]=entity
    return result


def geometry_inventory(model):
    output={"geometry_length_unit":unicode(ExtAPI.DataModel.GeoData.Unit)}
    for entity_type,key in [("edge","edges"),("vertex","vertices")]:
        rows=[]
        for identifier,entity in geometry_entities(model,entity_type).items():
            row={"id":identifier,"entity_type":entity_type}
            if entity_type=="edge":row["length"]=float(entity.Length)
            for attr in ("X","Y","Z"):
                if hasattr(entity,attr):row[attr.lower()]=float(getattr(entity,attr))
            rows.append(row)
        output[key]=sorted(rows,key=lambda x:x["id"])
    return output


def configure_primary_load(model, analysis, request):
    spec=request.get("load",{"type":"force","entity_ids":request["force_face_ids"],"force_N":request["force_N"]})
    load_type=spec["type"]
    if load_type not in LOAD_CLASSES:raise Exception("Unsupported load type")
    allowed=set(REACTION_CLASSES)
    active=[o for o in analysis.Children if kind(o) in allowed and not o.Suppressed]
    if len(active)>1 or any(unicode(o.Name)!=request["force_name"] for o in active):
        raise Exception("当前一次求解只支持一个主载荷；请先人工处理其他活动载荷")
    desired=LOAD_CLASSES[load_type]
    replaced=None
    if active and kind(active[0])!=desired:
        replaced=kind(active[0])
        active[0].Delete()
        active=[]
    load=active[0] if active else getattr(analysis,"Add"+LOAD_CLASSES[load_type])()
    load.Name=request["force_name"]
    systems=[c for c in model.CoordinateSystems.Children if unicode(c.Name) in ("Global Coordinate System","全局坐标系")]
    if len(systems)!=1:raise Exception("不能唯一识别全局坐标系")
    global_system=systems[0]
    entity_type=SCOPE_TYPES[load_type]
    entities=geometry_entities(model,entity_type) if entity_type else {}
    ids=spec.get("entity_ids",[])
    if entity_type:
        if not ids or any(i not in entities for i in ids):raise Exception("载荷作用对象不存在或类型不正确")
        if entity_type=="face" and set(ids).intersection(request["support_face_ids"]):raise Exception("固定面与载荷面不能重叠")
        if entity_type in ("vertex","edge"):
            constrained=set()
            for f in geometry_faces(model):
                if int(f.Id) in request["support_face_ids"]:
                    constrained.update(int(e.Id) for e in getattr(f,"Vertices" if entity_type=="vertex" else "Edges"))
            if constrained.intersection(ids):raise Exception("点/边载荷不能施加在固定支撑的顶点或边上")
        selection=ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities)
        selection.Ids=ids;load.Location=selection
    expected=None
    evidence={"type":load_type,"scope_type":entity_type,"entity_ids":ids,"replaced_load_class":replaced}
    if load_type=="pressure":
        load.Magnitude.Output.DiscreteValues=[Quantity(unicode(spec["pressure_Pa"])+" [Pa]")]
        length_to_m=float(units.ConvertUnit(1,unicode(ExtAPI.DataModel.GeoData.Unit),"m"))
        expected=[0.0,0.0,0.0]
        for identifier in ids:
            face=entities[identifier]
            if unicode(face.SurfaceType)!="GeoSurfacePlane":
                expected=None;evidence["balance_note"]="曲面压力合力未独立积分，需人工复核整体平衡";break
            normal=face.NormalAtParam(0.5,0.5)
            for i in range(3):expected[i]-=float(spec["pressure_Pa"])*float(face.Area)*length_to_m**2*float(normal[i])
    elif load_type=="gravity":
        load.DefineBy=LoadDefineBy.Components
        load.CoordinateSystem=global_system
        for component,value in zip([load.XComponent,load.YComponent,load.ZComponent],spec["gravity_m_s2"]):
            component.Output.DiscreteValues=[Quantity(unicode(-float(value))+" [m s^-2]")]
        evidence["implementation"]="inertial acceleration = negative requested gravity"
        mass=0.0
        for body in walk(model.Geometry):
            if kind(body)=="Body" and not body.Suppressed:
                value=quantity_value(body.Mass,"kg")
                if value<=0 or math.isnan(value) or math.isinf(value):raise Exception("重力计算要求每个活动实体具有有效密度和质量")
                mass+=value
        evidence["total_mass_kg"]=mass
        expected=[mass*float(v) for v in spec["gravity_m_s2"]]
    else:
        field=VALUE_FIELDS[load_type]
        unit=UNITS[load_type]
        load.DefineBy=LoadDefineBy.Components;load.CoordinateSystem=global_system
        for component,value in zip([load.XComponent,load.YComponent,load.ZComponent],spec[field]):
            component.Output.DiscreteValues=[Quantity(unicode(value)+" ["+unit+"]")]
        expected=[float(v) for v in spec[field]] if load_type!="moment" else [0.0,0.0,0.0]
        if load_type=="remote_force":
            load.Behavior=LoadBehavior.Deformable if spec.get("behavior","deformable")=="deformable" else LoadBehavior.Rigid
            for axis,value in zip(["XCoordinate","YCoordinate","ZCoordinate"],spec["application_point_mm"]):
                setattr(load,axis,Quantity(unicode(value)+" [mm]"))
            evidence["moment_review"]="远程作用点引入力矩；支撑反力矩及其参考点需人工复核"
        if load_type=="line_force":
            scale=float(units.ConvertUnit(1,unicode(ExtAPI.DataModel.GeoData.Unit),"mm"))
            length=sum(float(entities[i].Length) for i in ids)*scale
            evidence["total_length_mm"]=length
            expected=[float(v)*length for v in spec[field]]
    evidence["expected_force_N"]=expected
    return load,spec,evidence,global_system


def solve_configured_workflow(model, request):
    project=ExtAPI.DataModel.Project
    project.SaveAs(os.path.join(request["output"],"case.mechdat"),False)
    analysis=unique(model.Analyses,request["analysis_name"])
    if unicode(analysis.AnalysisType)!="Static" or analysis.AnalysisSettings.LargeDeflection or analysis.AnalysisSettings.NumberOfSteps!=1:
        raise Exception("只支持单步、小变形 Static Structural")
    bodies=[b for b in walk(model.Geometry) if kind(b)=="Body" and not b.Suppressed]
    if not bodies or any(not unicode(b.Material).strip() for b in bodies):raise Exception("所有活动实体必须先分配人工确认的材料")
    if [c for c in walk(model.Connections) if kind(c)=="ContactRegion" and not c.Suppressed]:raise Exception("当前执行范围不支持活动接触")
    allowed=set(REACTION_CLASSES)|set(["AnalysisSettings","ANSYSAnalysisSettings","Solution","FixedSupport"])
    if [c for c in analysis.Children if kind(c) not in allowed and not getattr(c,"Suppressed",False)]:raise Exception("存在未支持的活动分析对象")
    supports=[c for c in analysis.Children if kind(c)=="FixedSupport" and not c.Suppressed]
    if len(supports)>1 or any(unicode(o.Name)!=request["support_name"] for o in supports):raise Exception("要求一个指定名称的固定支撑，不能叠加其他活动支撑")
    support=supports[0] if supports else analysis.AddFixedSupport();support.Name=request["support_name"]
    faces=geometry_entities(model,"face")
    if not request["support_face_ids"] or any(i not in faces for i in request["support_face_ids"]):raise Exception("固定支撑必须选择当前模型的几何面")
    selection=ExtAPI.SelectionManager.CreateSelectionInfo(SelectionTypeEnum.GeometryEntities);selection.Ids=request["support_face_ids"];support.Location=selection
    load,spec,evidence,global_system=configure_primary_load(model,analysis,request)
    model.Mesh.ElementSize=Quantity(unicode(request["mesh_element_size_mm"])+" [mm]");model.Mesh.GenerateMesh()
    meshdata=analysis.MeshData
    if int(meshdata.ElementCount)<=0:raise Exception("网格为空")
    if request.get("max_elements") is not None and int(meshdata.ElementCount)>request["max_elements"]:
        project.Save();raise Exception("网格单元数超过预算，已在求解前停止")
    effective=dict(request);effective["load"]=spec
    review=review_model(model,effective)
    if review["state"]=="blocked":raise Exception("模型复核阻断: "+json.dumps(review,ensure_ascii=False))
    solution=analysis.Solution
    stamp="Agent_Load_"+time.strftime("%Y%m%d_%H%M%S")
    deformation=solution.AddTotalDeformation();deformation.Name=stamp+"_TotalDeformation"
    stress=solution.AddEquivalentStress();stress.Name=stamp+"_EquivalentStress"
    reaction=solution.AddForceReaction();reaction.BoundaryConditionSelection=support
    moment=None
    if spec["type"] in ("moment","remote_force"):
        moment=solution.AddMomentReaction();moment.BoundaryConditionSelection=support;moment.Orientation=global_system
    solution.Solve(True)
    if unicode(solution.Status)!="Done":raise Exception("Solve did not complete: "+unicode(solution.Status)+"; "+" | ".join(unicode(m.DisplayString) for m in ExtAPI.Application.Messages))
    solution.EvaluateAllResults()
    reactions=[quantity_value(v,"N") for v in (reaction.XAxis,reaction.YAxis,reaction.ZAxis)]
    expected=evidence["expected_force_N"]
    balance={"passed":None,"reaction_force_N":reactions,"applied_force_N":expected,"note":evidence.get("balance_note","")}
    if expected is not None:
        residual=[reactions[i]+expected[i] for i in range(3)]
        tolerance=max(1e-8,max([abs(v) for v in expected]+[0])*1e-4)
        balance.update(passed=all(abs(v)<=tolerance for v in residual),residual_force_N=residual,tolerance_N=tolerance)
        if spec['type']=='pressure':
            balance['estimated_check_passed']=balance['passed']
            balance['passed']=None
            balance['note']='压力合力由 CAD 面积和法向估算；离散压力面积可能不同，整体平衡需人工复核'
    result={"status":unicode(solution.Status),"deformation_max":unicode(deformation.Maximum),"deformation_max_mm":quantity_value(deformation.Maximum,"mm"),
        "stress_max":unicode(stress.Maximum),"stress_max_MPa":quantity_value(stress.Maximum,"MPa"),
        "reaction_x":unicode(reaction.XAxis),"reaction_y":unicode(reaction.YAxis),"reaction_z":unicode(reaction.ZAxis),
        "mesh_nodes":int(meshdata.NodeCount),"mesh_elements":int(meshdata.ElementCount),"reaction_balance":balance,
        "load":spec,"load_evidence":evidence,"preflight_review":review,"messages":[],"artifacts":[],"export_errors":[],
        "engineering_review":"human_signoff_required"}
    if moment is not None:
        values=[quantity_value(v,"N mm") for v in (moment.XAxis,moment.YAxis,moment.ZAxis)]
        result["reaction_moment_Nmm"]=values
        if spec["type"]=="moment":
            residual=[values[i]+float(spec["moment_Nmm"][i]) for i in range(3)]
            tolerance=max(1e-8,max(abs(v) for v in spec["moment_Nmm"])*1e-4)
            result["moment_balance"]={"passed":all(abs(v)<=tolerance for v in residual),"residual_Nmm":residual,"tolerance_Nmm":tolerance}
    for message in ExtAPI.Application.Messages:result["messages"].append({"severity":unicode(message.Severity),"text":unicode(message.DisplayString)})
    for obj,name in [(analysis,"loads.png"),(deformation,"deformation.png"),(stress,"stress.png")]:
        try:
            obj.Activate();ExtAPI.Graphics.Camera.SetFit();path=os.path.join(request["output"],name);ExtAPI.Graphics.ExportImage(path);result["artifacts"].append(path)
        except Exception as error:result["export_errors"].append(unicode(error))
    project.Save()
    return result
