import json,urllib.request,sys
from playwright.sync_api import sync_playwright
B=sys.argv[1]
U=lambda i,h,b:{"id":i,"email":h+"@example.com","password":"correct horse","display_name":h.title(),"handle":h,"balance":b}
def reset():
    r=urllib.request.Request(B+"/_test/reset",data=json.dumps({"currency":"EUR","minor_units":2,"users":[U("u_ada","ada",10000),U("u_bob","bob",2500)]}).encode(),method="POST",headers={"Content-Type":"application/json"}); urllib.request.urlopen(r)
T=lambda t:'[data-testid="%s"]'%t
with sync_playwright() as p:
    b=p.chromium.launch()
    for mode in ("after-success","during-flight"):
        reset(); pg=b.new_page(viewport={"width":390,"height":900})
        reqs=[]; pg.on("request",lambda r: r.method=="POST" and r.url.endswith("/requests") and reqs.append(r.post_data))
        pg.goto(B+"/login"); pg.fill(T("login-email"),"bob@example.com"); pg.fill(T("login-password"),"correct horse"); pg.click(T("login-submit")); pg.wait_for_selector(T("wallet-available"))
        pg.fill(T("request-handle"),"ada"); pg.fill(T("request-amount"),"12.00"); pg.fill(T("request-note"),"taxi"); pg.click(T("request-submit"))
        if mode=="after-success": pg.wait_for_selector(T("request-success"))
        pg.fill(T("request-handle"),"bob"); pg.click(T("request-submit")); pg.wait_for_timeout(1500)
        print(mode,"posts",len(reqs),"request-error",pg.locator(T("request-error")).count(),"success",pg.locator(T("request-success")).count(), "btn", pg.inner_text(T("request-submit")))
        pg.close()
    b.close()
