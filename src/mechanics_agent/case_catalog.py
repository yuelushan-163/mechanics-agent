from __future__ import annotations

from mechanics_agent.models import (
    AcceptanceCriteria,
    AnalysisStepSpec,
    BenchmarkSpec,
    BoundaryConditionSpec,
    CaseSpec,
    CaseTemplate,
    ContactSpec,
    GeometryInput,
    IdealizationSpec,
    LoadSpec,
    MaterialSpec,
    MeshStrategy,
    UnitSystem,
)


MM_N_MPA = UnitSystem(
    length="mm",
    force="N",
    stress="MPa",
    mass="tonne",
    time="s",
    temperature="degC",
)


def list_case_templates() -> list[CaseTemplate]:
    """Return versioned, read-only acceptance cases.

    The templates remain pending until the user approves the engineering corrections.
    They are not automatically submitted to a planner, CAD connector, or solver.
    """

    return [
        _beam_template(),
        _beam_overload_template(),
        _pressure_shell_template(),
        _pressure_closed_template(),
        _bolted_joint_template(),
        _thermal_pipe_template(),
        _thermal_restrained_template(),
    ]


def get_case_template(template_id: str) -> CaseTemplate | None:
    return next(
        (item for item in list_case_templates() if item.template_id == template_id),
        None,
    )


def _beam_template() -> CaseTemplate:
    case = CaseSpec(
        case_id="acceptance-beam-001",
        title="简支梁：梁单元与解析解对标",
        analysis_type="linear_static",
        geometry_type="beam",
        description="1000 mm 简支Q235B矩形梁，跨中受5000 N集中力。",
        unit_system=MM_N_MPA,
        geometry=GeometryInput(
            input_mode="text",
            parameters={
                "length": 1000.0,
                "section_width": 50.0,
                "section_height": 80.0,
            },
        ),
        idealization=IdealizationSpec(
            model_dimension="beam",
            element_types=["B31"],
            section_orientation="截面高度80 mm沿竖向，绕强轴弯曲",
            rationale="L/h=12.5；本案例用于梁模型基准测试，不用于局部三维应力。",
        ),
        material=MaterialSpec(
            name="碳素结构钢",
            grade="Q235B",
            elastic_modulus=210000.0,
            poisson_ratio=0.3,
            yield_strength=235.0,
            source_id="材料数据来源与厚度适用范围待工程师确认",
        ),
        loads=[
            LoadSpec(
                name="跨中集中力",
                load_type="concentrated_force",
                region="MIDSPAN_NODE",
                magnitude=5000.0,
                direction=[0.0, -1.0, 0.0],
                unit="N",
                time_variation="static",
            )
        ],
        boundary_conditions=[
            BoundaryConditionSpec(
                name="左端铰支",
                boundary_type="pinned",
                region="LEFT_END",
                constrained_dofs=["U1", "U2", "U3", "UR1"],
                description="UR1用于消除三维B31模型绕梁轴的刚体转动。",
            ),
            BoundaryConditionSpec(
                name="右端滚支",
                boundary_type="roller",
                region="RIGHT_END",
                constrained_dofs=["U2", "U3"],
                description="释放轴向U1，所有弯曲转角保持自由。",
            ),
        ],
        mesh=MeshStrategy(
            target_element_count=20,
            convergence_outputs=["midspan_displacement", "midspan_bending_stress"],
        ),
        benchmarks=[
            BenchmarkSpec(
                name="Euler-Bernoulli跨中位移",
                equation="delta=P*L^3/(48*E*I), I=b*h^3/12",
                expected_value=0.23251488095238096,
                unit="mm",
                tolerance_ratio=0.02,
                assumptions=["小变形", "线弹性", "跨中点载荷", "忽略剪切变形"],
            ),
            BenchmarkSpec(
                name="跨中外纤维弯曲正应力",
                equation="sigma=(P*L/4)*(h/2)/I",
                expected_value=23.4375,
                unit="MPa",
                tolerance_ratio=0.03,
                assumptions=["Euler-Bernoulli梁", "以截面积分点/截面力评估"],
            ),
        ],
        acceptance=AcceptanceCriteria(
            max_displacement=2.0,
            min_safety_factor=2.0,
            max_mesh_change_ratio=0.05,
            max_force_balance_error=0.01,
            max_benchmark_error=0.02,
        ),
        objectives=["验证参数化梁建模", "验证解析解对标", "验证截面方向纠错"],
        required_confirmations=["确认Q235B材料数据来源及适用厚度", "确认B31局部截面方向"],
        metadata={"test_only": True, "solver_execution_requested": False},
    )
    return CaseTemplate(
        template_id="beam-simply-supported-v2",
        version="2.0.0-draft",
        title=case.title,
        capability_tags=["text_to_geometry", "beam", "analytical_benchmark"],
        status="approved",
        case=case,
        expected_results={
            "analytical_displacement_mm": 0.23251488095238096,
            "analytical_bending_stress_mpa": 23.4375,
            "yield_safety_factor": 10.026666666666667,
            "expected_acceptance": "pass",
        },
        abnormal_scenario={
            "trigger": "截面改为宽80 mm、高50 mm，载荷方向不变",
            "expected_detection": "提示当前为弱轴弯曲并要求确认，不自动改回强轴",
            "weak_axis_displacement_mm": 0.5952380952380952,
            "stiffness_ratio_strong_to_weak": 2.56,
        },
        engineering_corrections=[
            "原位移2.33 mm应为0.233 mm；原式小数点错误。",
            "原最大应力187.5 MPa应为23.44 MPa。",
            "5000 N工况满足位移与安全系数目标，不应判为不合格。",
            "均匀网格应使用20个B31单元、21个节点，确保跨中存在节点。",
            "80×50与50×80的抗弯刚度比为2.56，不是约4倍。",
        ],
        required_confirmations=[
            "是否保留5000 N并把预期结论改为合格；若需要失败案例，建议另建50000 N变体。"
        ],
    )


