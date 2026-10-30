"""Canonical load definitions shared by desktop, chat and workflow validation.

Single source of truth: the IronPython fragments executed inside Mechanical
(mechanical_loads.py / mechanical_tools.py) receive these tables as injected
JSON from adapter.Adapter.call, so a new load type only has to be added here.
"""
import copy
import math
import jsonschema

LABELS={'force':'面上总力 · N','pressure':'均布面压力 · Pa','moment':'力矩 · N·mm',
    'gravity':'重力 · m/s²','remote_force':'远程力 · N','point_force':'顶点集中力 · N','line_force':'沿边均布力 · N/mm'}
ENTITY_TYPES={'force':'face','pressure':'face','moment':'face','gravity':None,'remote_force':'face','point_force':'vertex','line_force':'edge'}
VALUE_FIELDS={'force':'force_N','pressure':'pressure_Pa','moment':'moment_Nmm','gravity':'gravity_m_s2',
    'remote_force':'force_N','point_force':'force_N','line_force':'line_force_N_per_mm'}
# Mechanical object class per load type; the API call is always "Add" + class.
MECHANICAL_CLASS={'force':'Force','pressure':'Pressure','moment':'Moment','gravity':'Acceleration',
    'remote_force':'RemoteForce','point_force':'Force','line_force':'LinePressure'}
# Quantity string used for the X/Y/Z component values.
UNITS={'force':'N','pressure':'Pa','moment':'N mm','gravity':'m s^-2',
    'remote_force':'N','point_force':'N','line_force':'N mm^-1'}
REACTION_CLASSES=sorted(set(MECHANICAL_CLASS.values())|{'EarthGravity'})
ALL_TYPES=tuple(LABELS)
VECTOR={'type':'array','minItems':3,'maxItems':3,'items':{'type':'number'}}
IDS={'type':'array','minItems':1,'maxItems':1000,'uniqueItems':True,'items':{'type':'integer','minimum':1}}
variants=[]
for kind in LABELS:
    field=VALUE_FIELDS[kind]
    props={'type':{'const':kind},field:({'type':'number'} if kind=='pressure' else copy.deepcopy(VECTOR))}
    required=['type',field]
    if ENTITY_TYPES[kind]:
        props['entity_ids']={**IDS,**({'maxItems':1} if kind=='point_force' else {})};required.append('entity_ids')
    if kind=='remote_force':
        props.update(application_point_mm=copy.deepcopy(VECTOR),behavior={'enum':['deformable','rigid']})
        required.append('application_point_mm')
    variants.append({'type':'object','required':required,'additionalProperties':False,'properties':props})
LOAD_SCHEMA={'oneOf':variants}


def validate_load(load):
    jsonschema.validate(load,LOAD_SCHEMA)
    value=load[VALUE_FIELDS[load['type']]]
    values=value if isinstance(value,list) else [value]
    if any(isinstance(v,bool) or not math.isfinite(v) for v in values) or not any(values):
        raise ValueError('载荷值必须是有限非零数；单位按当前载荷类型填写')
    if load['type']=='remote_force' and any(not math.isfinite(v) or isinstance(v,bool) for v in load['application_point_mm']):
        raise ValueError('远程力作用点必须是有限的全局 X/Y/Z 坐标，单位 mm')
    normalized=copy.deepcopy(load)
    if load['type']=='remote_force':normalized.setdefault('behavior','deformable')
    return normalized


def validate_load_scope(load,context):
    load=validate_load(load)
    entity_type=ENTITY_TYPES[load['type']]
    if entity_type:
        key={'face':'faces','edge':'edges','vertex':'vertices'}[entity_type]
        available={e['id'] for e in context.get(key,[])}
        if any(i not in available for i in load['entity_ids']):
            raise ValueError('载荷作用对象必须是当前模型中有效的'+{'face':'面','edge':'边','vertex':'顶点'}[entity_type])
        if entity_type=='face' and set(load['entity_ids'])&set(context.get('support_face_ids',[])):
            raise ValueError('固定面与载荷作用面不能重叠')
    return load
