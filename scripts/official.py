"""Read publicly embedded streams from broadcaster pages; no login/session extraction."""
import base64,html,json,re,subprocess,concurrent.futures as cf
from build_playlist import entry

def refresh(root,rows):
    rules=json.loads((root/'config/official_pages.json').read_text())
    def fetch(rule):
        page=rule['url'];p=subprocess.run(['curl','-fLsS','--max-time','25','--max-filesize','3000000',page],capture_output=True,text=True)
        urls=[];text=html.unescape(p.stdout.replace('\\/','/'))
        if p.returncode==0:
            if rule['mode']=='rai':
                urls=[u+'&output=7' for u in re.findall(r'https?://mediapolis\.rai\.it/relinker/relinkerServlet\.htm\?cont=\d+',text)]
            elif rule['mode']=='base64':
                for blob in re.findall(r"hlsPlayerData_\w+\s*=\s*'([A-Za-z0-9+/=]+)'",text):
                    try:urls.append(json.loads(base64.b64decode(blob))['src'])
                    except (ValueError,KeyError):pass
            else:urls=re.findall(r'https?://[^\s\"<>\x27]+?\.m3u8(?:\?[^\s\"<>\x27]*)?',text)
        result=[]
        for url in dict.fromkeys(urls):
            n=rule['number'];name=re.sub(r'\s*\[SENZA URL\]','',rows[n-1]['requested'])
            epg={'Italiana powered by Rai':'Italiana.it','Rai YoYo':'RaiYoyo.it','Rai 4K':'Rai4K.it','EQUtv':'EQUtv.it','Marcopolo':'Marcopolo.it','TRM h24':'TRMh24.it','Arte Investimenti':'ArteInvestimenti.it'}.get(name,'')
            e=entry(name,url,'official-page',{'tvg-id':epg});e['evidence']=page;result.append(e)
        return result,{'number':rule['number'],'page':page,'candidates':len(result),'ok':p.returncode==0}
    with cf.ThreadPoolExecutor(max_workers=5) as pool:results=list(pool.map(fetch,rules))
    entries=[e for es,_ in results for e in es]
    (root/'.cache/official.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2))
    (root/'reports/official-pages.json').write_text(json.dumps([r for _,r in results],ensure_ascii=False,indent=2))
    return entries
