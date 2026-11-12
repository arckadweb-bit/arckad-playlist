#!/usr/bin/env python3
"""Build a reproducible Italian playlist. Public discovery feeds are NOT playback guarantees.
No proxies, DRM handling, geolocation spoofing or shared session tokens are introduced.
"""
import argparse, concurrent.futures, csv, datetime as dt, hashlib, ipaddress, json
import os, re, shutil, subprocess, time, unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlunparse
from hls_quality import inspect_hls, session_rejection

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'Playlists'
SOURCES = {
 'fulgione': 'https://davidefulgione.com/tv.m3u',
 'iptv-org-it': 'https://iptv-org.github.io/iptv/countries/it.m3u',
 'iptv-org-ita': 'https://iptv-org.github.io/iptv/languages/ita.m3u',
 'tundrak-tv': 'https://raw.githubusercontent.com/Tundrak/IPTV-Italia/main/iptvita.m3u',
 'tundrak-radio': 'https://raw.githubusercontent.com/Tundrak/IPTV-Italia/main/ipradioita.m3u',
 'pluto-app': 'https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/plutotv_it.m3u',
 'pluto-regions': 'https://raw.githubusercontent.com/davkattun/pluto-tv-regions/main/output/m3u/pluto-it.m3u',
 'samsung-app': 'https://raw.githubusercontent.com/BuddyChewChew/app-m3u-generator/main/playlists/samsungtvplus_it.m3u',
 'rakuten': 'https://raw.githubusercontent.com/Free-TV/IPTV/master/lists/zz_vod_it.md',
 'radio-browser': 'https://de1.api.radio-browser.info/json/stations/bycountrycodeexact/IT?hidebroken=true&limit=10000',
}
PROTOCOLS = 'http,https,tcp,tls,crypto'
VIDEO = {'h264', 'hevc'}
AUDIO = {'aac', 'mp3', 'ac3', 'eac3', 'alac', 'pcm_s16le'}
SESSION_KEYS = {'jwt','token','authorization','auth','hdnts','hdnea','signature','policy','expires','rj-tok','sec'}


