import sys
from playwright.sync_api import sync_playwright
B=sys.argv[1]
with sync_playwright() as p:
    b=p.chromium.launch()
    for w in (375,390,1280):
        pg=b.new_page(viewport={"width":w,"height":900})
        pg.goto(B+"/login"); pg.fill('[data-testid=login-email]',"ada@example.com"); pg.fill('[data-testid=login-password]',"correct horse"); pg.click('[data-testid=login-submit]'); pg.wait_for_selector('[data-testid=current-user]')
        m=pg.evaluate("""()=>{const b=document.querySelector('[data-testid=logout-button]');const lh=parseFloat(getComputedStyle(b).lineHeight)||20;
        const r=document.createRange();r.selectNodeContents(b);const lines=new Set([...r.getClientRects()].map(x=>Math.round(x.top))).size;
        const svg=document.querySelector('.brand svg').getBoundingClientRect();
        return {logout_text_lines:lines, brand_icon:[Math.round(svg.width),Math.round(svg.height)]}}""")
        print(w,m); pg.close()
    b.close()
