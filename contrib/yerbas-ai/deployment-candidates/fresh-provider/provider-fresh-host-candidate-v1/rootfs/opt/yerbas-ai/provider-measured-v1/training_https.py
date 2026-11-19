"""Provider-only verified HTTPS for isolated training assignments; no admin routes."""
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import re
import ssl
import socket
import threading
import time
from urllib.parse import urlsplit
from selected_checkpoint import MAX_BYTES


class RemoteError(Exception):
    def __init__(self,status,message):
        self.status=status
        super().__init__(message)


def create_server(store, token_hashes, cert, key, bind='127.0.0.1', port=0):
    address=ipaddress.ip_address(bind)
    allowed=[ipaddress.ip_network(n) for n in ('127.0.0.0/8','10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    if address.version!=4 or not any(address in network for network in allowed):
        raise ValueError('Explicit loopback or RFC1918 IPv4 bind required')
    credentials=dict(token_hashes)
    if not credentials or any(not re.fullmatch('[a-f0-9]{64}',k) for k in credentials):
        raise ValueError('Provider token hashes required')
    context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version=ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(cert,key)

    class Handler(BaseHTTPRequestHandler):
        protocol_version='HTTP/1.0'
        def log_message(self,*args):pass
        def reply(self,status,value):
            raw=json.dumps(value,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(raw)));self.send_header('Connection','close')
            self.end_headers();self.wfile.write(raw);self.close_connection=True
        def do_POST(self):
            try:
                headers=self.headers.get_all('Authorization',[])
                if len(headers)!=1 or not headers[0].startswith('Bearer '):
                    self.reply(401,{'error':'Provider authentication required'});return
                token=headers[0][7:]
                provider=credentials.get(hashlib.sha256(token.encode()).hexdigest())
                if provider is None:
                    self.reply(401,{'error':'Invalid provider credential'});return
                try:
                    with store.tx() as db:store.require_provider(db,provider)
                except ValueError:
                    self.reply(401,{'error':'Provider credential revoked'});return
                match=re.fullmatch('/v1/training/result/([a-f0-9]{32})',self.path)
                status_match=re.fullmatch('/v1/training/status/([a-f0-9]{32})',self.path)
                if self.path!='/v1/training/claim' and not match and not status_match:
                    self.reply(404,{'error':'Unknown provider route'});return
                lengths=self.headers.get_all('Content-Length',[])
                if self.headers.get_all('Transfer-Encoding') or len(lengths)!=1 or not lengths[0].isdigit():
                    self.reply(400,{'error':'One explicit Content-Length required'});return
                length=int(lengths[0]);limit=4096 if match is None else MAX_BYTES
                if not 0<length<=limit:
                    self.reply(413,{'error':'Request exceeds bound'});return
                expected_type='application/octet-stream' if match else 'application/json'
                if self.headers.get('Content-Type')!=expected_type:
                    self.reply(415,{'error':'Unsupported content type'});return
                if match:
                    checksums=self.headers.get_all('X-Artifact-SHA256',[])
                    if len(checksums)!=1 or not re.fullmatch('[a-f0-9]{64}',checksums[0]):
                        self.reply(400,{'error':'Artifact SHA256 required'});return
                deadline=time.monotonic()+90;chunks=[];remaining=length
                while remaining:
                    if time.monotonic()>deadline:raise TimeoutError('Upload deadline exceeded')
                    chunk=self.rfile.read1(min(65536,remaining))
                    if not chunk:raise ValueError('Truncated request')
                    chunks.append(chunk);remaining-=len(chunk)
                raw=b''.join(chunks)
                if match:
                    result=store.accept(provider,match[1],raw,checksums[0])
                    self.reply(200,{'receipt':result})
                else:
                    def unique(pairs):
                        value={}
                        for k,v in pairs:
                            if k in value:raise ValueError('Duplicate JSON key')
                            value[k]=v
                        return value
                    body=json.loads(raw,object_pairs_hook=unique)
                    if status_match:
                        if body!={} or type(body) is not dict:raise ValueError('Empty status body required')
                        self.reply(200,{'status':store.status(provider,status_match[1])});return
                    if type(body) is not dict or set(body)!={'request_id'}:
                        raise ValueError('Only request_id is accepted')
                    self.reply(200,{'assignment':store.claim(provider,body['request_id'])})
            except (ValueError,UnicodeError) as exc:
                self.reply(400,{'error':str(exc)[:200]})
            except (TimeoutError,ConnectionError):
                self.close_connection=True
            except Exception:
                self.reply(500,{'error':'Training coordinator error'})

    class Server(ThreadingHTTPServer):
        daemon_threads=False
        block_on_close=True
        request_queue_size=4
        def __init__(self,*args):
            self.slots=threading.BoundedSemaphore(2)
            super().__init__(*args)
        def get_request(self):
            sock,peer=super().get_request();sock.settimeout(10)
            try:return context.wrap_socket(sock,server_side=True,do_handshake_on_connect=False),peer
            except BaseException:sock.close();raise
        def process_request(self,request,address):
            if not self.slots.acquire(blocking=False):
                self.shutdown_request(request);return
            try:super().process_request(request,address)
            except BaseException:self.slots.release();raise
        def process_request_thread(self,*args):
            def expire_connection():
                try:args[0].shutdown(socket.SHUT_RDWR)
                except OSError:pass
            timer=threading.Timer(100,expire_connection);timer.daemon=True;timer.start()
            try:super().process_request_thread(*args)
            finally:timer.cancel();self.slots.release()
        def handle_error(self,*args):pass
    return Server((bind,port),Handler)


class Client:
    def __init__(self,url,token,ca):
        if type(url) is not str or any(ord(c)<=32 for c in url):raise ValueError('Invalid URL')
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.path not in ('','/') or parsed.query or parsed.fragment or '?' in url or '#' in url:
            raise ValueError('Verified HTTPS origin required')
        if type(token) is not str or len(token)<32 or any(ord(c)<=32 for c in token):raise ValueError('Invalid provider token')
        self.host=parsed.hostname;self.port=parsed.port or 443;self.token=token
        if not 1<=self.port<=65535:raise ValueError('Invalid port')
        if not ca:raise ValueError('Explicit trusted CA required')
        self.context=ssl.create_default_context(cafile=ca)
        self.context.minimum_version=ssl.TLSVersion.TLSv1_2
    def request(self,path,raw,content_type,extra=None,timeout=30):
        headers={'Authorization':'Bearer '+self.token,'Content-Type':content_type}
        if extra:headers.update(extra)
        conn=http.client.HTTPSConnection(self.host,self.port,context=self.context,timeout=timeout)
        try:
            conn.request('POST',path,raw,headers)
            response=conn.getresponse()
            data=response.read(65537)
            if len(data)>65536:raise RemoteError(502,'Oversized coordinator response')
            if response.status!=200:raise RemoteError(response.status,'Coordinator rejected request')
            value=json.loads(data)
            if type(value) is not dict:raise RemoteError(502,'Invalid coordinator response')
            return value
        finally:conn.close()
    def claim(self,request_id):
        return self.request('/v1/training/claim',json.dumps({'request_id':request_id}).encode(),'application/json')['assignment']
    def submit(self,assignment,raw):
        if not re.fullmatch('[a-f0-9]{32}',assignment):raise ValueError('Invalid assignment')
        if type(raw) is not bytes or not 0<len(raw)<=MAX_BYTES:raise ValueError('Artifact size invalid')
        return self.request('/v1/training/result/'+assignment,raw,'application/octet-stream',
                            {'X-Artifact-SHA256':hashlib.sha256(raw).hexdigest()})['receipt']

    def status(self,assignment):
        if not re.fullmatch('[a-f0-9]{32}',assignment):raise ValueError('Invalid assignment')
        return self.request('/v1/training/status/'+assignment,b'{}','application/json',timeout=3)['status']
