import json, urllib.request, uuid, sys
from playwright.sync_api import sync_playwright
B="http://127.0.0.1:18475"; PW="correct horse"
def call(m,p,b=None,t=None):
    h={"Content-Type":"application/json","Idempotency-Key":uuid.uuid4().hex}
    if t: h["Authorization"]="Bearer "+t
    with urllib.request.urlopen(urllib.request.Request(B+p,data=None if b is None else json.dumps(b).encode(),method=m,headers=h)) as x:
        d=x.read(); return json.loads(d) if d else None
U=lambda h,b:{"id":"u_"+h,"email":h+"@e.com","password":PW,"display_name":h.title(),"handle":h,"balance":b}
call("POST","/_test/reset",{"currency":"EUR","minor_units":2,"users":[U("ada",10000),U("bob",1000),U("cy",0)]})
T={h:call("POST","/auth/login",{"email":h+"@e.com","password":PW})["token"] for h in ("ada","bob","cy")}
pub=call("POST","/payments",{"to_handle":"bob","amount":800,"note":"<b>x</b>","visibility":"public"},T["ada"])
prv=call("POST","/payments",{"to_handle":"bob","amount":300,"visibility":"private"},T["ada"])
r1=call("POST","/payments/%s/refunds"%pub["payment_id"],{"amount":100},T["bob"])
r2=call("POST","/payments/%s/refunds"%prv["payment_id"],{"amount":50},T["bob"])
ok=[]
with sync_playwright() as p:
    br=p.chromium.launch()
    for w in (390,1280):
        pg=br.new_page(viewport={"width":w,"height":900})
        pg.goto(B+"/"); pg.fill("[data-testid=login-email]","cy@e.com"); pg.fill("[data-testid=login-password]",PW); pg.click("[data-testid=login-submit]")
        pg.wait_for_selector("[data-testid=activity-item-%s]"%r1["payment_id"])
        row=pg.locator("[data-testid=activity-item-%s]"%r1["payment_id"])
        ok.append(row.locator("[data-role=refund-badge]").count()==1)
        ok.append(pg.locator("[data-testid=activity-item-%s]"%r2["payment_id"]).count()==0)   # private refund hidden from third party
        ok.append(pg.locator("[data-testid=activity-note-%s]"%r1["payment_id"]).text_content()=="<b>x</b>")  # escaped
        ok.append(pg.evaluate("document.documentElement.scrollWidth<=innerWidth"))
        pg.screenshot(path="/Users/sebastienhenry/dark-factory/band-work/result/reviews/stage4/shots/S4.U1/third-party-%d.png"%w,full_page=True)
    br.close()
print(ok, "PASS" if all(ok) else "FAIL")
