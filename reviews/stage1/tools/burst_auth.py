import json,time,sys,urllib.request,concurrent.futures as cf
from collections import Counter
B=sys.argv[1]
def call(p,b):
    r=urllib.request.Request(B+p,data=json.dumps(b).encode(),method="POST",headers={"Content-Type":"application/json"})
    t=time.time()
    try:
        with urllib.request.urlopen(r,timeout=15) as x: return x.status,time.time()-t
    except urllib.error.HTTPError as e: return e.code,time.time()-t
for run in range(3):
    call("/_test/reset",{"currency":"EUR","minor_units":2,"users":[]})
    with cf.ThreadPoolExecutor(50) as ex: s=list(ex.map(lambda i: call("/auth/signup",{"email":f"v{i}@x.io","password":"12345678","display_name":"V"}),range(50)))
    with cf.ThreadPoolExecutor(50) as ex: l=list(ex.map(lambda i: call("/auth/login",{"email":f"v{i}@x.io","password":"12345678"}),range(50)))
    print("run",run,"signups",dict(Counter(x for x,_ in s)),"max %.2fs"%max(t for _,t in s),"| logins",dict(Counter(x for x,_ in l)),"max %.2fs"%max(t for _,t in l), "| >5s:",sum(t>5 for _,t in s+l))
