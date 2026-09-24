import struct, datetime
PS=4096
class DB:
    def __init__(s,path):
        s.f=open(path,'rb').read(); s.np=len(s.f)//PS
        s.pages_by_tdef={}
        for p in range(s.np):
            o=p*PS
            if s.f[o]==1 and s.f[o+1]==1:
                t=struct.unpack_from('<I',s.f,o+4)[0]
                s.pages_by_tdef.setdefault(t,[]).append(p)
    def pg(s,p): return s.f[p*PS:(p+1)*PS]
    def tdef(s,p):
        b=s.pg(p); buf=bytearray(b)
        nxt=struct.unpack_from('<I',b,4)[0]
        while nxt:
            b2=s.pg(nxt); buf+=b2[8:]; nxt=struct.unpack_from('<I',b2,4)[0]
        b=bytes(buf)
        ncols=struct.unpack_from('<H',b,0x2d)[0]
        nidx=struct.unpack_from('<I',b,0x2f)[0]; nridx=struct.unpack_from('<I',b,0x33)[0]
        off=0x3f+nridx*12
        cols=[]
        for i in range(ncols):
            c=b[off:off+25]; off+=25
            cols.append(dict(type=c[0],num=struct.unpack_from('<H',c,5)[0],offV=struct.unpack_from('<H',c,7)[0],
              fixed=bool(c[15]&1),offF=struct.unpack_from('<H',c,21)[0],len=struct.unpack_from('<H',c,23)[0],
              prec=c[11],scale=c[12]))
        for c in cols:
            l=struct.unpack_from('<H',b,off)[0]; off+=2
            c['name']=b[off:off+l].decode('utf-16le'); off+=l
        return cols
    def text(s,d):
        if len(d)>=2 and d[0]==0xff and d[1]==0xfe:
            out=[];comp=True;i=2
            while i<len(d):
                if d[i]==0: comp=not comp; i+=1; continue
                if comp: out.append(chr(d[i])); i+=1
                else:
                    if i+1<len(d): out.append(d[i:i+2].decode('utf-16le','replace'))
                    i+=2
            return ''.join(out)
        return d.decode('utf-16le','replace')
    def lval(s,ptr):
        pg=ptr>>8; r=ptr&0xff; b=s.pg(pg)
        st=struct.unpack_from('<H',b,14+r*2)[0]&0x1fff
        end=PS if r==0 else struct.unpack_from('<H',b,14+(r-1)*2)[0]&0x1fff
        return b[st:end]
    def memo(s,d):
        if len(d)<12: return None
        ln=struct.unpack_from('<I',d,0)[0]; fl=ln>>24; ln&=0xffffff
        if fl&0x80: raw=d[12:12+ln]
        elif fl&0x40: raw=s.lval(struct.unpack_from('<I',d,4)[0])[:ln]
        else:
            raw=b'';ptr=struct.unpack_from('<I',d,4)[0]
            while ptr and len(raw)<ln:
                x=s.lval(ptr); ptr=struct.unpack_from('<I',x,0)[0]; raw+=x[4:]
            raw=raw[:ln]
        return s.text(raw)
    def val(s,c,d):
        t=c['type']
        if t==2: return d[0]
        if t==3: return struct.unpack('<h',d[:2])[0]
        if t==4: return struct.unpack('<i',d[:4])[0]
        if t==5: return struct.unpack('<q',d[:8])[0]/10000
        if t==6: return struct.unpack('<f',d[:4])[0]
        if t==7: return struct.unpack('<d',d[:8])[0]
        if t==8: return datetime.datetime(1899,12,30)+datetime.timedelta(days=struct.unpack('<d',d[:8])[0])
        if t==10: return s.text(d)
        if t==12: return s.memo(d)
        if t==16:
            neg=d[0]&0x80; v=0
            for k in (1,5,9,13): v=(v<<32)|struct.unpack_from('<I',d,k)[0]
            v=v/10**c['scale']; return -v if neg else v
        return d.hex()
    def rows(s,tp):
        cols=s.tdef(tp)
        for p in s.pages_by_tdef.get(tp,[]):
            b=s.pg(p); n=struct.unpack_from('<H',b,12)[0]
            for r in range(n):
                raw=struct.unpack_from('<H',b,14+r*2)[0]
                if raw&0x8000: continue
                st=raw&0x1fff; end=PS if r==0 else struct.unpack_from('<H',b,14+(r-1)*2)[0]&0x1fff
                rb=b[st:end]
                if raw&0x4000:
                    ptr=struct.unpack_from('<I',rb,0)[0]; rb=s.lval(ptr)
                yield s.row(cols,rb)
    def row(s,cols,rb):
        nc=struct.unpack_from('<H',rb,0)[0]; bm=(nc+7)//8
        mask=rb[len(rb)-bm:]
        re=len(rb)-1
        nv=struct.unpack_from('<H',rb,re-bm-1)[0]
        vo=[struct.unpack_from('<H',rb,re-bm-3-i*2)[0] for i in range(nv+1)]
        out={}
        for c in cols:
            n=c['num']
            if n>=nc: out[c['name']]=None; continue
            present=(mask[n//8]>>(n%8))&1
            if c['type']==1: out[c['name']]=bool(present); continue
            if not present: out[c['name']]=None; continue
            if c['fixed']:
                o=2+c['offF']; out[c['name']]=s.val(c,rb[o:o+c['len']])
            else:
                if c['offV']>=nv: out[c['name']]=None; continue
                out[c['name']]=s.val(c,rb[vo[c['offV']]:vo[c['offV']+1]])
        return out
    def tables(s):
        res={}
        for r in s.rows(2):
            if r.get('Type')==1 and r.get('Name'): res[r['Name']]=r['Id']&0xffffff
        return res
