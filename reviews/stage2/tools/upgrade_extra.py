import json,urllib.request,sys
def call(base,m,p,b=None,t=None,k=None):
    h={"Content-Type":"application/json"}
    if t:h["Authorization"]="Bearer "+t
    if k:h["Idempotency-Key"]=k
    r=urllib.request.Request(base+p,data=None if b is None else json.dumps(b).encode(),method=m,headers=h)
    try:
        with urllib.request.urlopen(r,timeout=15) as x: d=x.read(); return x.status,(json.loads(d) if d else None)
    except urllib.error.HTTPError as e: return e.code,json.loads(e.read() or b"null")
S1,S2=sys.argv[1],sys.argv[2]
U=lambda i,h,b:{"id":i,"email":h+"@e.com","password":"correct horse","display_name":h,"handle":h,"balance":b}
call(S1,"POST","/_test/reset",{"currency":"BHD","minor_units":3,"users":[U("u_a","a",10000),U("u_b","b",500),U("u_op","op",0)],"settlement_operator_ids":["u_op"],
  "payments":[{"id":"p_s","from_user_id":"u_a","to_user_id":"u_b","amount":1,"created_at":"2026-09-24T19:00:00+02:00"}]})
T={h:call(S1,"POST","/auth/login",{"email":h+"@e.com","password":"correct horse"})[1]["token"] for h in ("a","b","op")}
T["n"]=call(S1,"POST","/auth/signup",{"email":"n@e.com","password":"12345678","display_name":"N"})[1]["token"]
sp=call(S1,"POST","/splits",{"amount":1,"participant_handles":["a","b","n"]},T["a"],"sp")
z=sp[1]["requests"][0]["request_id"]; pz=call(S1,"POST","/requests/%s/pay"%z,{},T["b"],"pz")
st=call(S1,"POST","/settlements",{"transfers":[{"from_handle":"a","to_handle":"op","amount":7}]},T["op"],"st")
rq=call(S1,"POST","/requests",{"payer_handle":"b","amount":3},T["a"],"rq")[1]["request_id"]; call(S1,"POST","/requests/%s/decline"%rq,None,T["b"])
call(S1,"POST","/payments",{"to_handle":"b","amount":10**9},T["a"],"fail")
e1=call(S1,"GET","/_test/export")[1]
tot1={h:call(S1,"GET","/me",t=t)[1]["balance"] for h,t in T.items()}
print("import",call(S2,"POST","/_test/import",e1)[0])
me2={h:call(S2,"GET","/me",t=t)[1] for h,t in T.items()}
print("balances equal",all(me2[h]["total"]==tot1[h]==me2[h]["available"] for h in T), me2["a"]["minor_units"], me2["a"]["currency"])
print("replays split/zero-pay/settlement", call(S2,"POST","/splits",{"amount":1,"participant_handles":["a","b","n"]},T["a"],"sp")[1]==sp[1],
      call(S2,"POST","/requests/%s/pay"%z,{},T["b"],"pz")[1]==pz[1], call(S2,"POST","/settlements",{"transfers":[{"from_handle":"a","to_handle":"op","amount":7}]},T["op"],"st")[1]==st[1])
print("failed key reusable", call(S2,"POST","/payments",{"to_handle":"b","amount":1},T["a"],"fail")[0])
print("seeded offset payment last in b's feed", [p["payment_id"] for p in call(S2,"GET","/activity",t=T["b"])[1]["payments"]][-1])
print("operator kept", call(S2,"POST","/settlements",{"transfers":[{"from_handle":"b","to_handle":"a","amount":1}]},T["op"],"st2")[0])
print("declined request kept", [r["status"] for r in call(S2,"GET","/requests?status=declined",t=T["a"])[1]["requests"]])
e2=call(S2,"GET","/_test/export")[1]; print("re-import stable",call(S2,"POST","/_test/import",e2)[0], call(S2,"GET","/_test/export")[1]==e2)
