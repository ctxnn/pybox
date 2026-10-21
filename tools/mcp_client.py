"""Independent finite newline JSON-RPC test client; no server implementation imports."""
import json
import os
import selectors
import subprocess
import time


class Client:
    def __init__(self,argv,*,env=None,cwd=None,timeout=50):
        self.process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=env,cwd=cwd,bufsize=0,start_new_session=True)
        self.selector=selectors.DefaultSelector()
        for name,pipe in [('stdout',self.process.stdout),('stderr',self.process.stderr)]:
            os.set_blocking(pipe.fileno(),False);self.selector.register(pipe,selectors.EVENT_READ,name)
        self.buffer=bytearray();self.messages=[];self.stderr=bytearray();self.history=[]
        self.timeout=timeout;self.sequence=0

    def send_raw(self,data):
        remaining=memoryview(data)
        while remaining:
            sent=self.process.stdin.write(remaining)
            if not sent:raise RuntimeError('server input pipe closed')
            remaining=remaining[sent:]
        self.process.stdin.flush()

    def send(self,value):
        self.history.append(dict(direction='send',message=value))
        self.send_raw(json.dumps(value,separators=(',',':')).encode()+b'\n')

    def request(self,method,params=None,rid=None):
        if rid is None:self.sequence+=1;rid=self.sequence
        self.send(dict(jsonrpc='2.0',id=rid,method=method,params=params or {}))
        return rid

    def notify(self,method,params=None):
        self.send(dict(jsonrpc='2.0',method=method,params=params or {}))

    def pump(self,seconds=0.05):
        for key,event in self.selector.select(seconds):
            data=os.read(key.fd,8192)
            if not data:self.selector.unregister(key.fileobj);continue
            if key.data=='stderr':
                self.stderr.extend(data)
                if len(self.stderr)>16384:raise RuntimeError('server diagnostic bound exceeded')
            else:
                self.buffer.extend(data)
                if len(self.buffer)>262144:raise RuntimeError('server frame bound exceeded')
                while b'\n' in self.buffer:
                    line,_,tail=self.buffer.partition(b'\n');self.buffer=bytearray(tail)
                    message=json.loads(line)
                    if message.get('jsonrpc')!='2.0':raise RuntimeError('non-protocol stdout')
                    self.messages.append(message);self.history.append(dict(direction='receive',message=message))

    def response(self,rid,timeout=None):
        deadline=time.monotonic()+(timeout or self.timeout)
        while time.monotonic()<deadline:
            for i,message in enumerate(self.messages):
                if message.get('id')==rid:return self.messages.pop(i)
            if self.process.poll() is not None and not self.selector.get_map():break
            self.pump()
        raise RuntimeError('No response for request '+repr(rid)+': '+self.stderr.decode(errors='replace'))

    def initialize(self):
        rid=self.request('initialize',dict(protocolVersion='2025-11-25',capabilities={},clientInfo=dict(name='pybox-finite-client',version='1')))
        response=self.response(rid)
        assert response['result']['protocolVersion']=='2025-11-25'
        self.notify('notifications/initialized')
        return response

    def close(self,timeout=25):
        if not self.process.stdin.closed:self.process.stdin.close()
        end=time.monotonic()+timeout
        while time.monotonic()<end and (self.process.poll() is None or self.selector.get_map()):self.pump()
        if self.process.poll() is None:
            self.process.kill();self.process.wait(timeout=2)
            raise RuntimeError('Server did not shut down')
        if self.buffer:raise RuntimeError('partial protocol frame at exit')
        code=self.process.returncode
        self.selector.close()
        for pipe in (self.process.stdout,self.process.stderr):pipe.close()
        return code