def _beam_overload_template() -> CaseTemplate:
    baseline = _beam_template()
    case = baseline.case.model_copy(deep=True)
    case.case_id = "acceptance-beam-overload-001"
    case.title = "简支梁过载：明确不合格流程"
    case.description = "与梁基准相同，但跨中载荷提高为50000 N，用于验证不合格判定。"
    case.loads[0].magnitude = 50000.0
    case.benchmarks[0].expected_value = 2.3251488095238093
    case.benchmarks[1].expected_value = 234.375
    case.objectives = ["验证刚度不合格", "验证安全系数不合格", "验证禁止自动宣布合格"]
    return CaseTemplate(
        template_id="beam-simply-supported-overload-v1",
        version="1.0.0",
        title=case.title,
        capability_tags=["text_to_geometry", "beam", "expected_failure"],
        status="approved",
        case=case,
        expected_results={
            "analytical_displacement_mm": 2.3251488095238093,
            "analytical_bending_stress_mpa": 234.375,
            "yield_safety_factor": 1.0026666666666666,
            "expected_acceptance": "fail",
        },
        abnormal_scenario={
            "trigger": "规划器把解析基准通过误写成结构设计合格",
            "expected_detection": "解析解对标可以通过，但位移和安全系数必须判为不合格",
        },
        engineering_corrections=["该流程与5000 N合格基准分开，避免一个案例承担相反预期。"],
        required_confirmations=[],
    )


