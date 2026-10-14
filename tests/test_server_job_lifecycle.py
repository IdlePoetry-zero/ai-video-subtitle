"""A completed worker may still be flushing the terminal RPC notification."""
import ast
import copy
from pathlib import Path
import threading


def test_resume_is_allowed_while_previous_terminal_message_is_flushing():
    tree=ast.parse(Path('worker/server.py').read_text())
    # Load the actual protocol functions without its stdin process entrypoint.
    definitions=[]
    for node in tree.body:
        if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Attribute) and isinstance(node.value.func.value,ast.Name) and node.value.func.value.id=='signal':break
        if isinstance(node,ast.If):continue  # Process-only stdio reconfiguration.
        definitions.append(node)
    namespace={'__file__':str(Path('worker/server.py').resolve())}
    exec(compile(ast.Module(body=definitions,type_ignores=[]),'worker/server.py','exec'),namespace)
    class Project:
        data={'cues':[{'id':'valid'}]}
        def save(self):pass
        def snapshot(self):return copy.deepcopy(self.data)
    first=threading.Event();release=threading.Event();second=threading.Event();messages=[]
    def send(payload):
        if payload.get('event')!='job':return
        messages.append(payload)
        if len(messages)==1:
            first.set();assert release.wait(5)
        else:second.set()
    namespace.update(project=Project(),scan=lambda *args:None,send=send)
    try:
        old=namespace['start_job']('scan',{})
        assert first.wait(5)
        new=namespace['start_job']('scan',{})
        assert second.wait(5)
        assert old['job']!=new['job']
        assert [m['status'] for m in messages]==['complete','complete']
        assert messages[0]['project']['task']['id']==old['job']
    finally:release.set()
