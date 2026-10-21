"""Fixed NVIDIA NIM transport. Credentials live only in parent/worker memory."""
import json
import math
from pathlib import Path
import sys
import time

from .container import _capture
from .mcp import strict_json
from .mcp_policy import encode

ENDPOINT='https://integrate.api.nvidia.com/v1/chat/completions'
MODEL='nvidia/nemotron-3.5-lightning-30b-a3b'
MAX_RESPONSE_BYTES=524288
MAX_PROMPT_BYTES=24576
MAX_COMPLETION_TOKENS=2048
REQUEST_TIMEOUT_S=45
WORKER=Path(__file__).with_name('_nim_worker.py')


class ProviderError(RuntimeError):
    """A request may have been admitted upstream; never retry automatically."""


def request_body(messages):
    if (not isinstance(messages,list) or len(messages)!=2 or
        [m.get('role') for m in messages if isinstance(m,dict)]!=['system','user'] or
        any(set(m)!={'role','content'} or not isinstance(m['content'],str) for m in messages)):
        raise ValueError('Expected two bounded system/user text messages')
    if len(encode(messages))>MAX_PROMPT_BYTES:raise ValueError('Prompt byte bound exceeded')
    return dict(model=MODEL,messages=messages,temperature=1,top_p=0.95,max_tokens=MAX_COMPLETION_TOKENS,
                stream=False,seed=17,reasoning_budget=0,chat_template_kwargs=dict(enable_thinking=False))


def normalized_response(response):
    if not isinstance(response,dict) or response.get('model')!=MODEL:raise ProviderError('Unexpected response model')
    choices=response.get('choices')
    if not isinstance(choices,list) or len(choices)!=1 or not isinstance(choices[0],dict):raise ProviderError('Invalid choices')
    choice=choices[0];message=choice.get('message')
    if not isinstance(message,dict) or not isinstance(message.get('content'),str) or message.get('tool_calls'):
        raise ProviderError('Expected answer text without provider tool calls')
    usage=response.get('usage')
    if not isinstance(usage,dict):raise ProviderError('Usage unavailable; stop rather than assume zero')
    counts={}
    for key in ('prompt_tokens','completion_tokens','total_tokens'):
        n=usage.get(key)
        if type(n) is not int or not 0<=n<=1000000:raise ProviderError('Invalid usage counts')
        counts[key]=n
    if counts['completion_tokens']>MAX_COMPLETION_TOKENS or counts['total_tokens']!=counts['prompt_tokens']+counts['completion_tokens']:
        raise ProviderError('Provider usage exceeds or contradicts bounds')
    if len(message['content'].encode('utf-8'))>32768:raise ProviderError('Answer exceeds byte bound')
    cost=usage.get('cost')
    if cost is not None and (type(cost) not in (int,float) or not math.isfinite(cost) or cost<0):raise ProviderError('Invalid reported cost')
    fingerprint=response.get('system_fingerprint')
    if fingerprint is not None and (not isinstance(fingerprint,str) or len(fingerprint)>256):raise ProviderError('Invalid model fingerprint')
    return dict(model=response['model'],id=str(response.get('id',''))[:256],finish_reason=choice.get('finish_reason'),
                content=message['content'],usage=counts,reported_cost_usd=None,provider_cost_field=cost,
                cost_provenance='USD settlement unavailable; trial listing is not a settled bill',
                reasoning_chars=len(message.get('reasoning_content') or ''),system_fingerprint=fingerprint)


class NimProvider:
    def __init__(self,key):
        if not isinstance(key,str) or not key.startswith('nvapi-') or not 10<=len(key)<=256 or not key.isascii() or any(c.isspace() for c in key):
            raise ValueError('Expected an NVIDIA API key')
        self._key=key

    def __repr__(self):return 'NimProvider(credentials=<redacted>)'

    def complete(self,messages,timeout_s=REQUEST_TIMEOUT_S):
        body=request_body(messages)
        if not 0<timeout_s<=REQUEST_TIMEOUT_S:raise ValueError('Invalid request timeout')
        start=time.monotonic()
        capture=_capture([sys.executable,'-I','-B',str(WORKER)],input_data=encode(dict(key=self._key,request=body)),
                         timeout_s=timeout_s,cap=MAX_RESPONSE_BYTES)
        if (capture['timed_out'] or not capture['input_complete'] or not capture['output_complete'] or
            capture['stdout_truncated'] or capture['stderr_truncated'] or capture['returncode']!=0):
            detail=capture.get('stderr','').replace(self._key,'[REDACTED]')[:256]
            raise ProviderError('NIM transport incomplete; upstream usage/cost unknown; batch must stop. '+detail)
        try:
            data=strict_json(capture['stdout'])
            if set(data)!={'response'}:raise ValueError()
            result=normalized_response(data['response'])
            if self._key in encode(result).decode('utf-8'):raise ValueError()
        except (ValueError,TypeError,KeyError,UnicodeError,RecursionError):
            raise ProviderError('Invalid NIM response; usage/cost unknown; batch must stop') from None
        result['elapsed_s']=time.monotonic()-start
        return result

    def forget(self):self._key=None
