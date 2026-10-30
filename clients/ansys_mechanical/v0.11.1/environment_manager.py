"""Deterministic environment evidence and offline recovery; no model-written commands."""
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import threading
from datetime import datetime
import uuid
import zipfile

PROBE = r'''
import importlib, importlib.metadata as m, json, struct, sys
packages = json.loads(sys.argv[1])
errors = []
versions = {}
for name, expected in packages.items():
    try:
        actual = m.version(name)
        versions[name] = actual
        if actual != expected: errors.append(name + ': version mismatch')
    except m.PackageNotFoundError: errors.append(name + ': missing')
for name, attribute in (('ansys.mechanical.core','launch_mechanical'), ('grpc','insecure_channel'), ('jsonschema','validate'),
        ('requests','post'), ('psutil','Process'), ('PIL.Image','open'), ('fastapi','FastAPI'), ('uvicorn','run')):
    try:
        module = importlib.import_module(name)
        if not callable(getattr(module,attribute,None)): errors.append(name + ': required interface missing')
    except Exception as exc: errors.append(name + ': ' + str(exc))
print(json.dumps({'ok': not errors and struct.calcsize('P') == 8, 'version': sys.version.split()[0],
    'bits': struct.calcsize('P') * 8, 'packages': versions, 'errors': errors}))
'''


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def run_hidden(command, timeout=120, **kwargs):
    env = dict(os.environ)
    for name in ('PYTHONHOME', 'PYTHONPATH', 'PYTHONSTARTUP'):
        env.pop(name, None)
    env['PYTHONIOENCODING'] = 'utf-8'
    env['PIP_NO_INDEX'] = '1'
    env['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    return subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace',
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), env=env, timeout=timeout, **kwargs)


def settings_directory():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'AnsysMechanicalAssistant'


def find_ansys_executable():
    candidates = []
    if os.environ.get('ANSYS_AGENT_ANSYS_EXE'):
        candidates.append(Path(os.environ['ANSYS_AGENT_ANSYS_EXE']))
    try:
        saved = json.loads((settings_directory()/'ansys-installation.json').read_text(encoding='utf-8'))
        if saved.get('executable'): candidates.append(Path(saved['executable']))
    except (OSError, ValueError, TypeError):
        pass
    if os.environ.get('AWP_ROOT252'):
        candidates.append(Path(os.environ['AWP_ROOT252'])/'aisol/Bin/winx64/AnsysWBU.exe')
    # Honour the real program-files locations first, then fall back to a drive scan.
    roots = [Path(os.environ[variable]) for variable in ('ProgramFiles', 'ProgramFiles(x86)') if os.environ.get(variable)]
    roots += [Path(drive + '/') for drive in ('C:', 'D:', 'E:')]
    for root in dict.fromkeys(roots):
        for directory in ('ANSYS Inc/v252', 'Program Files/ANSYS Inc/v252', 'Program Files/ANSYS 2025R2/v252'):
            candidates.append(root / directory / 'aisol/Bin/winx64/AnsysWBU.exe')
    return next((str(p.resolve()) for p in candidates if p.is_file() and p.name.lower()=='ansyswbu.exe'), None)


def save_ansys_executable(path):
    path = Path(path).resolve()
    if not path.is_file() or path.name.lower() != 'ansyswbu.exe':
        raise ValueError('请选择 Mechanical 安装目录中的 AnsysWBU.exe。')
    folder = settings_directory()
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'ansys-installation.json').write_text(json.dumps({'executable': str(path)}), encoding='utf-8')
    os.environ['ANSYS_AGENT_ANSYS_EXE'] = str(path)


