"""Pinned OpenSSL EVP AES-256-GCM provider, without custom cryptographic math."""
import ctypes
import hashlib
from pathlib import Path
import re


class OpenSSLAESGCM:
    def __init__(self,key,library,pin):
        path=Path(library)
        if len(key)!=32 or not path.is_absolute() or not path.is_file() or not re.fullmatch('[a-f0-9]{64}',str(pin)):
            raise ValueError('AES-256 key and explicitly pinned native libcrypto required')
        path=path.resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest()!=pin:raise ValueError('libcrypto SHA256 mismatch')
        self.key=key;self.library=str(path);self.sha256=pin
        self.lib=ctypes.CDLL(str(path))
        pointer=ctypes.c_void_p;integer=ctypes.c_int;length=ctypes.POINTER(integer)
        signatures={
            'EVP_CIPHER_CTX_new':([],pointer),'EVP_CIPHER_CTX_free':([pointer],None),
            'EVP_aes_256_gcm':([],pointer),'EVP_CIPHER_CTX_ctrl':([pointer,integer,integer,pointer],integer),
            'EVP_EncryptInit_ex':([pointer,pointer,pointer,pointer,pointer],integer),
            'EVP_DecryptInit_ex':([pointer,pointer,pointer,pointer,pointer],integer),
            'EVP_EncryptUpdate':([pointer,pointer,length,pointer,integer],integer),
            'EVP_DecryptUpdate':([pointer,pointer,length,pointer,integer],integer),
            'EVP_EncryptFinal_ex':([pointer,pointer,length],integer),
            'EVP_DecryptFinal_ex':([pointer,pointer,length],integer),
        }
        for name,(arguments,result) in signatures.items():
            function=getattr(self.lib,name);function.argtypes=arguments;function.restype=result
        if not self.lib.EVP_aes_256_gcm():raise ValueError('Native AES-256-GCM unavailable')

    @staticmethod
    def checked(result):
        if result!=1:raise ValueError('Native AES-GCM operation or authentication failed')

    def crypt(self,nonce,data,aad,decrypt=False):
        if (type(nonce) is not bytes or len(nonce)!=12 or type(data) is not bytes or type(aad) is not bytes
                or len(data)>16777216 or len(aad)>65536 or (decrypt and len(data)<16)):
            raise ValueError('Bounded AES-GCM buffers and 96-bit nonce required')
        context=self.lib.EVP_CIPHER_CTX_new()
        if not context:raise MemoryError('Native cipher context unavailable')
        try:
            prefix='EVP_Decrypt' if decrypt else 'EVP_Encrypt'
            initialize=getattr(self.lib,prefix+'Init_ex');update=getattr(self.lib,prefix+'Update');finish=getattr(self.lib,prefix+'Final_ex')
            key_buffer=ctypes.create_string_buffer(self.key);nonce_buffer=ctypes.create_string_buffer(nonce)
            associated_buffer=ctypes.create_string_buffer(aad)
            body=data[:-16] if decrypt else data;input_buffer=ctypes.create_string_buffer(body)
            output=ctypes.create_string_buffer(len(body)+16);length=ctypes.c_int()
            self.checked(initialize(context,self.lib.EVP_aes_256_gcm(),None,None,None))
            self.checked(self.lib.EVP_CIPHER_CTX_ctrl(context,0x9,12,None))
            self.checked(initialize(context,None,None,key_buffer,nonce_buffer))
            if aad:self.checked(update(context,None,ctypes.byref(length),associated_buffer,len(aad)))
            self.checked(update(context,output,ctypes.byref(length),input_buffer,len(body)))
            total=length.value
            if decrypt:
                tag=ctypes.create_string_buffer(data[-16:])
                self.checked(self.lib.EVP_CIPHER_CTX_ctrl(context,0x11,16,tag))
            self.checked(finish(context,ctypes.byref(output,total),ctypes.byref(length)))
            total+=length.value
            if total!=len(body):raise ValueError('Unexpected AES-GCM output length')
            if decrypt:return output.raw[:total]
            tag=ctypes.create_string_buffer(16)
            self.checked(self.lib.EVP_CIPHER_CTX_ctrl(context,0x10,16,tag))
            return output.raw[:total]+tag.raw
        finally:
            self.lib.EVP_CIPHER_CTX_free(context)

    def encrypt(self,nonce,data,associated_data):return self.crypt(nonce,data,associated_data)
    def decrypt(self,nonce,data,associated_data):return self.crypt(nonce,data,associated_data,True)


def cipher_provider(key,config):
    provider=config.get('provider','cryptography')
    if provider=='cryptography':
        if set(config)-{'enabled','key_file','provider'}:raise ValueError('Unexpected cryptography provider configuration')
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return AESGCM(key)
    if provider=='openssl-evp':
        if set(config)!={'enabled','key_file','provider','library','library_sha256'}:raise ValueError('Pinned EVP provider configuration required')
        return OpenSSLAESGCM(key,config['library'],config['library_sha256'])
    raise ValueError('Unknown AEAD provider; no automatic fallback')