def _pressure_shell_template() -> CaseTemplate:
    case = CaseSpec(
        case_id="acceptance-pressure-shell-001",
        title="开口圆筒壳：壳单元与薄膜理论对标",
        analysis_type="linear_static",
        geometry_type="cylindrical_shell",
        description="直径500 mm、长800 mm、厚5 mm开口圆筒，仅圆柱内壁承受2.5 MPa内压。",
        unit_system=MM_N_MPA,
        geometry=GeometryInput(
            input_mode="cad_part",
            cad_filename="cylinder.SLDPRT",
            parameters={
                "diameter": 500.0,
                "length": 800.0,
                "thickness": 5.0,
                "end_closure": "open_no_end_pressure",
            },
        ),
        idealization=IdealizationSpec(
            model_dimension="shell",
            element_types=["S4R"],
            symmetry="两个沿筒轴的径向对称面，取周向1/4模型",
            rationale="D/t=100、R/t=50，适合壳体薄膜基准。",
            preserved_features=["厚度分区", "压力作用面", "端部条件"],
        ),
        material=MaterialSpec(
            name="奥氏体不锈钢",
            grade="304",
            elastic_modulus=193000.0,
            poisson_ratio=0.3,
            yield_strength=205.0,
            allowable_basis="205 MPa暂按案例限值；真实压力容器须按设计规范确定许用应力",
            source_id="材料状态、温度和设计规范待确认",
        ),
        loads=[
            LoadSpec(
                name="圆柱内壁压力",
                load_type="pressure",
                region="CYLINDER_INNER_SURFACE",
                magnitude=2.5,
                unit="MPa",
                time_variation="static",
            )
        ],
        boundary_conditions=[
            BoundaryConditionSpec(
                name="第一径向对称面",
                boundary_type="symmetry",
                region="RADIAL_PLANE_A",
                constrained_dofs=["U_normal", "UR_tangent_1", "UR_tangent_2"],
            ),
            BoundaryConditionSpec(
                name="第二径向对称面",
                boundary_type="symmetry",
                region="RADIAL_PLANE_B",
                constrained_dofs=["U_normal", "UR_tangent_1", "UR_tangent_2"],
            ),
            BoundaryConditionSpec(
                name="最小刚体约束",
                boundary_type="minimal_stabilization",
                region="REFERENCE_EDGE_OR_POINT",
                constrained_dofs=["axial_rigid_translation"],
                description="只消除轴向刚体平移，不施加虚假的端部封闭约束。",
            ),
        ],
        mesh=MeshStrategy(
            global_size=10.0,
            refined_size=6.0,
            unit="mm",
            convergence_outputs=["hoop_membrane_stress", "radial_displacement"],
        ),
        benchmarks=[
            BenchmarkSpec(
                name="开口薄壁圆筒环向应力",
                equation="sigma_h=p*D/(2*t)",
                expected_value=125.0,
                unit="MPa",
                tolerance_ratio=0.03,
                assumptions=["开口端", "远离端部", "薄壁膜应力", "均匀内压"],
            )
        ],
        acceptance=AcceptanceCriteria(
            max_displacement=3.0,
            max_equivalent_stress=205.0,
            max_mesh_change_ratio=0.05,
            max_benchmark_error=0.03,
        ),
        objectives=["验证壳单元", "验证周向对称", "验证薄膜理论对标"],
        required_confirmations=["确认开口端还是封闭端", "确认205 MPa是测试限值而非规范许用值"],
        metadata={"test_only": True, "solver_execution_requested": False},
    )
    return CaseTemplate(
        template_id="pressure-shell-open-ended-v2",
        version="2.0.0-draft",
        title=case.title,
        capability_tags=["cad_part", "shell", "symmetry", "analytical_benchmark"],
        status="approved",
        case=case,
        expected_results={
            "analytical_hoop_stress_mpa": 125.0,
            "analytical_axial_stress_mpa": 0.0,
            "analytical_mises_stress_mpa": 125.0,
        },
        abnormal_scenario={
            "trigger": "沿轴向局部设置8 mm加厚段",
            "expected_detection": "周向1/4对称仍可用；只有加厚段在周向不连续时才取消相应周向对称",
        },
        engineering_corrections=[
            "原案例没有说明端盖/端面压力，必须区分开口端与封闭端。",
            "两个沿轴线的对称面属于周向1/4对称，不是轴向对称。",
            "沿整个圆周的底部轴向加厚不会破坏周向对称，因此不必自动改用全模型。",
            "对称面可能存在反力，不能写成‘对称模型反力为0’。",
            "205 MPa更接近材料屈服基准，不能在未指定规范、温度和状态时称为压力容器许用应力。",
        ],
        required_confirmations=["案例二采用开口端基准，还是补充端盖并改成封闭端压力容器基准？"],
    )