def utc(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
def suffix(source): return '.json' if source == 'radio-browser' else '.md' if source == 'rakuten' else '.m3u'
def clean_name(name):
    name = re.sub(r'\[(?:DAB|FM|HD|SD|.*?geo.*?|.*?not.*?24.*?)\]', '', name, flags=re.I)
    name = re.sub(r'\((?:\d{3,4}p|HD|SD|Italy|Germany)\)', '', name, flags=re.I)
    name = re.sub(r'\((?:MP3|AAC|AAC\+|OGG)(?:[ )0-9kKbBsSpP+.-]*)\)', '', name, flags=re.I)
    name = re.sub(r'\b(?:HD|FHD|UHD|SD|4K|\d{2,3}\s?kbps)\b', '', name, flags=re.I)
    return re.sub(r'\s+', ' ', name).strip(' -–\t#')

def normalize(name):
    name = unicodedata.normalize('NFKD', clean_name(name)).encode('ascii', 'ignore').decode().lower()
    name = re.sub(r'[^a-z0-9+]', '', name)
    return {'mediasetitaliausa':'mediasetitalia','mediasetitaliaaustralia':'mediasetitalia',
            '20':'20mediaset','mediaset20':'20mediaset','27':'twentyseven','27twentyseven':'twentyseven',
            'mediaset27twentyseven':'twentyseven','raiuno':'rai1','raidue':'rai2','raitre':'rai3','retequattro':'rete4',
            'canalecinque':'canale5','italiauno':'italia1','la7':'la7',
            'rdsradiodimensionesuono':'rds','radiodimensionesuono':'rds','rds100grandisuccessi':'rds',
            'rtl1025hitradio':'rtl1025','rmc':'radiomontecarlo','rmcradiomontecarlo':'radiomontecarlo',
            'radioitaliasolomusicaitaliana':'radioitalia','virginradioitalia':'virginradio','virginradioitaly':'virginradio',
            'radiomariaitaly':'radiomaria','r101fm':'r101','radiomontecarlofm':'radiomontecarlo',
            'radiorai1':'rairadio1','radiorai2':'rairadio2','radiorai3':'rairadio3',
            'rtl1025fm':'rtl1025','radiodeejayfm':'radiodeejay'}.get(name,name)


def public_url(url):
    try:
        p=urlparse(url)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password: return False
        if p.hostname.lower() in ('localhost',) or p.hostname.lower().endswith(('.local','.internal')): return False
        try: return ipaddress.ip_address(p.hostname).is_global
        except ValueError: return True
    except ValueError: return False


def entry(name,url,source,attrs=None,kind='tv'):
    attrs=attrs or {}
    return dict(name=clean_name(name), url=url.strip(), source=source, kind=kind,
                epg=attrs.get('tvg-id',''), logo=attrs.get('tvg-logo',''), group=attrs.get('group-title',''),
                declared=name, headers_required=False)


def parse_m3u(text,source):
    result=[]; metadata=None; headers=False
    for line in text.lstrip('\ufeff').splitlines():
        line=line.strip()
        if line.startswith('#EXTINF:'):
            # Split on the first comma outside quoted attributes; names can contain commas.
            parts=re.split(r',(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)',line,maxsplit=1)
            attrs=dict(re.findall(r'([\w-]+)="([^\"]*)"',parts[0]))
            metadata=(parts[1] if len(parts)>1 else attrs.get('tvg-name','Canale'),attrs);headers=False
        elif line.startswith(('#EXTVLCOPT:http-', '#KODIPROP:')): headers=True
        elif line and not line.startswith('#') and metadata:
            name,attrs=metadata
            e=entry(name,line,source,attrs,'radio' if source=='tundrak-radio' else 'tv')
            e['headers_required']=headers;result.append(e);metadata=None
    return result


def read_source(source):
    text=(OUT/'sources'/(source+suffix(source))).read_text(encoding='utf-8-sig')
    if source=='radio-browser':
        result=[]
        for r in json.loads(text):
            if r.get('countrycode')!='IT': continue
            url=r.get('url') or r.get('url_resolved','')
            e=entry(r['name'],url,source,{'tvg-logo':r.get('favicon',''),'group-title':'Radio'},'radio')
            e['stationuuid']=r.get('stationuuid'); result.append(e)
        return result
    if source=='rakuten':
        result=[]
        for line in text.splitlines():
            if not line.startswith('|') or '[>](http' not in line: continue
            cells=[x.strip() for x in line.split('|')]
            url=re.search(r'\[>\]\((https?://[^)]+)\)',cells[3])
            if not url: continue
            logo=re.search(r'src="([^\"]+)"',cells[4])
            result.append(entry(cells[2].replace('Ⓢ','').replace('Ⓖ',''),url[1],source,
                                {'tvg-logo':logo[1] if logo else '', 'tvg-id':cells[5] if len(cells)>5 else ''}))
        return result
    return parse_m3u(text,source)


def download(source,url):
    dest=OUT/'sources'/(source+suffix(source));temp=dest.with_suffix('.download')
    p=subprocess.run(['curl','-fLsS','--max-time','45','--max-filesize','20000000',
                      '-A','ARCKADPlaylist/1.0',url,'-o',str(temp)],capture_output=True,text=True)
    if p.returncode: return {'source':source,'url':url,'ok':False,'error':p.stderr[:300]}
    temp.replace(dest)
    return {'source':source,'url':url,'ok':True,'bytes':dest.stat().st_size}


def provider(e):
    s=(e['name']+' '+e['url']+' '+e['logo']).lower()
    if 'rakuten' in s: return 'Rakuten TV'
    if 'pluto' in s or '/plu-' in s or e['source'].startswith('pluto'): return 'Pluto TV'
    if '/stvp-' in s or 'samsung' in s or e['source']=='samsung-app': return 'Samsung TV Plus'
    return 'Radio' if e['kind']=='radio' else 'TV italiana'


def identity_groups(entries):
    parent=list(range(len(entries)))
    def find(i):
        while parent[i]!=i: parent[i]=parent[parent[i]];i=parent[i]
        return i
    seen={}
    for i,e in enumerate(entries):
        kind=e['kind']; keys=[(kind,'url',e['url'])]
        if kind=='radio':
            radio_name=normalize(e['name'])
            if radio_name.startswith('radio') and len(radio_name)>7: radio_name=radio_name[5:]
            keys.append((kind,'radio-brand',radio_name))
        platform=provider(e)
        if platform=='Pluto TV':
            platform_name=re.sub(r'(?i)^pluto\s*tv\s*|\s*[–—-]\s*pluto\s*tv$', '',e['name']).strip()
            keys.append((kind,'pluto-name',normalize(platform_name)))
            for value in (e['url'],e['logo']):
                match=re.search(r'(?:/plu-|/channels?/)([a-f0-9]{24})',value)
                if match: keys.append((kind,'pluto-id',match[1]))
        if platform=='Rakuten TV':
            name=re.sub(r'(?i)^rakuten\s*tv\s*|\s*[–—-]\s*rakuten\s*tv$', '',e['name']).strip()
            keys.append((kind,'rakuten-name',normalize(name)))
        if normalize(e['name']): keys.append((kind,'name',normalize(e['name'])))
        epg=e['epg']
        # Remove variant suffixes, not country/language. IDs shared by unrelated channels are excluded.
        if epg and epg.lower() not in ('canale.it','undefined','null'):
            epg=re.sub(r'@(?:sd|hd|fhd|uhd|4k)$','',epg,flags=re.I)
            keys.append((kind,'id',epg.lower()))
        for k in keys:
            if k in seen: parent[find(i)]=find(seen[k])
            else: seen[k]=i
    groups=defaultdict(list)
    for i,e in enumerate(entries): groups[find(i)].append(e)
    return list(groups.values())


def run(command,timeout):
    try:
        p=subprocess.run(command,capture_output=True,text=True,timeout=timeout)
        return p.returncode,p.stdout,p.stderr
    except subprocess.TimeoutExpired: return 124,'','timeout'


def inspect_stream(url,timeout):
    start=time.monotonic();r={'url':url,'checked_at':utc(),'status':'failed'}
    def finish(status,reason='',**kw):
        r.update(status=status,reason=reason,elapsed=round(time.monotonic()-start,2),**kw);return r
    if not public_url(url): return finish('unsupported','URL non pubblico o protocollo non HTTP/HTTPS')
    if urlparse(url).path.lower().endswith('.mpd'): return finish('unsupported','DASH non supportato dal player tvOS attuale')
    if reason := session_rejection(url):
        return finish('session_url',reason)
    if True:  # Relinkers and extensionless endpoints can also redirect to HLS masters.
        detailed=inspect_hls(url,timeout,run,PROTOCOLS)
        if detailed is not None and detailed['status']=='verified':
            return finish(**detailed)
        # Alcuni CDN legano i segmenti alla sessione del player: riprovare dal master originale.
    common=['-protocol_whitelist',PROTOCOLS,'-rw_timeout','8000000']
    rc,out,err=run(['ffprobe','-v','error',*common,'-analyzeduration','10000000','-probesize','10000000',
                    '-show_streams','-show_format','-of','json',url],timeout)
    if rc: return finish('timeout' if rc==124 else 'failed',err[-600:])
    try: data=json.loads(out)
    except ValueError: return finish('failed','Risposta probe non valida')
    streams=data.get('streams',[]);fmt=data.get('format',{}).get('format_name','')
    video=[s for s in streams if s.get('codec_type')=='video' and not s.get('disposition',{}).get('attached_pic')]
    audio=[s for s in streams if s.get('codec_type')=='audio']
    if not audio: return finish('unsupported','Nessuna traccia audio rilevata',format=fmt)
    aud=next((s for s in audio if s.get('codec_name') in AUDIO),None)
    if not aud: return finish('unsupported','Codec audio non previsto per il player',format=fmt)
    vids=[s for s in video if s.get('codec_name') in VIDEO]
    if video and not vids: return finish('unsupported','Codec video non previsto per il player',format=fmt)
    # AVPlayer accepts HLS for TV, progressive MP3/AAC/MP4 for audio. Exclude MPEG-TS over bare HTTP.
    if video and 'hls' not in fmt: return finish('unsupported','TV non HLS: compatibilità AVPlayer non verificata',format=fmt)
    if not video and not any(f in fmt.split(',') for f in ('hls','mp3','aac','mov','m4a','wav')):
        return finish('unsupported','Contenitore radio non previsto per AVPlayer',format=fmt)
    vid=max(vids,key=lambda s:(s.get('height',0),s.get('width',0))) if vids else None
    cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error',*common,'-analyzeduration','10000000',
         '-probesize','10000000','-threads','1','-i',url]
    if vid: cmd+=['-map',f"0:{vid['index']}"]
    cmd+=['-map',f"0:{aud['index']}",'-t','3','-threads','1','-f','framehash','-']
    rc,decoded,err=run(cmd,timeout)
    counts={}
    for line in decoded.splitlines():
        if not line or line.startswith('#'):continue
        fields=line.split(',')
        if len(fields)>=6:
            try:
                if int(fields[4])>0: counts[int(fields[0])]=counts.get(int(fields[0]),0)+1
            except ValueError:pass
    audio_frames=counts.get(1 if vid else 0,0);video_frames=counts.get(0,0) if vid else 0
    if rc or audio_frames<10 or (vid and video_frames<10):
        return finish('timeout' if rc==124 else 'decode_failed',err[-600:] or 'Campione audio/video insufficiente')
    return finish('verified',format=fmt,height=vid.get('height',0) if vid else 0,
                  width=vid.get('width',0) if vid else 0,video_codec=vid.get('codec_name','') if vid else '',
                  audio_codec=aud['codec_name'],bitrate=int(aud.get('bit_rate') or 0),
                  decoded_frames=video_frames,decoded_audio_frames=audio_frames,sample_seconds=3,has_video=bool(vid))