class EnvironmentManager:
    def __init__(self, root, state_dir=None):
        self.root = Path(root).resolve()
        self.payload = self.root/'runtime_payload'
        self.state_dir = Path(state_dir) if state_dir else settings_directory()
        self.cache = self.state_dir/'runtimes'
        self.app_id = hashlib.sha256(str(self.root).encode('utf-8')).hexdigest()[:12]
        self.state_file = self.state_dir/f'runtime-{self.app_id}.json'
        self.lock = threading.Lock()
        self.last_report = None
        self.connection = None

    def record_connection(self, result):
        self.connection = {'connected':bool(result.get('connected')), 'session':str(result.get('session',''))[:1200],
            'checked_at':datetime.now().isoformat(timespec='seconds'),'executable':find_ansys_executable()}

    def manifest(self):
        data = json.loads((self.payload/'manifest.json').read_text(encoding='utf-8'))
        if data.get('schema') != 1 or data.get('architecture') != 'AMD64' or not data.get('files') or not data.get('packages'):
            raise ValueError('内置环境清单不完整。请重新解压完整发布包。')
        for row in data['files']:
            self.payload_path(row['path'])
        for key in ('embed', 'pip_wheel'):
            if data[key] not in {row['path'] for row in data['files']}:
                raise ValueError('内置环境缺少安装文件记录。')
        return data

    def payload_path(self, name):
        path = (self.payload/name).resolve()
        if Path(name).is_absolute() or not path.is_relative_to(self.payload.resolve()):
            raise ValueError('内置包路径非法。')
        return path

    def selected_python(self):
        try:
            state = json.loads(self.state_file.read_text(encoding='utf-8'))
            path = Path(state['python']).resolve()
            marker = json.loads((path.parent/'managed-runtime.json').read_text(encoding='utf-8'))
            if path.is_relative_to(self.cache.resolve()) and path.name=='python.exe' and path.is_file() and marker.get('app_id')==self.app_id:
                if marker.get('payload_sha256') == digest(self.payload/'manifest.json'):
                    return path
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def verify_payload(self, progress=lambda _: None):
        data = self.manifest()
        progress('正在校验内置 Python 和离线依赖包…')
        for row in data['files']:
            path = self.payload_path(row['path'])
            if not path.is_file() or path.stat().st_size != row['size'] or digest(path) != row['sha256']:
                raise ValueError('内置文件缺失或校验失败：'+row['path']+'。请重新解压完整发布包。')
        return data

    def probe(self, python, packages):
        try:
            result = run_hidden([str(python), '-I', '-c', PROBE, json.dumps(packages)], timeout=90, cwd=str(python.parent))
            data = json.loads(result.stdout.strip().splitlines()[-1])
            if result.returncode: data['ok'] = False
            if data.get('ok'):
                check = run_hidden([str(python), '-I', '-m', 'pip', '--isolated', 'check'], timeout=45, cwd=str(python.parent))
                if check.returncode:
                    data['ok'] = False
                    data.setdefault('errors', []).append('依赖一致性检查失败：'+check.stdout[-1500:])
            return data
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired) as exc:
            return {'ok': False, 'errors': [str(exc)]}

    def inspect(self):
        checks = []
        supported = platform.system()=='Windows' and platform.machine().upper() in ('AMD64', 'X86_64')
        checks.append({'id':'platform', 'state':'pass' if supported else 'blocked', 'message':'Windows 64 位' if supported else '需要 Windows x64 系统'})
        packages = {}
        try:
            data = self.manifest()
            packages = data['packages']
            missing = [row['path'] for row in data['files'] if not self.payload_path(row['path']).is_file()]
            checks.append({'id':'offline_payload', 'state':'blocked' if missing else 'pass',
                'message':'内置离线包缺失：'+', '.join(missing[:3]) if missing else '内置 Python 和离线包可用；配置前会核验 SHA256'})
        except (OSError, ValueError, KeyError, TypeError) as exc:
            checks.append({'id':'offline_payload', 'state':'blocked', 'message':'请使用完整发布文件夹：'+str(exc)})
        python = self.selected_python()
        probe = self.probe(python, packages) if python else {'ok':False, 'errors':['尚未配置本程序的内置 Python 环境']}
        checks.append({'id':'python', 'state':'pass' if probe['ok'] else 'repairable',
            'message':'内置 Python '+probe.get('version','')+' 与依赖检查通过' if probe['ok'] else '；'.join(probe.get('errors',[]))[:1600]})
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=self.state_dir) as test: test.write(b'check')
            free = shutil.disk_usage(self.state_dir).free
            disk_ready = probe['ok'] or free >= 512*1024**2
            checks.append({'id':'storage', 'state':'pass' if disk_ready else 'blocked', 'message':'用户目录可写，可用空间 %.1f GB'%(free/1024**3)})
        except OSError as exc:
            checks.append({'id':'storage','state':'blocked','message':'用户目录无法写入：'+str(exc)})
        ansys = find_ansys_executable()
        checks.append({'id':'ansys_installation','state':'pass' if ansys else 'manual',
            'message':'发现 Mechanical 安装程序；尚需验证软件连接' if ansys else '未找到 Mechanical 2025 R2。请安装后选择 AnsysWBU.exe；内置包不含 Ansys 安装介质。'})
        connection = self.connection if self.connection and self.connection['executable']==ansys else None
        connected = bool(connection and connection['connected'])
        checks.append({'id':'mechanical_connection','state':'pass' if connected else 'unverified',
            'message':('Mechanical 连接已验证，检查时间 '+connection['checked_at']) if connected else '尚未验证实际连接；点击“检查 Ansys 连接”，不会自动求解。'})
        checks.append({'id':'solver_license','state':'unverified','message':'求解许可证需在实际求解时验证；发现安装程序或软件连接通过不代表求解许可有效。'})
        report = {'state':('connected' if connected else 'ready_to_connect') if probe['ok'] and ansys and not any(c['state']=='blocked' for c in checks) else 'needs_configuration',
            'checks':checks, 'python':str(python) if python else None, 'ansys_executable':ansys,
            'can_repair':any(c['state']=='repairable' for c in checks) and not any(c['state']=='blocked' for c in checks),
            'connection_verified':connected}
        if connection:report['connection']=connection
        self.last_report = report
        return report

    @staticmethod
    def extract(archive_path, destination):
        destination = Path(destination).resolve()
        with zipfile.ZipFile(archive_path) as archive:
            for member in archive.infolist():
                target = (destination/member.filename).resolve()
                if not target.is_relative_to(destination) or (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('压缩包包含非法路径。')
            archive.extractall(destination)

    def ensure(self, progress=lambda _: None, force=False):
        if not self.lock.acquire(blocking=False):
            raise RuntimeError('环境正在检查或配置，请稍后再试。')
        target = None
        try:
            if platform.system()!='Windows' or platform.machine().upper() not in ('AMD64','X86_64'):
                raise RuntimeError('内置环境只支持 Windows x64。')
            data = self.verify_payload(progress)
            current = self.selected_python()
            if not force and current and self.probe(current,data['packages'])['ok']:
                progress('内置 Python 环境已就绪。')
                return current
            self.cache.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(self.cache).free < 512*1024**2:
                raise RuntimeError('配置环境需要至少 512 MB 可用空间。')
            target = self.cache/f'py312-{self.app_id}-{uuid.uuid4().hex[:10]}'
            target.mkdir()
            progress('正在部署内置 Python 3.12 和离线依赖…')
            self.extract(self.payload_path(data['embed']), target)
            site = target/'Lib/site-packages'
            site.mkdir(parents=True)
            self.extract(self.payload_path(data['pip_wheel']), site)
            (target/'python312._pth').write_text('python312.zip\n.\nLib/site-packages\n'+str(self.root)+'\nimport site\n',encoding='utf-8')
            command = [str(target/'python.exe'), '-I', '-m', 'pip', '--isolated', 'install', '--no-index',
                '--find-links', str(self.payload/'wheels'), '--require-hashes', '--no-compile', '--no-warn-script-location',
                '--disable-pip-version-check', '-r', str(self.payload/'requirements.lock')]
            result = run_hidden(command, timeout=600, cwd=str(target))
            (target/'offline-install.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
            if result.returncode:
                raise RuntimeError('离线依赖配置失败：'+(result.stderr or result.stdout)[-1800:])
            progress('正在复查 Python 模块与依赖一致性…')
            probe = self.probe(target/'python.exe',data['packages'])
            if not probe['ok']:
                raise RuntimeError('环境复查未通过：'+'；'.join(probe.get('errors',[])))
            (target/'managed-runtime.json').write_text(json.dumps({'app_id':self.app_id,
                'payload_sha256':digest(self.payload/'manifest.json')}),encoding='utf-8')
            self.state_dir.mkdir(parents=True,exist_ok=True)
            pending = self.state_file.with_suffix('.'+uuid.uuid4().hex+'.tmp')
            pending.write_text(json.dumps({'python':str(target/'python.exe')}),encoding='utf-8')
            os.replace(pending,self.state_file)
            progress('内置 Python 环境配置完成，无需另装 Python。')
            return target/'python.exe'
        except Exception:
            # Keep failed attempt and its log for review. It cannot become the selected runtime.
            raise
        finally:
            self.lock.release()


ENVIRONMENT_TOOLS = [
    {'type':'function','function':{'name':'environment_status',
        'description':'读取真实本机环境检查：内置 Python、固定依赖、离线包、Ansys 安装与连接验证状态。不启动求解，不包含 API 密钥。',
        'parameters':{'type':'object','properties':{},'additionalProperties':False}}},
    {'type':'function','function':{'name':'prepare_environment',
        'description':'仅使用已打包并校验的离线 Python 与依赖补齐本程序环境，然后重新检查。不下载未知包、不安装 Ansys、不更改系统 Python、不执行任意命令。',
        'parameters':{'type':'object','properties':{},'additionalProperties':False}}}
]
