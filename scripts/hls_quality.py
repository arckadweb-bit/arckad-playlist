"""Inspect individual HLS renditions, including separate audio, before assigning HD."""
import json,re,time
from urllib.parse import urljoin,urlparse,parse_qs

SIGNED_KEYS={'jwt','token','authorization','auth','hdnts','hdnea','signature','policy','expires','rj-tok','sec'}

def session_rejection(url,now=None):
    now=time.time() if now is None else now
    p=urlparse(url);params={k.lower():v for k,v in parse_qs(p.query).items()}
    keys=set(params)&SIGNED_KEYS
    if not keys:return None
    # Known public broadcaster entry point; never strip or forge the signature.
    if p.hostname in {'hlslive-web-gcdn-skycdn-it.akamaized.net','livestream-conc-gii.akamaized.net'} and keys <= {'hdnts','hdnea'}:
        expiry=[]
        for k in keys:
            for value in params[k]:
                match=re.search(r'(?:^|~)exp=(\d+)(?:~|$)',value)
                if not match:return 'Firma del broadcaster senza scadenza verificabile'
                expiry.append(int(match[1]))
        if min(expiry)>now+86400:return None
        return 'Firma del broadcaster scaduta o con meno di 24 ore residue'
    return 'URL di sessione non adatto alla pubblicazione statica'


def attrs(line):
    return {m[1]:m[2] if m[2] is not None else m[3] for m in re.finditer(r'([A-Z0-9-]+)=(?:"([^"]*)"|([^,]*))',line)}


def variants(text,base):
    audio={};result=[];pending=None
    for line in text.splitlines():
        line=line.strip()
        if line.startswith('#EXT-X-MEDIA:'):
            a=attrs(line)
            if a.get('TYPE')=='AUDIO' and a.get('URI'):
                key=a.get('GROUP-ID','')
                if key not in audio or a.get('DEFAULT')=='YES':audio[key]=urljoin(base,a['URI'])
        elif line.startswith('#EXT-X-STREAM-INF:'):pending=attrs(line)
        elif pending and line and not line.startswith('#'):
            res=re.fullmatch(r'(\d+)x(\d+)',pending.get('RESOLUTION',''))
            if res:
                result.append(dict(url=urljoin(base,line),width=int(res[1]),height=int(res[2]),
                                   bandwidth=int(pending.get('BANDWIDTH','0')),audio_group=pending.get('AUDIO','')))
            pending=None
    for v in result:v['audio_url']=audio.get(v.pop('audio_group'))
    return sorted(result,key=lambda v:(v['height'],v['bandwidth']),reverse=True)


def inspect_hls(url,timeout,run,protocols):
    rc,body,err=run(['curl','-fsSL','--max-time','15','--max-filesize','2000000','-w','\n__URL__%{url_effective}',url],20)
    if rc:return None
    text,base=body.rsplit('\n__URL__',1)
    if '#EXT-X-STREAM-INF:' not in text:return None
    options=variants(text,base)
    if not options:return None
    common=['-protocol_whitelist',protocols,'-rw_timeout','8000000']
    failures=[]
    for v in options:
        rc,out,err=run(['ffprobe','-v','error',*common,'-analyzeduration','5000000','-probesize','5000000','-show_streams','-of','json',v['url']],timeout)
        if rc:failures.append(err[-150:]);continue
        try:streams=json.loads(out).get('streams',[])
        except ValueError:continue
        video=next((s for s in streams if s.get('codec_type')=='video' and s.get('codec_name') in ('h264','hevc') and s.get('height',0)>0),None)
        if not video:continue
        audio=next((s for s in streams if s.get('codec_type')=='audio' and s.get('codec_name') in ('aac','mp3','ac3','eac3')),None)
        if v['audio_url']:
            rc,aout,err=run(['ffprobe','-v','error',*common,'-show_streams','-of','json',v['audio_url']],timeout)
            if rc:failures.append(err[-150:]);continue
            try:audio=next((s for s in json.loads(aout).get('streams',[]) if s.get('codec_type')=='audio' and s.get('codec_name') in ('aac','mp3','ac3','eac3')),None)
            except ValueError:continue
        if not audio:continue
        cmd=['ffmpeg','-nostdin','-hide_banner','-loglevel','error',*common,'-threads','1','-i',v['url']]
        if v['audio_url']:cmd+=common+['-threads','1','-i',v['audio_url']]
        cmd+=['-map',f"0:{video['index']}",'-map',f"{1 if v['audio_url'] else 0}:{audio['index']}",'-t','3','-threads','1','-f','framehash','-']
        rc,frames,err=run(cmd,timeout)
        counts={0:0,1:0}
        for line in frames.splitlines():
            if line.startswith('#'):continue
            fields=line.split(',')
            if len(fields)>=6:
                try:
                    if int(fields[4])>0:counts[int(fields[0])]=counts.get(int(fields[0]),0)+1
                except ValueError:pass
        if rc or min(counts.values())<10:failures.append(err[-150:] or 'Campione insufficiente');continue
        return dict(status='verified',reason='',format='hls',height=video['height'],width=video['width'],
                    video_codec=video['codec_name'],audio_codec=audio['codec_name'],bitrate=int(audio.get('bit_rate') or 0),
                    decoded_frames=counts[0],decoded_audio_frames=counts[1],sample_seconds=3,has_video=True,
                    rendition_verified=True,manifest_max_height=options[0]['height'],
                    tested_video_url=v['url'],tested_audio_url=v['audio_url'])
    return dict(status='decode_failed',reason='Nessuna variante HLS decodificata: '+'; '.join(failures)[-600:])
