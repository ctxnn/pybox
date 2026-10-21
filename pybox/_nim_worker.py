"""Owned disposable HTTPS worker; no credential files, redirects, proxies or retries."""
from pathlib import Path
import sys
import ssl
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import urllib.error
import urllib.request
from pybox.mcp import strict_json
from pybox.mcp_policy import encode
from pybox.nim import ENDPOINT,MAX_RESPONSE_BYTES,request_body


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def main():
    phase='payload'
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError()
        value=strict_json(raw)
        if set(value)!={'key','request'} or request_body(value['request']['messages'])!=value['request']:raise ValueError()
        key=value['key']
        if not isinstance(key,str) or not key.startswith('nvapi-') or not key.isascii() or not 10<=len(key)<=256 or any(c.isspace() for c in key):raise ValueError()
        request=urllib.request.Request(ENDPOINT,data=encode(value['request']),method='POST',
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'})
        context=ssl.create_default_context(cafile='/etc/ssl/cert.pem')
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect(),urllib.request.HTTPSHandler(context=context))
        phase='connect'
        with opener.open(request,timeout=40) as response:
            if response.status!=200:
                print('NIM nonterminal HTTP status '+str(response.status)+'; upstream usage/cost unconfirmed',file=sys.stderr)
                return 1
            phase='read'
            data=response.read(MAX_RESPONSE_BYTES+1)
            if len(data)>MAX_RESPONSE_BYTES or key.encode() in data:raise ValueError()
        phase='parse'
        print(encode(dict(response=strict_json(data))).decode(),flush=True)
        return 0
    except urllib.error.HTTPError as exc:
        print('NIM HTTP status '+str(exc.code)+'; no retry; usage/cost unconfirmed',file=sys.stderr)
        exc.close();return 1
    except urllib.error.URLError as exc:
        category='TLS certificate verification' if isinstance(exc.reason,ssl.SSLCertVerificationError) else 'connection or request timeout'
        print('NIM '+category+' failed; no retry; usage/cost unconfirmed',file=sys.stderr)
        return 1
    except Exception:
        print('NIM '+phase+' '+type(sys.exc_info()[1]).__name__+' failed; no retry; usage/cost unconfirmed',file=sys.stderr)
        return 1


if __name__=='__main__':sys.exit(main())