def _pressure_closed_template() -> CaseTemplate:
    baseline = _pressure_shell_template()
    case = baseline.case.model_copy(deep=True)
    case.case_id = "acceptance-pressure-shell-closed-001"
    case.title = "封闭圆筒壳：双向薄膜应力流程"
    case.description = "直径500 mm、厚5 mm的封闭薄壁圆筒，内压2.5 MPa，显式计入端盖压力效应。"
    case.geometry.parameters["end_closure"] = "closed_with_end_pressure_effect"
    case.loads.append(
        LoadSpec(
            name="封闭端轴向压力合力",
            load_type="equivalent_closed_end_pressure",
            region="END_CLOSURE_OR_EQUIVALENT_EDGE",
            magnitude=2.5,
            unit="MPa",
            description="必须由端盖实体/壳或等效轴向膜力实现，不能只加载圆柱内壁。",
        )
    )
    case.benchmarks = [
        BenchmarkSpec(
            name="封闭薄壁圆筒环向应力",
            equation="sigma_h=p*D/(2*t)",
            expected_value=125.0,
            unit="MPa",
            tolerance_ratio=0.03,
            assumptions=["封闭端", "远离端部", "薄壁膜应力"],
        ),
        BenchmarkSpec(
            name="封闭薄壁圆筒轴向应力",
            equation="sigma_a=p*D/(4*t)",
            expected_value=62.5,
            unit="MPa",
            tolerance_ratio=0.03,
            assumptions=["封闭端", "压力端部合力已施加"],
        ),
    ]
    case.required_confirmations = ["确认端盖是显式建模，还是使用等效轴向膜力"]
    return CaseTemplate(
        template_id="pressure-shell-closed-ended-v1",
        version="1.0.0",
        title=case.title,
        capability_tags=["cad_part", "shell", "closed_end", "analytical_benchmark"],
        status="approved",
        case=case,
        expected_results={
            "analytical_hoop_stress_mpa": 125.0,
            "analytical_axial_stress_mpa": 62.5,
            "analytical_mises_stress_mpa": 108.25317547305482,
        },
        abnormal_scenario={
            "trigger": "只在圆柱内壁施压，却仍声称得到封闭端轴向应力",
            "expected_detection": "阻断并要求补充端盖或等效轴向载荷",
        },
        engineering_corrections=["与开口圆筒基准分开，端部压力效应成为显式输入。"],
        required_confirmations=["求解前选择端盖建模方法。"],
    )