def category(e):
    p=provider(e)
    if e['kind']=='radio': return '10 | Radio italiane'
    if p=='Pluto TV': return '07 | Pluto TV'
    if p=='Rakuten TV': return '08 | Rakuten TV'
    if p=='Samsung TV Plus': return '09 | Samsung TV Plus'
    name=normalize(e['name'])
    if name.startswith('rai'): return '01 | Rai'
    if name in ['rete4','canale5','italia1','20mediaset','mediaset20','iris','la5','cine34','focus','mediasetextra','topcrime','italia2','twentyseven','27twentyseven','tgcom24','boing','cartoonito','mediasetitalia']: return '02 | Mediaset'
    groups=e['group'].lower()
    if 'music' in groups or 'radio' in name: return '06 | Musica e Radio TV'
    if any(x in groups for x in ['news','sport']): return '04 | Informazione e sport'
    if any(x in groups for x in ['movie','cinema','series','film']): return '05 | Cinema e serie'
    return '03 | Nazionali e locali'


def rank(e):
    r=e['check'];p=provider(e)
    # Prefer highest measured resolution; HTTPS and primary feeds break ties.
    return (not bool(re.search(r'(?i)mediaset italia (?:usa|australia)',e['name'])),
            r.get('height',0),e['url'].startswith('https:'),r.get('bitrate',0),
            e['source'] in ('fulgione','tundrak-tv','tundrak-radio'),p!='Samsung TV Plus')


