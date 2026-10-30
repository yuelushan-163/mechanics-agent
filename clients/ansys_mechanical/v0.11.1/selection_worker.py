"""Private JSON-lines worker owning one interactive Mechanical selection copy."""
from contextlib import redirect_stdout
import json
from pathlib import Path
import sys
import tempfile
from adapter import Adapter, digest


def signature(data):
    """Geometry fingerprint used to detect model changes between calls.

    Faces, edges and vertices use independent ID spaces, so rows are compared as
    strings: a float length and a missing (None) length can otherwise raise
    TypeError when two entity kinds share an ID.
    """
    faces = ((f['id'], f.get('area'), f.get('type')) for f in data.get('faces', []))
    others = ((e['id'], e.get('length'), e.get('x'), e.get('y'), e.get('z'))
              for e in data.get('edges', []) + data.get('vertices', []))
    return sorted(faces, key=str) + sorted(others, key=str)


class VisualSession:
    def __init__(self):
        self.adapter = None
        self.temporary = None
        self.source = None
        self.source_hash = None
        self.face_signature = None

    def open(self, path):
        source = Path(path).resolve()
        if not source.is_file() or source.suffix.lower() != '.mechdat':
            raise ValueError('请先选择独立 .mechdat 模型')
        if self.source == source and self.adapter and digest(source) == self.source_hash:
            try:
                return self.inspect()
            except Exception:
                # The user may have closed the owned Mechanical window manually.
                self.close()
        self.close()
        self.source, self.source_hash = source, digest(source)
        try:
            self.adapter = Adapter(batch=False)
            data = self.adapter.call('inspect', project=str(source))
            self.face_signature = signature(data)
            self.temporary = tempfile.TemporaryDirectory(prefix='AnsysFacePicker_')
            copy = str(Path(self.temporary.name) / 'selection.mechdat')
            self.adapter.call('selection_copy', output=copy)
            if signature(self.adapter.call('inspect')) != self.face_signature:
                raise ValueError('可视化副本与源模型的几何面不一致，已停止选面')
            return self.inspect()
        except Exception:
            self.close()
            raise

    def inspect(self):
        self.check()
        data = self.adapter.call('inspect')
        if signature(data) != self.face_signature:
            raise ValueError('可视化模型的几何已改变，请关闭选面窗口并重新打开原模型')
        return dict(data, source=str(self.source), source_sha256=self.source_hash,
            selection_copy=str(Path(self.temporary.name) / 'selection.mechdat'))

    def check(self):
        if not self.adapter:
            raise ValueError('请先打开可视化选面窗口')
        if digest(self.source) != self.source_hash:
            raise ValueError('源模型已改变，请重新打开可视化模型')

    def selection(self,entity_type="face"):
        data = self.inspect()
        result = self.adapter.call('selection_read',entity_type=entity_type)
        available = {f['id'] for f in data[{'face':'faces','edge':'edges','vertex':'vertices'}[entity_type]]}
        ids = result['entity_ids']
        if not ids or len(ids) != len(set(ids)) or any(i not in available for i in ids):
            raise ValueError('选择对象必须与载荷要求的面、边或顶点类型一致')
        return dict(result, source=str(self.source), source_sha256=self.source_hash)

    def close(self):
        if self.adapter:
            try:
                self.adapter.session.exit(force=True)
            except Exception:
                pass
            finally:
                self.adapter = None
        if self.temporary:
            self.temporary.cleanup()
            self.temporary = None
        self.source = None


def main():
    session = VisualSession()
    try:
        for line in sys.stdin:
            request = {}
            try:
                request = json.loads(line)
                with redirect_stdout(sys.stderr):
                    action = request['action']
                    if action == 'open':
                        result = session.open(request['project'])
                    elif action == 'read_selection':
                        result = session.selection(request.get("entity_type","face"))
                    elif action == 'highlight':
                        session.inspect()
                        result = session.adapter.call('selection_highlight', face_ids=request['face_ids'],entity_type=request.get('entity_type','face'))
                    elif action == 'close':
                        session.close()
                        result = {'closed': True}
                    else:
                        raise ValueError('Unknown selection action')
                response = {'id': request.get('id'), 'ok': True, 'result': result}
            except Exception as exc:
                response = {'id': request.get('id'), 'ok': False, 'error': str(exc)}
            print(json.dumps(response, ensure_ascii=False), flush=True)
            if request.get('action') == 'close':
                break
    finally:
        session.close()


if __name__ == '__main__':
    main()