def _bolted_joint_template() -> CaseTemplate:
    case = CaseSpec(
        case_id="acceptance-bolted-joint-001",
        title="预紧螺栓搭接：接触、摩擦与两步加载",
        analysis_type="contact_static",
        geometry_type="bolted_assembly",
        description="两块钢板由4个M10-10.9螺栓夹紧，外载20 kN由板间摩擦传递。",
        unit_system=MM_N_MPA,
        geometry=GeometryInput(
            input_mode="cad_assembly",
            cad_filename="assembly.SLDASM",
            parameters={
                "plate_length": 200.0,
                "plate_width": 100.0,
                "plate_thickness": 10.0,
                "bolt_nominal_diameter": 10.0,
                "bolt_count": 4,
                "bolt_hole_diametral_clearance": 1.0,
            },
            assembly_inventory={"plates": 2, "bolts": 4, "nuts": 4},
        ),
        idealization=IdealizationSpec(
            model_dimension="mixed",
            element_types=["C3D8R", "B31"],
            rationale="钢板用实体；螺栓可用B31加预紧截面进行系统能力测试。",
            preserved_features=["板间接触面", "螺栓轴线", "孔位置", "承压区域"],
            removed_features=["螺纹牙型"],
        ),
        material=MaterialSpec(
            name="钢板与紧固件组合材料",
            grade="Q355B / 10.9",
            yield_strength=355.0,
            allowable_stress=900.0,
            allowable_basis="900 MPa仅作本测试判据；需确认采用保证应力、屈服或设计许用值",
            source_id="钢板与螺栓应拆分材料记录并分别确认来源",
        ),
        loads=[
            LoadSpec(
                name="每个螺栓预紧力",
                load_type="bolt_pretension",
                region="BOLT_1_TO_4_PRETENSION_SECTION",
                magnitude=45000.0,
                direction=[0.0, 0.0, -1.0],
                unit="N_per_bolt",
                time_variation="step_1_apply_then_fix_length",
            ),
            LoadSpec(
                name="钢板端部总拉力",
                load_type="distributed_resultant_force",
                region="MOVING_PLATE_END",
                magnitude=20000.0,
                direction=[1.0, 0.0, 0.0],
                unit="N_total",
                time_variation="step_2",
            ),
        ],
        boundary_conditions=[
            BoundaryConditionSpec(
                name="固定钢板端",
                boundary_type="fixed_end_region",
                region="FIXED_PLATE_END",
                constrained_dofs=["U1", "U2", "U3"],
            )
        ],
        contacts=[
            ContactSpec(
                name="钢板搭接面",
                primary_region="PLATE_A_FAYING_SURFACE",
                secondary_region="PLATE_B_FAYING_SURFACE",
                normal_behavior="hard_contact",
                tangential_behavior="penalty_friction",
                friction_coefficient=0.15,
            )
        ],
        analysis_steps=[
            AnalysisStepSpec(
                name="施加预紧",
                procedure="static_general",
                sequence=1,
                nonlinear_geometry=True,
                actions=["每个螺栓施加45 kN", "稳定后固定预紧截面长度"],
            ),
            AnalysisStepSpec(
                name="施加工作载荷",
                procedure="static_general",
                sequence=2,
                nonlinear_geometry=True,
                actions=["保持预紧长度", "施加20 kN总拉力"],
            ),
        ],
        mesh=MeshStrategy(
            global_size=5.0,
            unit="mm",
            convergence_outputs=["bolt_axial_force", "integrated_contact_shear", "relative_slip"],
        ),
        benchmarks=[
            BenchmarkSpec(
                name="初始摩擦承载力上界",
                equation="F_friction=mu*sum(F_preload)",
                expected_value=27000.0,
                unit="N",
                tolerance_ratio=0.0,
                assumptions=["四个预紧力均完全转化为夹紧力", "未计外载导致的夹紧力变化"],
            )
        ],
        acceptance=AcceptanceCriteria(
            max_equivalent_stress=900.0,
            max_relative_slip=0.01,
            max_mesh_change_ratio=0.05,
            additional={"plate_stress_limit_mpa": 355.0},
        ),
        objectives=["验证接触非线性", "验证螺栓预紧顺序", "验证滑移判据"],
        required_confirmations=[
            "确认孔径、螺栓布置、搭接长度和边距",
            "确认900 MPa判据的物理含义与标准来源",
            "确认B31螺栓与钢板之间的耦合/连接方法",
        ],
        metadata={"test_only": True, "solver_execution_requested": False},
    )
    return CaseTemplate(
        template_id="bolted-lap-joint-v2",
        version="2.0.0-draft",
        title=case.title,
        capability_tags=["cad_assembly", "contact", "pretension", "nonlinear"],
        status="approved",
        case=case,
        expected_results={
            "assembly_part_count": 10,
            "initial_friction_capacity_upper_bound_n": 27000.0,
            "external_load_n": 20000.0,
            "analytical_screening_only": True,
        },
        abnormal_scenario={
            "trigger": "B31单元连接顺序与预紧截面法向相反",
            "expected_detection": "检查预紧截面法向、单元首末节点、预紧节点反力与板间接触压力后再请求人工确认",
        },
        engineering_corrections=[
            "装配清单应为2板+4螺栓+4螺母，共10个零件，不是7个。",
            "摩擦能力必须使用接触压力积分得到的法向合力，不能用最大接触压力乘接触面积。",
            "0.003 mm不是严格的‘无滑移’，必须先定义允许相对滑移阈值。",
            "预紧损失5.2必须标明是百分比、kN还是其他单位。",
            "孔边单节点峰值应力不能直接作为钢板强度结论。",
        ],
        required_confirmations=["补齐孔位、边距、搭接长度、螺母/垫圈和900 MPa判据后才能作为求解验收案例。"],
    )


