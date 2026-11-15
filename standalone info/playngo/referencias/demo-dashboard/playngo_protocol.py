"""Public Play'n GO text commands carried by SignalR MessagePack."""
import re
from urllib.parse import unquote
import msgpack

def commands(text):
    text=text.removeprefix('d=')
    result=[]
    for line in text.splitlines():
        if not line.strip():continue
        match=re.fullmatch(r'(\d+)(?:\s+(.*))?',line.strip())
        if not match:raise ValueError('unrecognized_native_command')
        args=[]
        for token in re.findall(r'"(?:[^"\\]|\\.)*"|[^\s]+',match[2] or ''):
            value=token[1:-1].replace('\\"','"') if token.startswith('"') else token
            args.append(unquote(value))
        result.append((int(match[1]),args))
    return result

def encode_frame(value):
    data=msgpack.packb(value,use_bin_type=True);size=len(data);prefix=bytearray()
    while size>=128:prefix.append((size&127)|128);size>>=7
    prefix.append(size);return bytes(prefix)+data

def decode_frames(data):
    offset=0;frames=[]
    while offset<len(data):
        size=0;shift=0
        while True:
            if offset>=len(data) or shift>=35:raise ValueError('invalid_signalr_length')
            byte=data[offset];offset+=1;size|=(byte&127)<<shift
            if not byte&128:break
            shift+=7
        if size>len(data)-offset:raise ValueError('incomplete_signalr_message')
        frames.append(msgpack.unpackb(data[offset:offset+size],raw=False));offset+=size
    return frames

def sanitize_commands(items):
    safe=[]
    for code,args in items:
        if code==103 and len(args)==1 or code in (100,91):args=['[REDACTED]' if arg else '' for arg in args]
        elif code==101 and any(args):args=[arg if i in (1,3) else '[REDACTED]' for i,arg in enumerate(args)]
        elif code==200:args=[arg if i in (1,3) else '[REDACTED]' for i,arg in enumerate(args)]
        safe.append({'code':code,'args':args})
    return safe