def safe(s): return str(s).replace('"',"'").replace('\n',' ').replace('\r',' ')
def write_m3u(path,selected):
    lines=['#EXTM3U x-tvg-url="https://iptv-epg.org/files/epg-it.xml"',
           '# ARCKAD TV - '+utc(), '# Fonti: Fulgione; iptv-org; Tundrak; Radio Browser; app-m3u-generator; pluto-tv-regions; Free-TV/IPTV', '# Verifica breve FFmpeg; disponibilità e compatibilità tvOS non garantite nel tempo.']
    for e in selected:
        r=e['check'];label=e['name'];h=r.get('height',0)
        if h>=720: label+= ' UHD' if h>=2160 else ' HD'
        identity=e['epg'] or ('arckad.'+hashlib.sha256((e['kind']+normalize(e['name'])).encode()).hexdigest()[:16])
        lines.append(f'#EXTINF:-1 tvg-id="{safe(identity)}" tvg-name="{safe(e["name"])}" tvg-logo="{safe(e["logo"])}" group-title="{category(e)}",{safe(label)}')
        lines.append(e['url'])
    tmp=path.with_suffix('.tmp');tmp.write_text('\n'.join(lines)+'\n');tmp.replace(path)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--refresh',action='store_true');ap.add_argument('--workers',type=int,default=10)
    ap.add_argument('--timeout',type=int,default=22);ap.add_argument('--resume',action='store_true');ap.add_argument('--limit',type=int);ap.add_argument('--retry-failed',action='store_true');ap.add_argument('--assemble-only',action='store_true',help='Ricompone i risultati esistenti senza dichiararli nuovi test')
    args=ap.parse_args()
    for tool in ('curl','ffmpeg','ffprobe'):
        if not shutil.which(tool): raise SystemExit(f'Manca {tool}')
    (OUT/'sources').mkdir(parents=True,exist_ok=True);(OUT/'reports').mkdir(exist_ok=True)
    source_report=[]
    if args.refresh:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            source_report=list(pool.map(lambda pair:download(*pair),SOURCES.items()))
        (OUT/'reports'/'sources.json').write_text(json.dumps(source_report,indent=2))
        # Never silently reuse yesterday's feed after a failed download.
        available={r['source'] for r in source_report if r['ok']}
        if len(available) != len(SOURCES):
            raise SystemExit('Aggiornamento incompleto delle fonti: pubblicazione precedente conservata; vedere sources.json')
    else: available={s for s in SOURCES if (OUT/'sources'/(s+suffix(s))).exists()}
    entries=[]
    for source in SOURCES:
        if source in available: entries+=read_source(source)
    # Try HTTPS equivalents of public HTTP addresses, retaining the original as an alternative.
    secure=[]
    for e in entries:
        parsed=urlparse(e['url'])
        if parsed.scheme=='http' and public_url(e['url']):
            try: ipaddress.ip_address(parsed.hostname); continue
            except ValueError: pass
            host=parsed.netloc[:-3] if parsed.netloc.endswith(':80') else parsed.netloc
            secure.append({**e,'url':urlunparse(parsed._replace(scheme='https',netloc=host)),'https_candidate':True})
    entries+=secure
    urls=sorted({e['url'] for e in entries})
    if args.limit: urls=urls[:args.limit]
    cache={};journal=OUT/'reports'/'checks.jsonl'
    if (args.resume or args.assemble_only) and journal.exists():
        for line in journal.read_text().splitlines():
            try:
                r=json.loads(line)
                if args.assemble_only or (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(r['checked_at'])).total_seconds()<21600: cache[r['url']]=r
            except (ValueError,KeyError): pass
    pending=[u for u in urls if u not in cache or (args.retry_failed and cache[u]['status'] in ('failed','timeout','decode_failed','error'))]
    if args.assemble_only and pending: raise SystemExit('Mancano risultati: eseguire i test prima della ricomposizione')
    print(f'{len(entries)} voci, {len(urls)} URL distinti; {len(pending)} test da eseguire',flush=True)
    with journal.open('a' if args.resume or args.assemble_only else 'w') as log, concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures={pool.submit(inspect_stream,u,args.timeout):u for u in pending}
        for n,f in enumerate(concurrent.futures.as_completed(futures),1):
            try:r=f.result()
            except Exception as ex:r={'url':futures[f],'checked_at':utc(),'status':'error','reason':str(ex)}
            cache[r['url']]=r;log.write(json.dumps(r)+'\n');log.flush()
            if n%50==0 or n==len(pending): print(f'Test {n}/{len(pending)}: '+str(dict(Counter(v['status'] for v in cache.values()))),flush=True)
    entries=[e for e in entries if e['url'] in cache]
    for e in entries:
        e['check']=cache[e['url']]
        try:
            ipaddress.ip_address(urlparse(e['url']).hostname)
            e['check']={**e['check'],'status':'unsupported','reason':'Sorgente su IP numerico: origine e stabilità non identificate'}
        except ValueError: pass
        if reason := session_rejection(e['url']):
            e['check']={**e['check'],'status':'session_url','reason':reason}
        if e['headers_required'] and e['check']['status']!='verified': e['check']={**e['check'],'status':'unsupported','reason':'Header specifici richiesti dalla sorgente'}
        # Discovered "radio" TV streams remain TV so they do not replace their audio counterpart.
        if e['check'].get('has_video'): e['kind']='tv'
        elif e['check']['status']=='verified': e['kind']='radio'
        if e['kind']=='radio' and normalize(e['name']) in ('rai1','rai2','rai3'):
            e['name']='Rai Radio '+normalize(e['name'])[-1]
    groups=identity_groups(entries);selected=[];unavailable=[];alternatives=[]
    for group in groups:
        good=[e for e in group if e['check']['status']=='verified']
        if not good: unavailable.append(group);continue
        winner=max(good,key=rank);selected.append(winner)
        alternatives.append({'name':winner['name'],'selected':winner['url'],'alternatives':list(dict.fromkeys(e['url'] for e in sorted(good,key=rank,reverse=True) if e['url']!=winner['url']))})
    selected.sort(key=lambda e:(category(e),normalize(e['name'])))
    assert len({e['url'] for e in selected})==len(selected),'URL duplicati nel risultato'
    assert len({(e['kind'],normalize(e['name'])) for e in selected})==len(selected),'Nomi duplicati nel risultato'
    if not selected: raise SystemExit('Nessun flusso verificato: playlist precedente conservata')
    # Avoid overwriting a working publication after a mass upstream outage.
    target=OUT/'ARCKAD_Verificata.m3u'
    previous=target.read_text().count('#EXTINF:') if target.exists() else 0
    publish=len(selected)>=max(1,previous//2) and not args.limit
    if publish:
        write_m3u(target,selected)
        write_m3u(OUT/'ARCKAD_TV_Verificata.m3u',[e for e in selected if e['kind']=='tv'])
        write_m3u(OUT/'ARCKAD_Radio_Verificata.m3u',[e for e in selected if e['kind']=='radio'])
    (OUT/'reports'/'selected.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
    (OUT/'reports'/'alternatives.json').write_text(json.dumps(alternatives,ensure_ascii=False,indent=2))
    with (OUT/'reports'/'catalogo.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['nome','tipo','piattaforma','fonte','stato','altezza','audio','data_test','motivo','url'])
        for e in entries:
            r=e['check'];w.writerow([e['name'],e['kind'],provider(e),e['source'],r['status'],r.get('height',''),r.get('audio_codec',''),r['checked_at'],r.get('reason',''),e['url']])
    summary={'generated_at':utc(),'sources':len(available),'entries':len(entries),'tested_urls':len(urls),
             'checks':dict(Counter(cache[u]['status'] for u in urls)), 'distinct_channels':len(groups),
             'selected':len(selected),'tv':sum(e['kind']=='tv' for e in selected),
             'radio':sum(e['kind']=='radio' for e in selected),'hd':sum(e['check'].get('height',0)>=720 for e in selected),
             'platforms':dict(Counter(provider(e) for e in selected)),'unavailable_channels':len(unavailable),'published':publish}
    (OUT/'reports'/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2),flush=True)
    if not publish: raise SystemExit('Pubblicazione fermata: test parziale o calo anomalo dei canali')

if __name__=='__main__': main()