def _thermal_pipe_template() -> CaseTemplate:
    case = CaseSpec(
        case_id="acceptance-thermal-pipe-001",
        title="自由热膨胀管：温度场与解析位移对标",
        analysis_type="thermal_stress_static",
        geometry_type="pipe",
        description="外径100 mm、厚8 mm、长600 mm的20钢直管，一端固定、另一端自由，均匀升温。",
        unit_system=MM_N_MPA,
        geometry=GeometryInput(
            input_mode="cad_part",
            cad_filename="pipe.SLDPRT",
            parameters={"outer_diameter": 100.0, "thickness": 8.0, "length": 600.0},
        ),
        idealization=IdealizationSpec(
            model_dimension="shell",
            element_types=["S4R"],
            rationale="均匀给定温度场时使用静力步和温度预定义场；无需求解传热。",
            preserved_features=["固定端", "自由端", "温度场"],
        ),
        material=MaterialSpec(
            name="优质碳素结构钢",
            grade="20钢",
            elastic_modulus=206000.0,
            poisson_ratio=0.3,
            yield_strength=245.0,
            allowable_stress=150.0,
            allowable_basis="案例测试限值",
            thermal_expansion_coefficient=1.2e-5,
            thermal_reference_temperature=20.0,
            temperature_dependent=False,
            source_id="热膨胀系数及20~200℃适用性待确认",
        ),
        loads=[
            LoadSpec(
                name="均匀温度场",
                load_type="predefined_temperature",
                region="ALL_PIPE",
                unit="degC",
                time_variation="uniform_ramp",
                initial_value=20.0,
                final_value=200.0,
                reference_value=20.0,
            )
        ],
        boundary_conditions=[
            BoundaryConditionSpec(
                name="固定端",
                boundary_type="fixed_end",
                region="PIPE_END_A",
                constrained_dofs=["U1", "U2", "U3"],
                description="自由端不施加轴向约束。",
            )
        ],
        analysis_steps=[
            AnalysisStepSpec(
                name="施加均匀温升",
                procedure="static_general_with_temperature_field",
                sequence=1,
                nonlinear_geometry=False,
                actions=["设置初始温度20℃", "施加均匀200℃预定义场"],
            )
        ],
        mesh=MeshStrategy(
            global_size=12.0,
            refined_size=6.0,
            unit="mm",
            convergence_outputs=["free_end_axial_displacement", "stress_away_from_fixed_end"],
        ),
        benchmarks=[
            BenchmarkSpec(
                name="自由热膨胀",
                equation="delta=alpha*L*(T-T_ref)",
                expected_value=1.296,
                unit="mm",
                tolerance_ratio=0.02,
                assumptions=["均匀温度", "自由端无轴向约束", "常数热膨胀系数"],
            ),
            BenchmarkSpec(
                name="远离固定端的轴向热应力",
                equation="sigma=0 for free expansion",
                expected_value=0.0,
                unit="MPa",
                tolerance_ratio=0.0,
                assumptions=["直管", "一端自由", "忽略固定端局部边界层"],
            ),
        ],
        acceptance=AcceptanceCriteria(
            max_displacement=3.0,
            max_equivalent_stress=150.0,
            max_mesh_change_ratio=0.05,
            max_benchmark_error=0.02,
        ),
        objectives=["验证温度预定义场", "验证自由热膨胀", "识别固定端局部应力"],
        required_confirmations=["确认20℃为无应力参考温度", "确认热膨胀系数在20~200℃范围内的来源"],
        metadata={"test_only": True, "solver_execution_requested": False},
    )
    return CaseTemplate(
        template_id="thermal-pipe-free-expansion-v2",
        version="2.0.0-draft",
        title=case.title,
        capability_tags=["cad_part", "thermal_load", "analytical_benchmark"],
        status="approved",
        case=case,
        expected_results={
            "analytical_free_end_displacement_mm": 1.296,
            "far_field_axial_stress_mpa": 0.0,
            "expected_acceptance": "pass_if_local_boundary_peak_is_excluded",
        },
        abnormal_scenario={
            "trigger": "未提供无应力参考温度或初始温度",
            "expected_detection": "阻断求解并要求分别补充参考温度、初始温度和最终温度",
        },
        engineering_corrections=[
            "理论热膨胀量为1.296 mm；原1.12 mm结果与该基准相差约13.6%，不能直接判为通过。",
            "一端固定、另一端自由且均匀升温时，远场轴向热应力应接近0。",
            "固定端98.3 MPa可能是局部约束边界层，不能未经路径/区域评估直接作为整体热应力结论。",
            "已知均匀温度场时无需热-结构耦合求解，只需静力分析加温度预定义场。",
        ],
        required_confirmations=["是否将案例四定义为自由热膨胀基准；若目标是产生热应力，需要增加第二端/支架约束。"],
    )


def _thermal_restrained_template() -> CaseTemplate:
    baseline = _thermal_pipe_template()
    case = baseline.case.model_copy(deep=True)
    case.case_id = "acceptance-thermal-pipe-restrained-001"
    case.title = "轴向全约束热管：材料非线性阻断流程"
    case.description = "20钢直管两端轴向受限，从20℃均匀升温到200℃，用于识别屈服与塑性数据缺失。"
    case.analysis_type = "nonlinear_static"
    case.boundary_conditions.append(
        BoundaryConditionSpec(
            name="另一端轴向约束",
            boundary_type="axial_restraint",
            region="PIPE_END_B",
            constrained_dofs=["U_axial"],
            description="形成理想轴向全约束；保留必要横向自由度避免额外过约束。",
        )
    )
    case.benchmarks = [
        BenchmarkSpec(
            name="全约束线弹性热应力筛查",
            equation="sigma=E*alpha*(T-T_ref)",
            expected_value=444.96,
            unit="MPa",
            tolerance_ratio=0.03,
            assumptions=["仅用于屈服前筛查", "完全轴向约束", "常数材料参数"],
        )
    ]
    case.required_confirmations = [
        "线弹性估算444.96 MPa超过245 MPa屈服强度，必须补充20~200℃塑性真应力-真塑性应变数据",
        "确认两端约束真实存在且不会被支架柔度释放",
    ]
    case.objectives = ["验证材料非线性识别", "验证缺少塑性曲线时阻断求解"]
    return CaseTemplate(
        template_id="thermal-pipe-fully-restrained-v1",
        version="1.0.0",
        title=case.title,
        capability_tags=["thermal_load", "restraint", "material_nonlinearity", "expected_block"],
        status="approved",
        case=case,
        expected_results={
            "elastic_screening_stress_mpa": 444.96,
            "yield_strength_mpa": 245.0,
            "expected_precheck": "block_until_plastic_curve_is_supplied",
        },
        abnormal_scenario={
            "trigger": "缺少塑性曲线仍按线弹性提交正式求解",
            "expected_detection": "阻断任务，建立补充材料数据审批记录",
        },
        engineering_corrections=["该流程与自由膨胀案例分开，专门验证热应力和材料非线性门控。"],
        required_confirmations=["补齐塑性数据前只允许生成计划，不允许正式求解。"],
    )
